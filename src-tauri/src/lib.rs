mod sidecar;

use std::path::{Path, PathBuf};
use std::sync::atomic::Ordering;
use std::sync::Arc;
use std::time::{Duration, Instant};

use tauri::{AppHandle, Emitter, Manager, RunEvent, State};
use tauri_plugin_opener::OpenerExt;

use sidecar::{FailureInfo, SidecarInfo, SidecarManager, SidecarState};

/// 返回 sidecar 地址（port + token）。sidecar 拉起前会短暂等待，保证前端总能拿到真值。
///
/// 注意：state 以 `Arc<SidecarManager>` 注册（supervisor 线程 + commands + 退出钩子共享同一实例），
/// 命令签名必须用 `State<Arc<SidecarManager>>`，否则 Tauri 报「state not managed」。
#[tauri::command]
fn get_sidecar_info(state: State<'_, Arc<SidecarManager>>) -> Result<SidecarInfo, String> {
    let deadline = Instant::now() + Duration::from_secs(20);
    loop {
        // 失败态且无手动重启请求时立即报错：熔断后 info 为 None，不提前退出的话
        // 前端每个请求都要挂满 20s 超时才拿到「sidecar 尚未就绪」
        if *state.state.lock().unwrap() == SidecarState::Failed
            && !state.restart_requested.load(Ordering::SeqCst)
        {
            return Err("sidecar 未运行".into());
        }
        if let Some(info) = state.info.lock().unwrap().clone() {
            return Ok(info);
        }
        if Instant::now() >= deadline {
            return Err("sidecar 尚未就绪".into());
        }
        std::thread::sleep(Duration::from_millis(200));
    }
}

/// 手动重启 sidecar（红态「重试」）：清零失败计数给满 3 次新尝试，并请求 supervisor
/// 重新拉起——存活监控与熔断等待两处都会消费 restart_requested（kill+reap 后再 spawn）。
#[tauri::command]
fn restart_sidecar(state: State<'_, Arc<SidecarManager>>) -> Result<(), String> {
    if state.stopping.load(Ordering::SeqCst) {
        return Err("应用正在退出".into());
    }
    *state.fail_count.lock().unwrap() = 0;
    *state.last_failure.lock().unwrap() = None;
    state.restart_requested.store(true, Ordering::SeqCst);
    log::info!("收到手动重启 sidecar 请求");
    Ok(())
}

/// 最近一次 sidecar 失败原因（不等 info：get_sidecar_info 在失败期会阻塞等待，
/// 探活失败后前端用本命令立即取原因展示红态文案）。
#[tauri::command]
fn get_sidecar_failure(state: State<'_, Arc<SidecarManager>>) -> Option<FailureInfo> {
    state.last_failure.lock().unwrap().clone()
}

/// 读文件末尾 max 字节并按 UTF-8 解析（lossy，容忍任意字节边界截断）。
fn tail_file(path: &Path, max: usize) -> String {
    use std::io::{Read, Seek, SeekFrom};
    let Ok(mut f) = std::fs::File::open(path) else {
        return format!("（不存在或不可读：{}）", path.display());
    };
    let len = f.metadata().map(|m| m.len()).unwrap_or(0);
    let start = len.saturating_sub(max as u64);
    if f.seek(SeekFrom::Start(start)).is_err() {
        return "（读取失败）".into();
    }
    let mut buf = Vec::new();
    let _ = f.take(len - start).read_to_end(&mut buf);
    let mut text = String::from_utf8_lossy(&buf).into_owned();
    if start > 0 {
        text.insert_str(0, "…（超长，仅保留末尾部分）\n");
    }
    text
}

/// 目录内最近修改的 .log 文件（tauri-plugin-log 的文件名随应用名变化，按规则找最稳）。
fn newest_log_in_dir(dir: &Path) -> Option<PathBuf> {
    std::fs::read_dir(dir)
        .ok()?
        .filter_map(|e| e.ok())
        .filter(|e| e.path().extension().map(|x| x == "log").unwrap_or(false))
        .max_by_key(|e| e.metadata().and_then(|m| m.modified()).ok())
        .map(|e| e.path())
}

