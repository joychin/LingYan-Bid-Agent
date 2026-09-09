mod sidecar;

use std::path::{Path, PathBuf};
use std::sync::atomic::Ordering;
use std::sync::Arc;
use std::time::{Duration, Instant};

use tauri::{AppHandle, Manager, RunEvent, State};
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
    report.push_str("==== Tender Agent 诊断报告 ====\n");
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
        .map_err(|e| format!("无法解析数据目录: {e}"))?;
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
        // flags 去掉 VISIBLE：插件默认含它，restore 会把 visible:false 的主窗提前
        // show 出来（与 splash 并存，用户实测「同时展示很怪异」）——显示时机只归
        // sidecar.rs 的 reveal_main_from_splash。DECORATIONS/FULLSCREEN 同理不跨启动恢复。
        .plugin(
            tauri_plugin_window_state::Builder::default()
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
            reveal_in_folder
        ])
        .build(tauri::generate_context!())
        .expect("error while building tauri application");

    app.run(|app_handle, event| {
        if let RunEvent::Exit = event {
            // 退出时杀 sidecar 进程树（state 同样是 Arc 包装，需按同一类型查询）
            if let Some(state) = app_handle.try_state::<Arc<SidecarManager>>() {
                sidecar::shutdown(state.inner());
            }
        }
    });
}
