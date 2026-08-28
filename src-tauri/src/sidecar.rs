//! sidecar 生命周期管理（Tauri 壳唯一职责之一，零业务逻辑）。
//!
//! 职责：
//!   1. 选空闲端口（127.0.0.1:0 → drop 取端口）→ 生成随机 token → spawn python sidecar
//!   2. 轮询 /api/healthz（1s×30）→ 失败 kill 后指数退避重启（上限 3 次）
//!   3. 退出时杀整个进程树
//!   4. 提供 commands：get_sidecar_info / get_model_settings / set_model_settings /
//!      get_api_key_has_value / set_baidu_ocr_keys —— 按角色组织，共用同一 settings.json 真值。

use std::net::TcpListener;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Duration;

use serde::Serialize;
use tauri::{AppHandle, Emitter};
use uuid::Uuid;

pub const KEYRING_SERVICE: &str = "tender-agent";
pub const KEYRING_ACCOUNT_LLM: &str = "llm-api-key";
pub const KEYRING_ACCOUNT_VLM: &str = "vlm-api-key";
pub const KEYRING_ACCOUNT_BAIDU_AK: &str = "baidu-ocr-api-key";
pub const KEYRING_ACCOUNT_BAIDU_SK: &str = "baidu-ocr-secret-key";
const DEFAULT_BASE_URL: &str = "https://api.deepseek.com/v1";
const DEFAULT_MODEL: &str = "deepseek-v4-flash";

const HEALTHZ_ATTEMPTS: u32 = 30;
const HEALTHZ_INTERVAL: Duration = Duration::from_secs(1);
const MAX_RESTARTS: u32 = 3;

#[derive(Clone, Serialize)]
pub struct SidecarInfo {
    pub port: u16,
    pub token: String,
}

/// 单角色模型配置（llm 或 vlm）。vlm 未配置时为全空串。
/// image_support 仅 llm 块有值：透传 settings.json 的该字段（Python 侧写入），
/// 不透传会在保存 key 重写文件时把它抹掉。
#[derive(Clone, Default, Serialize)]
pub struct RoleSettings {
    pub base_url: String,
    pub model: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub image_support: Option<bool>,
}

/// 双角色模型设置：llm 恒有值（spawn 必需），vlm 可空（未配置=知识库图片/扫描件走降级链）。
#[derive(Clone, Serialize)]
pub struct ModelSettings {
    pub llm: RoleSettings,
    pub vlm: RoleSettings,
}

#[derive(Clone, Copy, PartialEq, Serialize, Debug, Default)]
pub enum SidecarState {
    Starting,
    Running,
    #[default]
    Failed,
}

/// 跨线程共享的 sidecar 状态（supervisor 线程 + commands + 退出钩子）。
#[derive(Default)]
pub struct SidecarManager {
    pub info: Mutex<Option<SidecarInfo>>,
    pub settings: Mutex<ModelSettings>,
    pub state: Mutex<SidecarState>,
    pub child: Mutex<Option<Child>>,
    pub restart_requested: AtomicBool,
    pub fail_count: Mutex<u32>,
    pub stopping: AtomicBool,
}

impl Default for ModelSettings {
    fn default() -> Self {
        Self {
            llm: RoleSettings {
                base_url: DEFAULT_BASE_URL.to_string(),
                model: DEFAULT_MODEL.to_string(),
                image_support: None,
            },
            vlm: RoleSettings::default(),
        }
    }
}

fn sidecar_dir() -> PathBuf {
    if let Ok(p) = std::env::var("TENDER_SIDECAR_DIR") {
        let pb = PathBuf::from(&p);
        if pb.join("pyproject.toml").exists() {
            return pb;
        }
    }
    for cand in ["./sidecar", "../sidecar"] {
        let pb = PathBuf::from(cand);
        if pb.join("pyproject.toml").exists() {
            return pb;
        }
    }
    PathBuf::from("../sidecar")
}

pub(crate) fn data_dir() -> PathBuf {
    sidecar_dir().join("data")
}