/// 导出诊断报告（单个 txt，零新依赖）：应用/环境信息 + 最近失败原因 +
/// Rust 壳日志尾部 + sidecar 日志尾部 + 启动 stderr 留档。返回路径供前端 reveal。
#[tauri::command]
fn export_diagnostics(
    app: AppHandle,
    state: State<'_, Arc<SidecarManager>>,
    timestamp: String,
) -> Result<String, String> {
    let logs_dir = sidecar::data_dir().join("logs");
    std::fs::create_dir_all(&logs_dir).map_err(|e| format!("创建日志目录失败: {e}"))?;

    let mut report = String::new();
    report.push_str("==== 灵燕智能 诊断报告 ====\n");
    report.push_str(&format!("生成时间: {timestamp}\n"));
    report.push_str(&format!(
        "应用版本: {}  系统: {} {}\n",
        app.package_info().version,
        std::env::consts::OS,
        std::env::consts::ARCH
    ));
    if let Some(failure) = state.last_failure.lock().unwrap().clone() {
        report.push_str(&format!("最近失败: [{}] {}\n", failure.kind, failure.detail));
    } else {
        report.push_str("最近失败: 无记录\n");
    }

    report.push_str("\n---- Rust 壳日志（末尾部分） ----\n");
    let rust_log = app.path().app_log_dir().ok().and_then(|dir| newest_log_in_dir(&dir));
    match rust_log {
        Some(p) => report.push_str(&tail_file(&p, 200 * 1024)),
        None => report.push_str("（无 Rust 日志文件）\n"),
    }

    report.push_str("\n---- sidecar 日志（末尾部分） ----\n");
    report.push_str(&tail_file(&sidecar::data_dir().join("logs/sidecar.log"), 200 * 1024));

    report.push_str("\n---- sidecar 启动留档（本次拉起的 stderr） ----\n");
    report.push_str(&tail_file(&sidecar::boot_log_path(), 200 * 1024));

    report.push_str(
        "\n---- 隐私提示 ----\n本报告仅含日志文本，不含标书文件内容；但日志可能包含文件名或路径，发送前可自行检查。\n",
    );

    let out = logs_dir.join(format!(
        "diagnostics-{}.txt",
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_secs())
            .unwrap_or(0)
    ));
    std::fs::write(&out, report).map_err(|e| format!("写入诊断报告失败: {e}"))?;
    log::info!("诊断报告已导出: {}", out.display());
    Ok(out.to_string_lossy().into_owned())
}

/// 打开 sidecar 日志目录（data/logs：sidecar.log / sidecar-boot.log / 诊断报告都在这）。
/// 直接在 Rust 侧 reveal：前端拿不到该目录的绝对路径，走 reveal_in_folder 需多一次回传。
#[tauri::command]
fn reveal_sidecar_logs(app: AppHandle) -> Result<(), String> {
    let logs = sidecar::data_dir().join("logs");
    std::fs::create_dir_all(&logs).map_err(|e| format!("创建日志目录失败: {e}"))?;
    app.opener()
        .reveal_item_in_dir(logs.to_str().ok_or("路径含非法字符")?)
        .map_err(|e| format!("打开日志目录失败: {e}"))
}

/// 在系统文件管理器中定位文件。
///
/// path 仅允许两个前缀下的绝对路径（做 canonicalize 前缀校验），
/// 防止被诱导去打开任意敏感文件：`data/workspace/`（产物）与 `data/`（设置页的
/// 数据目录/日志入口）。非 Tauri 环境不可用。
#[tauri::command]
fn reveal_in_folder(app: AppHandle, path: String) -> Result<(), String> {
    let root = sidecar::workspace_dir()
        .canonicalize()
        .map_err(|e| format!("无法解析工作区路径: {e}"))?;
    let data_root = sidecar::data_dir()
        .canonicalize()
        .map_err(|e| format!("无法解析数据目录路径: {e}"))?;
    let target = PathBuf::from(&path)
        .canonicalize()
        .map_err(|e| format!("无法解析文件路径: {e}"))?;
    if !target.starts_with(&root) && !target.starts_with(&data_root) {
        return Err("路径不在允许范围内".into());
    }
    app.opener()
        .reveal_item_in_dir(target.to_str().ok_or("路径含非法字符")?)
        .map_err(|e| format!("打开所在目录失败: {e}"))
}

/// 退出确认放行（前端 ExitGuard 弹窗点「退出」后调用）：置 allow_exit 让
/// ExitRequested 拦截放行，再触发应用退出。窗口关闭路径不走本命令（前端直接
/// destroy()，见 ExitGuard）。
#[tauri::command]
fn confirm_exit(app: AppHandle, state: State<'_, Arc<SidecarManager>>) {
    state.allow_exit.store(true, Ordering::SeqCst);
    log::info!("用户确认退出（运行中任务将中断）");
    app.exit(0);
}

