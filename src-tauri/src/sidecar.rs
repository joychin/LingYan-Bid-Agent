//! sidecar 生命周期管理（Tauri 壳唯一职责之一，零业务逻辑）。
//!
//! 职责：
//!   1. 选空闲端口（127.0.0.1:0 → drop 取端口）→ 生成随机 token → spawn python sidecar
//!   2. 轮询 /api/healthz（1s×30）→ 失败 kill 后指数退避重启（上限 3 次）
//!   3. 退出时杀整个进程树
//!   4. 提供 commands：get_sidecar_info / reveal_in_folder
//!      （模型配置与凭证 2026-08-29 起真值在 sidecar 的 app.db，经 HTTP 读写——
//!      钥匙串/MODEL_KEYS 注入/设置类 command 已全部移除）

use std::net::TcpListener;
use std::path::PathBuf;
use std::process::{Child, Command, ExitStatus, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

use serde::Serialize;
use tauri::{AppHandle, Emitter};
use uuid::Uuid;

const HEALTHZ_ATTEMPTS: u32 = 30;
const HEALTHZ_INTERVAL: Duration = Duration::from_secs(1);
const MAX_RESTARTS: u32 = 3;
/// 稳定窗口：探活成功后存活满该时长才把失败计数清零（Docker 10s 成功窗口的加强版），
/// 防「每次都能起来、活 N 秒必崩」型故障陷入 起-崩-起 永久循环。
const STABLE_WINDOW: Duration = Duration::from_secs(30);
/// sidecar 启动期 stderr 留档（每次 spawn 截断重写）：捕捉 Python 日志系统
/// 初始化之前的启动早期错误（杀软拦截、二进制损坏等第一现场）。
pub(crate) fn boot_log_path() -> PathBuf {
    sidecar_dir().join("data/logs/sidecar-boot.log")
}

/// 最近一次失败的可透出信息（kind 供前端映射文案，detail 已是中文人话）。
#[derive(Clone, Serialize, Debug)]
pub struct FailureInfo {
    /// spawn_failed | boot_timeout | crashed | exited
    pub kind: String,
    pub detail: String,
}

#[derive(Clone, Serialize)]
pub struct SidecarInfo {
    pub port: u16,
    pub token: String,
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
    pub state: Mutex<SidecarState>,
    pub child: Mutex<Option<Child>>,
    pub restart_requested: AtomicBool,
    pub fail_count: Mutex<u32>,
    pub stopping: AtomicBool,
    /// 最近一次失败原因（红态横幅透出；探活成功时清除）。
    pub last_failure: Mutex<Option<FailureInfo>>,
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

/// stderr 重定向到启动留档文件（每次 spawn 截断重写）；文件创建失败回退 null，
/// 不能让留档失败阻断拉起。
fn boot_stderr_stdio() -> Stdio {
    let path = boot_log_path();
    if let Some(parent) = path.parent() {
        let _ = std::fs::create_dir_all(parent);
    }
    match std::fs::File::create(&path) {
        Ok(f) => Stdio::from(f),
        Err(e) => {
            log::warn!("sidecar 启动留档文件创建失败（回退丢弃 stderr）: {e}");
            Stdio::null()
        }
    }
}

/// 把进程退出状态分类为人话（kind 供前端分组，detail 直接展示）。
/// 纯函数，便于单测。
fn classify_exit_status(status: &ExitStatus) -> FailureInfo {
    #[cfg(unix)]
    {
        use std::os::unix::process::ExitStatusExt;
        if let Some(sig) = status.signal() {
            let detail = match sig {
                libc::SIGKILL => "进程被强制终止（可能被安全软件拦截或系统内存不足）".to_string(),
                libc::SIGSEGV => "程序崩溃（段错误）".to_string(),
                other => format!("进程因信号 {other} 终止"),
            };
            return FailureInfo { kind: "crashed".into(), detail };
        }
    }
    match status.code() {
        Some(0) => FailureInfo { kind: "exited".into(), detail: "进程自行退出".into() },
        Some(code) => {
            FailureInfo { kind: "exited".into(), detail: format!("进程异常退出（退出码 {code}）") }
        }
        None => FailureInfo { kind: "exited".into(), detail: "进程退出（退出状态未知）".into() },
    }
}

fn set_failure(mgr: &SidecarManager, kind: &str, detail: impl Into<String>) {
    *mgr.last_failure.lock().unwrap() =
        Some(FailureInfo { kind: kind.into(), detail: detail.into() });
}

/// 拉起 sidecar：配置与凭证都在 sidecar 的 app.db（经 HTTP 读写），env 只注入
/// 进程管理 plumbing（token + healthz nonce）。
fn spawn_sidecar(nonce: &str) -> std::io::Result<(Child, u16, String)> {
    let port = pick_free_port();
    let token = Uuid::new_v4().to_string();
    let python = sidecar_python();
    let workdir = sidecar_dir();

    let mut cmd = Command::new(&python);
    cmd.args(["-m", "uvicorn", "app.main:app", "--port", &port.to_string()])
        .current_dir(&workdir)
        .env("SIDECAR_TOKEN", &token)
        .env("TENDER_HEALTHZ_NONCE", nonce)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(boot_stderr_stdio());

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
            let nonce = Uuid::new_v4().to_string();
            match spawn_sidecar(&nonce) {
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
                        *mgr.last_failure.lock().unwrap() = None;
                        // 消费探活窗口内积压的手动重启请求：点击落在退避/拉起阶段时
                        // 存活监控不会消费它，若残留会把刚拉起的健康进程误杀重拉
                        mgr.restart_requested.store(false, Ordering::SeqCst);
                        *mgr.state.lock().unwrap() = SidecarState::Running;
                        emit(&app, SidecarState::Running, "ok");
                        log::info!("sidecar running on 127.0.0.1:{port}");
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
                        set_failure(
                            &mgr,
                            "boot_timeout",
                            format!("服务启动超时（{HEALTHZ_ATTEMPTS} 秒内未就绪）"),
                        );
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
                    let failed = {
                        let mut f = mgr.fail_count.lock().unwrap();
                        *f += 1;
                        *f
                    };
                    *mgr.state.lock().unwrap() = SidecarState::Failed;
                    set_failure(&mgr, "spawn_failed", format!("拉起服务进程失败: {e}"));
                    emit(&app, SidecarState::Failed, &format!("spawn failed: {e}"));
                    log::error!("sidecar spawn failed: {e} (attempt {failed})");

                    if failed >= MAX_RESTARTS {
                        emit(&app, SidecarState::Failed, "已达重启上限，停止自动重启");
                        log::error!(
                            "sidecar spawn 连续失败达上限（{failed} 次），停止自动重启，等待手动触发"
                        );
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

            // 存活监控（healthy_since 探活成功即置位，供稳定窗口判定）
            let healthy_since = Instant::now();
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

                // Some((描述, 退出状态))=已退出（wait 失败视为已退出但状态未知），None=仍在运行
                let exited: Option<(String, Option<ExitStatus>)> = {
                    let mut c = mgr.child.lock().unwrap();
                    match c.as_mut().map(|c| c.try_wait()) {
                        Some(Ok(Some(status))) => {
                            *c = None;
                            Some((status.to_string(), Some(status)))
                        }
                        Some(Ok(None)) => None,
                        _ => Some(("wait 失败".into(), None)),
                    }
                };

                if let Some((how, status)) = exited {
                    if mgr.stopping.load(Ordering::SeqCst) {
                        break 'outer;
                    }
                    let failed = {
                        let mut f = mgr.fail_count.lock().unwrap();
                        *f += 1;
                        *f
                    };
                    *mgr.state.lock().unwrap() = SidecarState::Failed;
                    let failure = status
                        .as_ref()
                        .map(classify_exit_status)
                        .unwrap_or(FailureInfo {
                            kind: "exited".into(),
                            detail: "进程退出（退出状态未知）".into(),
                        });
                    set_failure(&mgr, &failure.kind, failure.detail.clone());
                    emit(&app, SidecarState::Failed, &failure.detail);
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

                // 稳定窗口：本轮启动存活满 STABLE_WINDOW 才清零失败计数，
                // 防「每次都能起来、活 N 秒必崩」型故障陷入起-崩永久循环
                let f = *mgr.fail_count.lock().unwrap();
                if f > 0 && healthy_since.elapsed() >= STABLE_WINDOW {
                    *mgr.fail_count.lock().unwrap() = 0;
                    log::info!("sidecar 已稳定运行 {}s，清零失败计数", STABLE_WINDOW.as_secs());
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

#[cfg(test)]
mod tests {
    use super::*;

    #[cfg(unix)]
    #[test]
    fn classify_kill_signal_as_crashed() {
        use std::os::unix::process::ExitStatusExt;
        // wait status 编码：信号态直接是信号号，退出码才是 code << 8
        let status = ExitStatus::from_raw(libc::SIGKILL);
        let f = classify_exit_status(&status);
        assert_eq!(f.kind, "crashed");
        assert!(f.detail.contains("强制终止"));
    }

    #[cfg(unix)]
    #[test]
    fn classify_segv_as_crashed() {
        use std::os::unix::process::ExitStatusExt;
        let status = ExitStatus::from_raw(libc::SIGSEGV);
        let f = classify_exit_status(&status);
        assert_eq!(f.kind, "crashed");
        assert!(f.detail.contains("崩溃"));
    }

    #[cfg(unix)]
    #[test]
    fn classify_nonzero_code_as_exited() {
        use std::os::unix::process::ExitStatusExt;
        let status = ExitStatus::from_raw(42 << 8);
        let f = classify_exit_status(&status);
        assert_eq!(f.kind, "exited");
        assert!(f.detail.contains("42"));
    }

    #[cfg(unix)]
    #[test]
    fn classify_zero_code_as_self_exit() {
        use std::os::unix::process::ExitStatusExt;
        let status = ExitStatus::from_raw(0);
        let f = classify_exit_status(&status);
        assert_eq!(f.kind, "exited");
        assert!(f.detail.contains("自行退出"));
    }
}