/// 产物工作区目录（与 sidecar app/config.py 的 workspace_dir 一致）：`<sidecar>/data/workspace`。
/// Tauri 不设 DATA_DIR，故与 Python 侧默认解析一致。仅用于 reveal_in_folder 的路径前缀校验。
pub(crate) fn workspace_dir() -> PathBuf {
    sidecar_dir().join("data/workspace")
}

fn sidecar_python() -> PathBuf {
    #[cfg(windows)]
    {
        sidecar_dir().join(".venv/Scripts/python.exe")
    }
    #[cfg(not(windows))]
    {
        sidecar_dir().join(".venv/bin/python")
    }
}

fn pick_free_port() -> u16 {
    let listener = TcpListener::bind("127.0.0.1:0").expect("bind 127.0.0.1:0 failed");
    listener.local_addr().expect("local_addr").port()
}

/// 与 sidecar app/config.py 共享的配置真值文件（base_url/model 跨重启持久）。
/// 注意：Tauri 不设 DATA_DIR，故两侧都落在 <sidecar>/data/settings.json。
fn settings_file_path() -> PathBuf {
    sidecar_dir().join("data/settings.json")
}

/// 读 settings.json（双角色嵌套 `{llm:{base_url,model}, vlm:{...}}`；
/// 兼容旧扁平 `{base_url,model}` —— 顶层键视作 llm 块，首次写入时自然迁移为新格式）。
/// llm 缺失/损坏返回 None（调用方回退默认）；vlm 缺失返回空（未配置）。
pub fn read_settings_file() -> Option<ModelSettings> {
    let raw = std::fs::read_to_string(settings_file_path()).ok()?;
    let v: serde_json::Value = serde_json::from_str(&raw).ok()?;
    let llm = v
        .get("llm")
        .and_then(read_role)
        .or_else(|| read_role(&v)) // 旧扁平格式回退
        ?;
    let vlm = v.get("vlm").and_then(read_role).unwrap_or_default();
    Some(ModelSettings { llm, vlm })
}

fn read_role(v: &serde_json::Value) -> Option<RoleSettings> {
    let base = v.get("base_url")?.as_str()?;
    let model = v.get("model")?.as_str()?;
    if base.trim().is_empty() || model.trim().is_empty() {
        return None;
    }
    Some(RoleSettings {
        base_url: base.trim().to_string(),
        model: model.trim().to_string(),
        image_support: v.get("image_support").and_then(|b| b.as_bool()),
    })
}

/// 写 settings.json（set_model_settings 持久化，使 HTTP PUT 与 IPC 走同一真值）。
/// vlm 未配置（base_url 为空）时不写 vlm 块，读侧语义一致。
pub fn write_settings_file(s: &ModelSettings) -> Result<(), String> {
    let path = settings_file_path();
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    let mut llm = serde_json::json!({ "base_url": s.llm.base_url, "model": s.llm.model });
    if let Some(img) = s.llm.image_support {
        llm["image_support"] = serde_json::json!(img);
    }
    let mut json = serde_json::json!({ "llm": llm });
    if !s.vlm.base_url.is_empty() {
        json["vlm"] = serde_json::json!({ "base_url": s.vlm.base_url, "model": s.vlm.model });
    }
    std::fs::write(&path, serde_json::to_string_pretty(&json).map_err(|e| e.to_string())?)
        .map_err(|e| e.to_string())
}

/// 钥匙串读写走 macOS `security` CLI（写 login 钥匙串，`security find-generic-password -s tender-agent`
/// 必然可见）。注意：keyring crate 在此 macOS 上默认写入 Data Protection 钥匙串，`security` CLI 看不到，
/// 故改用 CLI 子进程以满足 PRD 验收（service=tender-agent，account 按角色 llm-api-key/vlm-api-key）。
pub fn keychain_set(account: &str, key: &str) -> Result<(), String> {
    let out = Command::new("security")
        .args(["add-generic-password", "-U", "-s", KEYRING_SERVICE, "-a", account, "-w", key])
        .output()
        .map_err(|e| e.to_string())?;
    if out.status.success() {
        Ok(())
    } else {
        Err(String::from_utf8_lossy(&out.stderr).trim().to_string())
    }
}