// ---------------------------------------------------------------------------
// 版本检查 + 更新提示（2026-09-15）：清单 = 官网 version.json（自建更新源，
// schema 见 docs/packaging.md）。更新源三层取值：环境变量 UPDATE_MANIFEST_URL >
// <数据目录>/updater.json 的 manifestUrl > DEFAULT_UPDATE_MANIFEST_URL 常量。
// 刻意不放设置界面：更新源是「前往下载」跳转的信任根，谁都能改就是引导恶意
// 下载页的入口——留在开发者可及的环境变量/文件层（改址免重编译），用户无感。
// ---------------------------------------------------------------------------

/// 内置默认更新清单地址；域名定稿后填入随版发布（空串=未配置，检查报「更新源尚未配置」）。
const DEFAULT_UPDATE_MANIFEST_URL: &str = "https://ddmdj.com/release/version.json";

/// 清单里 changes 要点条数上限（超出丢弃，防异常清单撑爆设置卡）。
const MAX_UPDATE_CHANGES: usize = 20;
/// 外链长度上限（https 前缀之外再卡一道，防异常长串）。
const MAX_URL_LEN: usize = 2048;

/// updater.json 配置文件（数据目录下）：{"manifestUrl": "https://…/version.json"}。
/// 文件不存在/坏 JSON/字段缺失 → None 静默落下一层（改址免重编译的运维通道）。
fn manifest_url_from_config() -> Option<String> {
    let text = std::fs::read_to_string(sidecar::data_dir().join("updater.json")).ok()?;
    let url = serde_json::from_str::<serde_json::Value>(&text)
        .ok()?
        .get("manifestUrl")?
        .as_str()?
        .trim()
        .to_string();
    (!url.is_empty()).then_some(url)
}

/// 更新源三层取值（None = 三层都未配置）。命中即整条采用，不做拼接。
fn resolve_manifest_url() -> Option<String> {
    if let Ok(url) = std::env::var("UPDATE_MANIFEST_URL") {
        let url = url.trim().to_string();
        if !url.is_empty() {
            log::info!("更新源：环境变量 UPDATE_MANIFEST_URL 覆盖");
            return Some(url);
        }
    }
    if let Some(url) = manifest_url_from_config() {
        log::info!("更新源：updater.json manifestUrl 覆盖");
        return Some(url);
    }
    (!DEFAULT_UPDATE_MANIFEST_URL.is_empty()).then(|| DEFAULT_UPDATE_MANIFEST_URL.to_string())
}

/// 剥 v/V 前缀并校验「数字段用点连接」形态（0.10.0 合法；0.1.x/空串/中文不合法）。
fn normalize_version(raw: &str) -> Option<String> {
    let t = raw.trim();
    let t = t.strip_prefix('v').or_else(|| t.strip_prefix('V')).unwrap_or(t);
    let ok = !t.is_empty()
        && t.split('.').all(|seg| !seg.is_empty() && seg.bytes().all(|b| b.is_ascii_digit()));
    ok.then(|| t.to_string())
}

/// 按字符截断（中文安全，非字节切片），截断补省略号；首尾空白先剥。
fn clamp_chars(s: &str, max: usize) -> String {
    let s = s.trim();
    if s.chars().count() <= max {
        return s.to_string();
    }
    format!("{}…", s.chars().take(max).collect::<String>())
}

/// 外链白名单式校验：仅 https 且长度合理。清单是远端内容，这里是它变成
/// 系统浏览器跳转前的唯一关口（本地测试清单地址可用 http，只管清单本身）。
fn valid_https_url(url: &str) -> bool {
    url.starts_with("https://") && url.len() <= MAX_URL_LEN
}

#[derive(serde::Deserialize)]
struct UpdateManifest {
    version: String,
    url: String,
    #[serde(rename = "notesUrl")]
    notes_url: Option<String>,
    #[serde(rename = "publishedAt")]
    published_at: Option<String>,
    highlights: Option<String>,
    changes: Option<Vec<String>>,
}

#[derive(serde::Serialize)]
#[serde(rename_all = "camelCase")]
struct LatestReleaseInfo {
    version: String,
    url: String,
    notes_url: Option<String>,
    published_at: Option<String>,
    highlights: Option<String>,
    changes: Vec<String>,
}

/// 查官网 version.json（5s 超时；sync 命令跑在 Tauri 线程池，不卡 UI 线程）。
/// 清单是远端内容，字段全部清洗（版本/链接校验、文本截断），不合法即整次判失败，
/// 返回人话错误——前端把它当「检查失败」展示，细节进日志。
#[tauri::command]
fn check_latest_version() -> Result<LatestReleaseInfo, String> {
    let Some(manifest_url) = resolve_manifest_url() else {
        return Err("更新源尚未配置".into());
    };
    log::info!("检查更新：GET {manifest_url}");
    let client = reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(5))
        .user_agent("tender-agent-updater")
        .build()
        .map_err(|e| format!("网络初始化失败: {e}"))?;
    let resp = client
        .get(&manifest_url)
        .send()
        .map_err(|_| "检查更新失败，可能是网络原因".to_string())?;
    if !resp.status().is_success() {
        return Err(format!("更新服务器返回 {}", resp.status()));
    }
    let manifest: UpdateManifest = resp.json().map_err(|_| "更新信息格式不正确".to_string())?;
    let version = normalize_version(&manifest.version).ok_or("更新信息版本号不合法")?;
    let url = manifest.url.trim().to_string();
    if !valid_https_url(&url) {
        return Err("更新信息下载链接不合法".into());
    }
    Ok(LatestReleaseInfo {
        version,
        url,
        notes_url: manifest
            .notes_url
            .map(|u| u.trim().to_string())
            .filter(|u| valid_https_url(u)),
        published_at: manifest.published_at.map(|s| clamp_chars(&s, 64)),
        highlights: manifest.highlights.map(|s| clamp_chars(&s, 200)),
        changes: manifest
            .changes
            .unwrap_or_default()
            .into_iter()
            .filter(|s| !s.trim().is_empty())
            .take(MAX_UPDATE_CHANGES)
            .map(|s| clamp_chars(&s, 200))
            .collect(),
    })
}

/// 系统浏览器打开「前往下载/完整发布说明」外链（清单下发，经 https-only 校验）。
/// Rust 侧调 opener 不经 ACL（同 reveal 系命令口径），capabilities 零改动。
#[tauri::command]
fn open_download_page(app: AppHandle, url: String) -> Result<(), String> {
    let url = url.trim();
    if !valid_https_url(url) {
        return Err("仅支持 https 链接".into());
    }
    app.opener()
        .open_url(url, None::<&str>)
        .map_err(|e| format!("打开浏览器失败: {e}"))
}

#[cfg(test)]
mod update_check_tests {
    use super::*;

    #[test]
    fn normalize_version_strips_prefix_and_validates() {
        assert_eq!(normalize_version("v0.1.2").as_deref(), Some("0.1.2"));
        assert_eq!(normalize_version("V1.20.3").as_deref(), Some("1.20.3"));
        assert_eq!(normalize_version("0.10.0").as_deref(), Some("0.10.0"));
        assert_eq!(normalize_version(" 0.1.0 ").as_deref(), Some("0.1.0"));
        assert_eq!(normalize_version("0.1.x"), None);
        assert_eq!(normalize_version("版本1"), None);
        assert_eq!(normalize_version(""), None);
        assert_eq!(normalize_version("v"), None);
    }

    #[test]
    fn clamp_chars_is_char_safe() {
        assert_eq!(clamp_chars("你好世界", 2), "你好…");
        assert_eq!(clamp_chars("  短文本  ", 10), "短文本");
        assert_eq!(clamp_chars("abc", 3), "abc");
    }