pub fn keychain_get(account: &str) -> Result<String, String> {
    let out = Command::new("security")
        .args(["find-generic-password", "-s", KEYRING_SERVICE, "-a", account, "-w"])
        .output()
        .map_err(|e| e.to_string())?;
    if out.status.success() {
        Ok(String::from_utf8_lossy(&out.stdout).trim_end_matches('\n').to_string())
    } else {
        Err(String::from_utf8_lossy(&out.stderr).trim().to_string())
    }
}

pub fn keychain_has_value(account: &str) -> bool {
    keychain_get(account).map(|k| !k.is_empty()).unwrap_or(false)
}

fn resolve_api_key(account: &str, env_var: &str) -> Option<String> {
    // 优先钥匙串；开发期回退环境变量（sidecar/.env 由 tauri dev 的 shell 继承不到，故再兜底）
    if let Ok(k) = keychain_get(account) {
        if !k.is_empty() {
            return Some(k);
        }
    }
    std::env::var(env_var).ok().filter(|k| !k.is_empty())
}

/// vlm 为 None（未配置）时不注入任何 VLM_* env，让 sidecar 回退 settings.json 的 vlm 块；
/// 注入空串会覆盖 settings.json 的配置，故必须「无值不注入」。baidu（OCR AK/SK）同理。
fn spawn_sidecar(
    api_key: Option<String>,
    base_url: &str,
    model: &str,
    vlm: Option<(String, String, String)>, // (api_key, base_url, model)
    baidu: Option<(String, String)>,       // (api_key, secret_key)
    nonce: &str,
) -> std::io::Result<(Child, u16, String)> {
    let port = pick_free_port();
    let token = Uuid::new_v4().to_string();
    let python = sidecar_python();
    let workdir = sidecar_dir();

    let mut cmd = Command::new(&python);
    cmd.args(["-m", "uvicorn", "app.main:app", "--port", &port.to_string()])
        .current_dir(&workdir)
        .env("SIDECAR_TOKEN", &token)
        .env("LLM_API_KEY", api_key.unwrap_or_default())
        .env("LLM_BASE_URL", base_url)
        .env("LLM_MODEL", model)
        .env("TENDER_HEALTHZ_NONCE", nonce)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    if let Some((vkey, vbase, vmodel)) = vlm {
        cmd.env("VLM_API_KEY", vkey).env("VLM_BASE_URL", vbase).env("VLM_MODEL", vmodel);
    }
    if let Some((ak, sk)) = baidu {
        cmd.env("BAIDU_OCR_API_KEY", ak).env("BAIDU_OCR_SECRET_KEY", sk);
    }

    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt;
        cmd.process_group(0); // 整进程组，退出时一键杀
    }

    let child = cmd.spawn()?;
    Ok((child, port, token))
}

#[cfg(unix)]
fn kill_process_tree(child: &Child) {
    let pid = child.id() as i32;
    // spawn 时 process_group(0)：进程组 id = 主进程 pid
    unsafe {
        libc::kill(-pid, libc::SIGKILL);
    }
}

#[cfg(windows)]
fn kill_process_tree(child: &Child) {
    let _ = Command::new("taskkill")
        .args(["/T", "/F", "/PID", &child.id().to_string()])
        .status();
}

fn wait_healthy(port: u16, nonce: &str) -> bool {
    let client = reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(1))
        .build()
        .expect("reqwest client");
    for _ in 0..HEALTHZ_ATTEMPTS {
        match client.get(format!("http://127.0.0.1:{port}/api/healthz")).send() {
            // 校验 nonce 与本次 spawn 一致，避免把端口被占时其他本地服务误判为 sidecar
            Ok(resp) if resp.status().is_success() => {
                let ok = resp
                    .json::<serde_json::Value>()
                    .ok()
                    .and_then(|v| v.get("nonce").and_then(|n| n.as_str()).map(|n| n == nonce))
                    .unwrap_or(false);
                if ok {
                    return true;
                }
            }
            _ => {}
        }
        thread::sleep(HEALTHZ_INTERVAL);
    }
    false
}