    #[test]
    fn https_url_validation() {
        assert!(valid_https_url("https://example.com/a?b=1"));
        assert!(!valid_https_url("http://example.com/"));
        assert!(!valid_https_url("javascript:alert(1)"));
        assert!(!valid_https_url(&format!("https://a/{}", "x".repeat(MAX_URL_LEN))));
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let mgr = Arc::new(SidecarManager::default());

    let app = tauri::Builder::default()
        // single-instance 必须第一个注册。agent.db 是单文件 SQLite + SqliteSaver 常驻连接，
        // GUI 双开会撞 checkpoint——单实例守卫是用户不可见的最简防线，不做任何互斥协调。
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            // 启动期（splash 尚在）二次双击：先收尾启动序列把主窗亮出来，否则主窗
            // visible=false 会被直接 show 出半成品；正常运行期该调用幂等直通。
            sidecar::reveal_main_from_splash(app);
            if let Some(w) = app.get_webview_window("main") {
                let _ = w.unminimize();
                let _ = w.show();
                let _ = w.set_focus();
            }
        }))
        // 记住窗口大小/位置（退出自动持久化到系统 app 配置目录），纯 plumbing 无 IPC。
        // splash 进拉黑名单：它是每次居中出生的固定尺寸一次性小窗，几何只由 tauri.conf
        // 的 center:true 决定；一旦被记住，插件在 window ready 时 restore 存档位置会盖掉
        // center（实测启动画面固定出现在屏幕左上方、与随后亮出的主窗完全错位），且该存档
        // 位置每次退出写回、之后每次启动复用。
        // flags 去掉 VISIBLE：插件默认含它，restore 会把 visible:false 的主窗提前
        // show 出来（与 splash 并存，用户实测「同时展示很怪异」）——显示时机只归
        // sidecar.rs 的 reveal_main_from_splash。DECORATIONS/FULLSCREEN 同理不跨启动恢复。
        .plugin(
            tauri_plugin_window_state::Builder::default()
                .with_denylist(&["splash"])
                .with_state_flags(
                    tauri_plugin_window_state::StateFlags::SIZE
                        | tauri_plugin_window_state::StateFlags::POSITION
                        | tauri_plugin_window_state::StateFlags::MAXIMIZED,
                )
                .build(),
        )
        // 日志后端（Stdout + 应用日志目录文件，轮转自带）：sidecar.rs 的 log:: 调用
        // 此前因无后端被静默丢弃。不开 Webview target——纯 Rust 侧 plumbing，零 IPC 权限。
        .plugin(
            tauri_plugin_log::Builder::new()
                .targets([
                    tauri_plugin_log::Target::new(tauri_plugin_log::TargetKind::Stdout),
                    tauri_plugin_log::Target::new(tauri_plugin_log::TargetKind::LogDir { file_name: None }),
                ])
                .level(log::LevelFilter::Info)
                .build(),
        )
        .plugin(tauri_plugin_opener::init())
        // shell 插件：打包模式下经 app.shell().sidecar() 解析并拉起 PyInstaller 冻结的
        // sidecar 二进制（externalBin 的跨平台落点只有它知道）。Rust 侧直接调用不经
        // ACL 校验（scope 只拦 webview 发起的 IPC 命令层），故 capabilities 无需为它
        // 配 shell:allow-spawn——配了反而把带任意参数的 spawn 暴露给前端可调。
        .plugin(tauri_plugin_shell::init())
        .manage(mgr.clone())
        .setup(move |app| {
            sidecar::run_supervisor(app.handle().clone(), mgr.clone());
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            get_sidecar_info,
            restart_sidecar,
            get_sidecar_failure,
            export_diagnostics,
            reveal_sidecar_logs,
            reveal_in_folder,
            confirm_exit,
            check_latest_version,
            open_download_page
        ])
        .build(tauri::generate_context!())
        .expect("error while building tauri application");

    app.run(|app_handle, event| match event {
        // 退出拦截（2026-09-12）：cmd+Q/应用菜单退出在用户确认前拦下，转发给前端
        // ExitGuard 弪窗（查活 run 后确认）；确认后 confirm_exit 置 allow_exit 再退出。
        // 窗口关闭（X 钮）不走这里——由前端 onCloseRequested 拦截、确认后 destroy()；
        // destroy 触发的 ExitRequested 到达时窗口已从管理表移除（wry 先清表再发事件），
        // 拦下也无人能应答 confirm_exit——必须在 prevent 之前查窗口，拿不到就放行，
        // 否则 app 变无窗口僵尸进程、Exit 不触发 sidecar 也不停。
        RunEvent::ExitRequested { api, .. } => {
            let allow = app_handle
                .try_state::<Arc<SidecarManager>>()
                .map(|s| s.allow_exit.load(Ordering::SeqCst))
                .unwrap_or(true);
            if allow {
                return;
            }
            let Some(w) = app_handle.get_webview_window("main") else {
                return;
            };
            api.prevent_exit();
            let _ = w.emit("app:exit-requested", ());
        }
        RunEvent::Exit => {
            // 退出时杀 sidecar 进程树（state 同样是 Arc 包装，需按同一类型查询）
            if let Some(state) = app_handle.try_state::<Arc<SidecarManager>>() {
                sidecar::shutdown(state.inner());
            }
        }
        _ => {}
    });
}