fn emit(app: &AppHandle, state: SidecarState, detail: &str) {
    let _ = app.emit(
        "sidecar-status",
        serde_json::json!({ "state": format!("{:?}", state).to_lowercase(), "detail": detail }),
    );
}

/// 杀进程树并 wait 回收；同时清空 child/info（供 healthz 失败、restart、退出共用）。
fn kill_and_reap(mgr: &SidecarManager) {
    let mut guard = mgr.child.lock().unwrap();
    if let Some(mut child) = guard.take() {
        kill_process_tree(&child);
        let _ = child.wait();
    }
    drop(guard);
    *mgr.info.lock().unwrap() = None;
}

/// 后台 supervisor：拉起 → 探活 → 存活监控 → 崩溃/被要求重启时按指数退避重启。
/// 应用退出（stopping 置位）后不再拉起，避免残留孤儿 sidecar。
pub fn run_supervisor(app: AppHandle, mgr: Arc<SidecarManager>) {
    thread::spawn(move || {
        let mut restart_waits = 0u32;
        'outer: loop {
            if mgr.stopping.load(Ordering::SeqCst) {
                break;
            }
            // 取当前 settings：优先 settings.json（跨重启持久），否则 mgr.settings 默认
            let ms = read_settings_file().unwrap_or_else(|| mgr.settings.lock().unwrap().clone());
            let vlm = if ms.vlm.base_url.is_empty() {
                None
            } else {
                Some((
                    resolve_api_key(KEYRING_ACCOUNT_VLM, "VLM_API_KEY").unwrap_or_default(),
                    ms.vlm.base_url.clone(),
                    ms.vlm.model.clone(),
                ))
            };

            let nonce = Uuid::new_v4().to_string();
            // 百度 OCR AK/SK：两把钥匙串 account 齐备才注入（单边有值视为未配置，与 sidecar 判定一致）
            let baidu = match (
                resolve_api_key(KEYRING_ACCOUNT_BAIDU_AK, "BAIDU_OCR_API_KEY"),
                resolve_api_key(KEYRING_ACCOUNT_BAIDU_SK, "BAIDU_OCR_SECRET_KEY"),
            ) {
                (Some(ak), Some(sk)) => Some((ak, sk)),
                _ => None,
            };
            match spawn_sidecar(
                resolve_api_key(KEYRING_ACCOUNT_LLM, "LLM_API_KEY"),
                &ms.llm.base_url,
                &ms.llm.model,
                vlm,
                baidu,
                &nonce,
            ) {
                Ok((child, port, token)) => {
                    log::info!("sidecar spawned: pid={} port={}", child.id(), port);
                    *mgr.info.lock().unwrap() = Some(SidecarInfo { port, token: token.clone() });
                    *mgr.child.lock().unwrap() = Some(child);
                    *mgr.state.lock().unwrap() = SidecarState::Starting;
                    emit(&app, SidecarState::Starting, &format!("port {port}"));

                    // 探活（healthz 成功前端口即知，前端可先拿 info）
                    if wait_healthy(port, &nonce) {
                        restart_waits = 0;
                        *mgr.fail_count.lock().unwrap() = 0;
                        *mgr.state.lock().unwrap() = SidecarState::Running;
                        emit(&app, SidecarState::Running, "ok");
                        log::info!("sidecar running on 127.0.0.1:{port} (base={} model={})", ms.llm.base_url, ms.llm.model);
                    } else {
                        if mgr.stopping.load(Ordering::SeqCst) {
                            kill_and_reap(&mgr);
                            break 'outer;
                        }
                        let failed = {
                            let mut f = mgr.fail_count.lock().unwrap();
                            *f += 1;
                            *f
                        };
                        *mgr.state.lock().unwrap() = SidecarState::Failed;
                        kill_and_reap(&mgr);
                        emit(&app, SidecarState::Failed, "healthz timeout");
                        log::warn!("sidecar healthz failed (attempt {failed})");

                        if failed >= MAX_RESTARTS {
                            emit(&app, SidecarState::Failed, "已达重启上限，停止自动重启");
                            log::error!("sidecar healthz 连续失败达上限（{failed} 次），停止自动重启，等待手动触发");
                            // 等待手动触发（set_model_settings 会置 restart_requested）
                            while !mgr.restart_requested.swap(false, Ordering::SeqCst) {
                                if mgr.stopping.load(Ordering::SeqCst) {
                                    break 'outer;
                                }
                                thread::sleep(Duration::from_millis(500));
                            }
                            restart_waits = 0;
                            continue;
                        }
                        restart_waits += 1;
                        let wait = Duration::from_millis(1000 * 2u64.pow(restart_waits.min(3)));
                        log::warn!("{wait:?} 后重试拉起 sidecar（第 {failed} 次失败）");
                        thread::sleep(wait);
                        continue;
                    }
                }
                Err(e) => {
                    if mgr.stopping.load(Ordering::SeqCst) {
                        break 'outer;
                    }
                    *mgr.state.lock().unwrap() = SidecarState::Failed;
                    emit(&app, SidecarState::Failed, &format!("spawn failed: {e}"));
                    log::error!("sidecar spawn failed: {e}");
                    thread::sleep(Duration::from_secs(2));
                    continue;
                }
            }

            // 存活监控
            loop {
                if mgr.stopping.load(Ordering::SeqCst) {
                    kill_and_reap(&mgr);
                    break 'outer;
                }
                if mgr.restart_requested.swap(false, Ordering::SeqCst) {
                    kill_and_reap(&mgr);
                    *mgr.state.lock().unwrap() = SidecarState::Failed;
                    emit(&app, SidecarState::Failed, "restart requested");
                    restart_waits = 0;
                    break; // 外层重新拉起
                }

                // Some(how)=已退出（how 为退出状态描述；wait 失败视为已退出但状态未知），None=仍在运行
                let exited: Option<String> = {
                    let mut c = mgr.child.lock().unwrap();
                    match c.as_mut().map(|c| c.try_wait()) {
                        Some(Ok(Some(status))) => {
                            *c = None;
                            Some(status.to_string())
                        }
                        Some(Ok(None)) => None,
                        _ => Some("wait 失败".into()),
                    }
                };

                if let Some(how) = exited {
                    if mgr.stopping.load(Ordering::SeqCst) {
                        break 'outer;
                    }
                    let failed = {
                        let mut f = mgr.fail_count.lock().unwrap();
                        *f += 1;
                        *f
                    };
                    *mgr.state.lock().unwrap() = SidecarState::Failed;
                    emit(&app, SidecarState::Failed, "process exited unexpectedly");
                    // 退出状态是崩溃诊断的第一现场（信号退出在 unix 下由 code() 反映）
                    log::warn!("sidecar exited unexpectedly: {how} (attempt {failed})");

                    if failed >= MAX_RESTARTS {
                        emit(&app, SidecarState::Failed, "已达重启上限，停止自动重启");
                        log::error!("sidecar 连续意外退出达上限（{failed} 次），停止自动重启，等待手动触发");
                        while !mgr.restart_requested.swap(false, Ordering::SeqCst) {
                            if mgr.stopping.load(Ordering::SeqCst) {
                                break 'outer;
                            }
                            thread::sleep(Duration::from_millis(500));
                        }
                        restart_waits = 0;
                        continue; // 外层重新拉起
                    }
                    restart_waits += 1;
                    let wait = Duration::from_millis(1000 * 2u64.pow(restart_waits.min(3)));
                    log::warn!("{wait:?} 后重试拉起 sidecar（第 {failed} 次失败）");
                    thread::sleep(wait);
                    break; // 外层重新拉起
                }

                thread::sleep(Duration::from_millis(500));
            }
        }
    });
}

/// 停止并清理 sidecar（应用退出时调用）。置 stopping 后杀进程树并回收，supervisor 随后退出。
pub fn shutdown(mgr: &SidecarManager) {
    log::info!("应用退出：停止 sidecar 进程树");
    mgr.stopping.store(true, Ordering::SeqCst);
    kill_and_reap(mgr);
    *mgr.state.lock().unwrap() = SidecarState::Failed;
}
