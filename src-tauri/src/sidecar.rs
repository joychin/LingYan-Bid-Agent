//! sidecar 生命周期管理（Tauri 壳唯一职责之一，零业务逻辑）。
//!
//! 职责：
//!   1. 选空闲端口（127.0.0.1:0 → drop 取端口）→ 生成随机 token → spawn sidecar
//!   2. 轮询 /api/healthz（nonce 校验）→ 失败 kill 后指数退避重启（上限 3 次）
//!   3. 退出时杀整个进程树
//!   4. 提供 commands：get_sidecar_info / reveal_in_folder
//!      （模型配置与凭证 2026-08-29 起真值在 sidecar 的 app.db，经 HTTP 读写）
//!
//! 双启动模式（supervisor 启动时探测一次）：
//!   - Dev：仓库 checkout（`sidecar/` 下有 pyproject.toml）→ spawn `.venv/bin/python
//!     -m uvicorn`，数据落 `<sidecar>/data`。`npm run dev` 行为与历史完全一致。
//!   - Bundled：打包产物 → tauri shell 插件拉起 PyInstaller 冻结的 externalBin
//!     （`tender-agent-sidecar`，one-file），数据落系统 app_data_dir——经 `DATA_DIR`
//!     env 注入 Python，`config.py` 的 env 优先逻辑零改动生效；one-file 下 Python 的
//!     `__file__` 在临时解压目录，不注入则数据全部落临时目录。
//!
//! 杀进程（打包模式 unix）：PyInstaller one-file 是 bootloader + 真正 python 子进程的
//! 进程树，只 SIGKILL bootloader 会留孤儿继续占端口（tauri#11686 同款）。顺序 =
//! SIGTERM（bootloader 转发）→ 轮询终态 ≤3s → 按端口清扫孤儿（端口由本进程分配，
//! 无歧义锚点）→ SIGKILL 兜底。Windows 用 taskkill /T /F 沿进程树整棵带走。

use std::net::TcpListener;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, ExitStatus, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex, OnceLock};
use std::thread;
use std::time::{Duration, Instant};

use serde::Serialize;
use tauri::{AppHandle, Emitter, Manager};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;
use uuid::Uuid;

/// dev 模式探活窗口（.venv python 秒级启动）
const HEALTHZ_ATTEMPTS_DEV: u32 = 30;
/// 打包模式探活窗口：one-file 首启要解压全部依赖到临时目录，冷缓存可到十几秒
const HEALTHZ_ATTEMPTS_BUNDLED: u32 = 60;
const HEALTHZ_INTERVAL: Duration = Duration::from_secs(1);
const MAX_RESTARTS: u32 = 3;
/// 稳定窗口：探活成功后存活满该时长才把失败计数清零（Docker 10s 成功窗口的加强版），
/// 防「每次都能起来、活 N 秒必崩」型故障陷入 起-崩-起 永久循环。
const STABLE_WINDOW: Duration = Duration::from_secs(30);
/// externalBin 注册名（tauri.conf.json bundle.externalBin，构建产物带 triple 后缀）
const SIDECAR_BINARY: &str = "tender-agent-sidecar";

/// 更名前（Tender Agent 时期）的 bundle identifier：打包模式数据目录曾落
/// `…/com.tenderagent.app`（app_data_dir 按 identifier 派生），改名后需一次性搬迁，
/// 否则用户历史会话/任务/知识库全部「消失」。
const LEGACY_BUNDLE_ID: &str = "com.tenderagent.app";

/// 数据目录改名迁移：新目录为空（或不存在）且旧目录有内容才整目录 rename。
///
/// 幂等且保守——新目录已是非空（迁过了 / 新装已有数据）一律不动；任何失败只告警
/// 返回 false，绝不删任何一边（最坏结果=用户按日志手工搬）。旧路径由新路径的父目录
/// 推导（`app_data_dir` 各平台都在同一父下按 identifier 分目录），天然跨平台。
fn migrate_data_dir_if_legacy(new: &Path, legacy: &Path) -> bool {
    let newer = |p: &Path| {
        std::fs::read_dir(p)
            .map(|mut d| d.next().is_some())
            .unwrap_or(false)
    };
    if newer(new) {
        return false; // 已有数据（含迁移后的现场），不覆盖
    }
    if !newer(legacy) {
        return false; // 全新安装：旧目录不存在或为空
    }
    // 空的新目录（或占位目录）先移除：rename 的非空目标在 Windows 上会失败
    if new.exists() {
        if let Err(e) = std::fs::remove_dir(new) {
            log::warn!("数据目录迁移：清理空目录 {} 失败，跳过迁移: {e}", new.display());
            return false;
        }
    }
    match std::fs::rename(legacy, new) {
        Ok(()) => {
            log::info!("数据目录已迁移: {} → {}", legacy.display(), new.display());
            true
        }
        Err(e) => {
            log::warn!(
                "数据目录迁移失败（{} → {}）：{e}；请手工移动旧目录内容",
                legacy.display(),
                new.display()
            );
            false
        }
    }
}

/// 解析后的数据目录（supervisor 启动时按模式置位一次）：export_diagnostics /
/// reveal_sidecar_logs / reveal 前缀校验与 Python 侧注入的 DATA_DIR 保持同源。
static RESOLVED_DATA_DIR: OnceLock<PathBuf> = OnceLock::new();

pub(crate) fn data_dir() -> PathBuf {
    RESOLVED_DATA_DIR.get().cloned().unwrap_or_else(|| sidecar_dir().join("data"))
}

/// 启动留档（每次 spawn 截断重写）：捕捉 Python 日志系统初始化之前的启动早期错误
/// （杀软拦截、二进制损坏等第一现场）。
pub(crate) fn boot_log_path() -> PathBuf {
    data_dir().join("logs/sidecar-boot.log")
}

/// 产物工作区目录（与 sidecar app/config.py 的 workspace_dir 一致）：`<data>/workspace`。
/// 仅用于 reveal_in_folder 的路径前缀校验。
pub(crate) fn workspace_dir() -> PathBuf {
    data_dir().join("workspace")
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

/// 启动模式：探测到仓库 checkout（pyproject.toml）走 dev，否则打包产物。
enum LaunchMode {
    Dev {
        python: PathBuf,
        cwd: PathBuf,
        data_dir: PathBuf,
    },
    Bundled {
        data_dir: PathBuf,
    },
}

impl LaunchMode {
    fn data_dir(&self) -> &PathBuf {
        match self {
            LaunchMode::Dev { data_dir, .. } | LaunchMode::Bundled { data_dir } => data_dir,
        }
    }

    fn healthz_attempts(&self) -> u32 {
        match self {
            LaunchMode::Dev { .. } => HEALTHZ_ATTEMPTS_DEV,
            LaunchMode::Bundled { .. } => HEALTHZ_ATTEMPTS_BUNDLED,
        }
    }
}

fn resolve_launch_mode(app: &AppHandle) -> LaunchMode {
    let dir = sidecar_dir();
    if dir.join("pyproject.toml").exists() {
        return LaunchMode::Dev {
            python: sidecar_python(),
            cwd: dir.clone(),
            data_dir: dir.join("data"),
        };
    }
    let data_dir = app.path().app_data_dir().unwrap_or_else(|e| {
        log::error!("解析 app_data_dir 失败（回退 sidecar/data，仅兜底）: {e}");
        dir.join("data")
    });
    LaunchMode::Bundled { data_dir }
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

/// 插件句柄的退出状态（字段与 shell 插件 Terminated 事件一致）。
type TermStatus = (Option<i32>, Option<i32>);

/// sidecar 进程句柄双形态：dev=std 进程（try_wait 轮询 + 进程组杀）；
/// 打包=shell 插件句柄（无 wait/try_wait，退出状态由转发线程从 CommandEvent 通道置位）。
enum SidecarHandle {
    Std(Child),
    Plugin {
        child: CommandChild,
        terminated: Arc<Mutex<Option<TermStatus>>>,
    },
}

impl SidecarHandle {
    fn pid(&self) -> u32 {
        match self {
            SidecarHandle::Std(c) => c.id(),
            SidecarHandle::Plugin { child, .. } => child.pid(),
        }
    }

    /// Some((过程描述, 人话失败分类))=已退出；None=仍在运行。
    fn poll_exit(&mut self) -> Option<(String, FailureInfo)> {
        match self {
            SidecarHandle::Std(c) => match c.try_wait() {
                Ok(Some(status)) => {
                    let desc = status.to_string();
                    Some((desc, classify_exit_status(&status)))
                }
                Ok(None) => None,
                Err(_) => Some((
                    "wait 失败".into(),
                    FailureInfo { kind: "exited".into(), detail: "进程退出（退出状态未知）".into() },
                )),
            },
            SidecarHandle::Plugin { terminated, .. } => terminated.lock().unwrap().take().map(
                |(code, signal)| {
                    let desc = format!("code={code:?} signal={signal:?}");
                    (desc, classify_termination(code, signal))
                },
            ),
        }
    }

    /// 杀进程树。消费句柄（std 杀后 wait 回收；插件句柄 kill 收尾）。
    fn kill_tree(self, port: Option<u16>) {
        match self {
            SidecarHandle::Std(mut child) => {
                kill_process_tree(&child);
                let _ = child.wait();
            }
            SidecarHandle::Plugin { child, terminated } => {
                let pid = child.pid();
                kill_plugin_tree(pid, port, &terminated);
                let _ = child.kill();
            }
        }
    }
}

/// 跨线程共享的 sidecar 状态（supervisor 线程 + commands + 退出钩子）。
/// 仅 crate 内使用（lib.rs 的 commands 经 State<Arc<_>> 引用），句柄类型不外泄。
#[derive(Default)]
pub(crate) struct SidecarManager {
    pub info: Mutex<Option<SidecarInfo>>,
    pub state: Mutex<SidecarState>,
    /// 进程句柄（SidecarHandle 是模块私有类型，仅 supervisor 线程内操作）
    child: Mutex<Option<SidecarHandle>>,
    pub restart_requested: AtomicBool,
    pub fail_count: Mutex<u32>,
    pub stopping: AtomicBool,
    /// 最近一次失败原因（红态横幅透出；探活成功时清除）。
    pub last_failure: Mutex<Option<FailureInfo>>,
    /// 用户已在退出确认弹窗点「退出」（lib.rs 的 ExitRequested 拦截放行标志）：
    /// 运行中任务的退出拦截（2026-09-12）——cmd+Q/应用菜单退出先拦下转发前端确认，
    /// 确认后由 confirm_exit 命令置位本标志再真正退出。
    pub allow_exit: AtomicBool,
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
    let signal = {
        #[cfg(unix)]
        {
            use std::os::unix::process::ExitStatusExt;
            status.signal()
        }
        #[cfg(not(unix))]
        {
            None
        }
    };
    classify_termination(status.code(), signal)
}

/// 按退出码/信号分类（unix 信号态优先；wait status 编码：信号态直接是信号号，退出码才是 code << 8）。
/// 纯函数，便于单测。
fn classify_termination(code: Option<i32>, signal: Option<i32>) -> FailureInfo {
    #[cfg(unix)]
    {
        if let Some(sig) = signal {
            let detail = match sig {
                libc::SIGKILL => "进程被强制终止（可能被安全软件拦截或系统内存不足）".to_string(),
                libc::SIGSEGV => "程序崩溃（段错误）".to_string(),
                other => format!("进程因信号 {other} 终止"),
            };
            return FailureInfo { kind: "crashed".into(), detail };
        }
    }
    #[cfg(not(unix))]
    {
        let _ = signal;
    }
    match code {
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

/// 拉起 sidecar。配置与凭证都在 sidecar 的 app.db（经 HTTP 读写），env 只注入
/// 进程管理 plumbing（token + healthz nonce；打包模式加 DATA_DIR 数据目录重定向）。
fn spawn_sidecar(
    app: &AppHandle,
    mode: &LaunchMode,
    nonce: &str,
) -> std::io::Result<(SidecarHandle, u16, String)> {
    let port = pick_free_port();
    let token = Uuid::new_v4().to_string();

    let handle = match mode {
        LaunchMode::Dev { python, cwd, .. } => {
            let mut cmd = Command::new(python);
            cmd.args(["-m", "uvicorn", "app.main:app", "--port", &port.to_string()])
                .current_dir(cwd)
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

            SidecarHandle::Std(cmd.spawn()?)
        }
        LaunchMode::Bundled { data_dir } => {
            let (mut rx, child) = app
                .shell()
                .sidecar(SIDECAR_BINARY)
                .map_err(|e| std::io::Error::other(format!("解析 sidecar 可执行文件失败: {e}")))?
                .args(["--port", &port.to_string()])
                .env("SIDECAR_TOKEN", &token)
                .env("TENDER_HEALTHZ_NONCE", nonce)
                .env("DATA_DIR", data_dir)
                .spawn()
                .map_err(|e| std::io::Error::other(format!("拉起 sidecar 失败: {e}")))?;
            let terminated: Arc<Mutex<Option<TermStatus>>> = Arc::new(Mutex::new(None));
            spawn_plugin_forwarder(move || rx.blocking_recv(), terminated.clone());
            SidecarHandle::Plugin { child, terminated }
        }
    };

    Ok((handle, port, token))
}

/// 打包模式的 stdout/stderr 转发线程。CommandEvent 通道必须持续消费（缓冲满会堵死
/// 子进程）；stderr 行追加到启动留档（语义对齐 dev 的 Stdio 重定向）；Terminated
/// 置终态标志供 supervisor 存活监测与 kill 等待消费。
/// 取事件经闭包注入（rx 是插件 spawn 返回的 tokio mpsc Receiver，用 blocking_recv
/// 同步消费，类型由调用处推断避免引入 tokio 直接依赖）。
fn spawn_plugin_forwarder(
    mut next_event: impl FnMut() -> Option<CommandEvent> + Send + 'static,
    terminated: Arc<Mutex<Option<TermStatus>>>,
) {
    thread::spawn(move || {
        let mut log_file = std::fs::OpenOptions::new()
            .create(true)
            .write(true)
            .truncate(true)
            .open(boot_log_path())
            .ok();
        while let Some(event) = next_event() {
            match event {
                CommandEvent::Stderr(line) => {
                    if let Some(f) = log_file.as_mut() {
                        use std::io::Write;
                        // 插件读行已含行尾符，追加换行会每行多一空行
                        let _ = f.write_all(&line);
                    }
                }
                CommandEvent::Stdout(_) => {}
                CommandEvent::Error(e) => log::warn!("sidecar 事件流错误: {e}"),
                CommandEvent::Terminated(status) => {
                    *terminated.lock().unwrap() = Some((status.code, status.signal));
                    break;
                }
                _ => {}
            }
        }
    });
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
    taskkill_tree(child.id());
}

#[cfg(windows)]
fn taskkill_tree(pid: u32) {
    let _ = Command::new("taskkill").args(["/T", "/F", "/PID", &pid.to_string()]).status();
}

/// 打包模式杀进程（unix）：SIGTERM → 轮询终态 ≤3s → 按端口清扫孤儿 → SIGKILL 兜底。
/// 终态可见时 bootloader 已被插件的 wait 线程 reap：端口清扫仍要做（子进程可能
/// 未亡），但对 bootloader pid 的 SIGKILL 跳过——已 reap 的 pid 再发信号存在
/// pid 复用误杀窗口。
#[cfg(unix)]
fn kill_plugin_tree(pid: u32, port: Option<u16>, terminated: &Mutex<Option<TermStatus>>) {
    let pid = pid as i32;
    unsafe {
        libc::kill(pid, libc::SIGTERM);
    }
    for _ in 0..15 {
        if terminated.lock().unwrap().is_some() {
            if let Some(port) = port {
                sweep_port_orphans(port);
            }
            return;
        }
        thread::sleep(Duration::from_millis(200));
    }
    if let Some(port) = port {
        sweep_port_orphans(port);
    }
    unsafe {
        libc::kill(pid, libc::SIGKILL);
    }
}

#[cfg(windows)]
fn kill_plugin_tree(pid: u32, _port: Option<u16>, _terminated: &Mutex<Option<TermStatus>>) {
    // PyInstaller Windows 双进程：taskkill /T 沿进程树整棵带走，无需端口清扫
    taskkill_tree(pid);
}

/// 按端口清扫残留监听进程（`lsof -a -ti tcp:PORT -sTCP:LISTEN` → SIGKILL）。
/// 必须限定 LISTEN 状态：uvicorn 收 SIGTERM 后等活跃 SSE 连接 graceful shutdown，
/// 3s 窗口内退不干净，此刻前端网络进程仍持有到该端口的 ESTABLISHED 连接——
/// lsof 按「本端或对端」双向匹配会把它一并 SIGKILL。
#[cfg(unix)]
fn sweep_port_orphans(port: u16) {
    // -a 必须：lsof 多个 selection 默认 OR，缺了则 LISTEN 过滤不生效
    let Ok(out) = Command::new("lsof")
        .args(["-a", "-ti", &format!("tcp:{port}"), "-sTCP:LISTEN"])
        .output()
    else {
        return;
    };
    let self_pid = std::process::id() as i32;
    for pid in String::from_utf8_lossy(&out.stdout).split_whitespace() {
        let Ok(n) = pid.parse::<i32>() else { continue };
        if n == self_pid {
            continue;
        }
        log::warn!("sidecar 残留进程（端口 {port}）已强制清理: pid {n}");
        unsafe {
            libc::kill(n, libc::SIGKILL);
        }
    }
}

/// 启动期孤儿 sidecar 清扫（2026-09-12）：壳被强杀（kill -9/OOM/崩溃）时 Exit 钩子
/// 不执行，旧 sidecar 残留为孤儿（换端口绕开启动但无人清理）。sidecar 就绪时写
/// data/sidecar.pid（Python 侧 lifespan），此处据其核身份后清扫：pid 已死仅删陈旧
/// 文件；活着且命令行确认是我们的 sidecar（bundled 二进制名 / dev 的 uvicorn
/// app.main:app）才杀——防 pid 复用误杀无辜进程。纯 plumbing，用户不可见。
fn sweep_orphan_sidecar() {
    let pidfile = data_dir().join("sidecar.pid");
    let Ok(text) = std::fs::read_to_string(&pidfile) else { return };
    let parsed = serde_json::from_str::<serde_json::Value>(&text).ok();
    let pid = parsed
        .as_ref()
        .and_then(|v| v.get("pid"))
        .and_then(|p| p.as_u64())
        .unwrap_or(0) as u32;
    if pid == 0 {
        let _ = std::fs::remove_file(&pidfile);
        return;
    }
    if pid == std::process::id() {
        return;
    }
    match process_cmdline(pid) {
        Some(cmdline) if is_our_sidecar(&cmdline) => {
            log::info!("清扫孤儿 sidecar 进程 pid={pid}");
            kill_orphan_graceful(pid);
            let _ = std::fs::remove_file(&pidfile);
        }
        Some(_) => {
            // pid 已被复用给别的进程：不杀，仅清掉陈旧 pidfile（宁可漏扫不可误杀）
            log::warn!("sidecar.pid 指向 pid={pid}，命令行不符，跳过清扫（疑似 pid 复用）");
            let _ = std::fs::remove_file(&pidfile);
        }
        None => {
            let _ = std::fs::remove_file(&pidfile);
        }
    }
}

/// 进程命令行（身份核验用）。macOS 走 ps；Linux 读 /proc；Windows 的 tasklist 只给
/// 镜像名（bundled 二进制名仍可匹配，dev 模式的 python 参数看不到——dev Windows
/// 孤儿漏扫，接受：开发场景孤儿随手可清）。
#[cfg(target_os = "macos")]
fn process_cmdline(pid: u32) -> Option<String> {
    let out = Command::new("ps")
        .args(["-p", &pid.to_string(), "-o", "command="])
        .output()
        .ok()?;
    if !out.status.success() {
        return None;
    }
    let s = String::from_utf8_lossy(&out.stdout).trim().to_string();
    if s.is_empty() { None } else { Some(s) }
}

#[cfg(target_os = "linux")]
fn process_cmdline(pid: u32) -> Option<String> {
    let s = std::fs::read_to_string(format!("/proc/{pid}/cmdline")).ok()?;
    let joined = s.replace('\0', " ");
    if joined.trim().is_empty() { None } else { Some(joined) }
}

#[cfg(target_os = "windows")]
fn process_cmdline(pid: u32) -> Option<String> {
    let out = Command::new("tasklist")
        .args(["/FI", &format!("PID eq {pid}"), "/FO", "CSV", "/NH"])
        .output()
        .ok()?;
    if !out.status.success() {
        return None;
    }
    let s = String::from_utf8_lossy(&out.stdout).trim().to_string();
    if s.is_empty() || s.contains("没有运行") || s.to_lowercase().contains("no tasks") {
        None
    } else {
        Some(s)
    }
}

fn is_our_sidecar(cmdline: &str) -> bool {
    let c = cmdline.to_lowercase();
    c.contains("tender-agent-sidecar") || (c.contains("uvicorn") && c.contains("app.main:app"))
}

/// 杀孤儿进程（无句柄、无端口信息）：unix SIGTERM → ≤2s 轮询 → SIGKILL 兜底；
/// Windows taskkill 整树强杀。
#[cfg(unix)]
fn kill_orphan_graceful(pid: u32) {
    let pid = pid as i32;
    unsafe {
        libc::kill(pid, libc::SIGTERM);
    }
    for _ in 0..10 {
        // kill(pid,0) 返回 ESRCH = 进程已亡（僵尸被 reap 后）；仍存活则继续等
        if unsafe { libc::kill(pid, 0) } == -1 {
            return;
        }
        thread::sleep(Duration::from_millis(200));
    }
    unsafe {
        libc::kill(pid, libc::SIGKILL);
    }
}

#[cfg(windows)]
fn kill_orphan_graceful(pid: u32) {
    taskkill_tree(pid);
}

fn wait_healthy(port: u16, nonce: &str, attempts: u32) -> bool {
    let client = reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(1))
        .build()
        .expect("reqwest client");
    for _ in 0..attempts {
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

/// 启动序列是否已收尾（splash 已关、主窗已亮）——只在首次就绪/熔断时收尾一次，
/// 运行中崩溃重启不再抢焦点。
static SPLASH_DISMISSED: AtomicBool = AtomicBool::new(false);

/// 启动序列收尾：关 splash 窗、首次显示主窗（tauri.conf.json 里主窗 visible=false）。
/// 幂等：splash 不存在/已关、主窗已可见均 no-op；single-instance 回调也调它，
/// 防启动期二次双击把 splash 卡成死窗。熔断路径同样收尾——主窗红条（重试/日志/诊断）
/// 接管失败展示，不在 splash 里重复造。
pub fn reveal_main_from_splash(app: &AppHandle) {
    if SPLASH_DISMISSED.swap(true, Ordering::SeqCst) {
        return;
    }
    if let Some(w) = app.get_webview_window("splash") {
        // 先 hide 再 close：hide 同步生效保证视觉上 splash 先消失，close（销毁
        // WebView）是异步的，主窗 show 不等它——防两窗短暂并存
        let _ = w.hide();
        let _ = w.close();
    }
    if let Some(w) = app.get_webview_window("main") {
        if !w.is_visible().unwrap_or(true) {
            let _ = w.show();
        }
        let _ = w.set_focus();
    }
    log::info!("启动序列收尾：splash 关闭、主窗显示");
}

/// 杀进程树并回收；同时清空 child/info（供 healthz 失败、restart、退出共用）。
fn kill_and_reap(mgr: &SidecarManager) {
    let mut guard = mgr.child.lock().unwrap();
    if let Some(handle) = guard.take() {
        let port = mgr.info.lock().unwrap().as_ref().map(|i| i.port);
        handle.kill_tree(port);
    }
    drop(guard);
    *mgr.info.lock().unwrap() = None;
}

/// 后台 supervisor：拉起 → 探活 → 存活监控 → 崩溃/被要求重启时按指数退避重启。
/// 应用退出（stopping 置位）后不再拉起，避免残留孤儿 sidecar。
pub fn run_supervisor(app: AppHandle, mgr: Arc<SidecarManager>) {
    // dev/打包探测 + 数据目录解析必须先行：commands 的 export_diagnostics /
    // reveal_sidecar_logs / reveal 前缀校验都依赖 RESOLVED_DATA_DIR 已就位
    let mode = resolve_launch_mode(&app);
    let healthz_attempts = mode.healthz_attempts();
    // 改名迁移必须早于 RESOLVED_DATA_DIR 置位与 spawn：sidecar 一启动就读 DATA_DIR
    if let LaunchMode::Bundled { data_dir } = &mode {
        if let Some(parent) = data_dir.parent() {
            migrate_data_dir_if_legacy(data_dir, &parent.join(LEGACY_BUNDLE_ID));
        }
    }
    let _ = RESOLVED_DATA_DIR.set(mode.data_dir().clone());
    let mode_name = match mode {
        LaunchMode::Dev { .. } => "dev",
        LaunchMode::Bundled { .. } => "bundled",
    };
    log::info!("sidecar 启动模式: {mode_name}，数据目录: {}", mode.data_dir().display());
    // 启动期孤儿清扫：壳被强杀（kill -9/崩溃）时 Exit 钩子不执行，上一次的 sidecar
    // 可能残留为孤儿进程（握着 agent.db 连接占资源）——本次启动先按 pidfile 清掉
    sweep_orphan_sidecar();

    thread::spawn(move || {
        let mut restart_waits = 0u32;
        'outer: loop {
            if mgr.stopping.load(Ordering::SeqCst) {
                break;
            }
            let nonce = Uuid::new_v4().to_string();
            match spawn_sidecar(&app, &mode, &nonce) {
                Ok((handle, port, token)) => {
                    log::info!("sidecar spawned: pid={} port={}", handle.pid(), port);
                    *mgr.info.lock().unwrap() = Some(SidecarInfo { port, token: token.clone() });
                    *mgr.child.lock().unwrap() = Some(handle);
                    *mgr.state.lock().unwrap() = SidecarState::Starting;
                    emit(&app, SidecarState::Starting, &format!("port {port}"));

                    // 探活（healthz 成功前端口即知，前端可先拿 info）
                    if wait_healthy(port, &nonce, healthz_attempts) {
                        restart_waits = 0;
                        *mgr.fail_count.lock().unwrap() = 0;
                        *mgr.last_failure.lock().unwrap() = None;
                        // 消费探活窗口内积压的手动重启请求：点击落在退避/拉起阶段时
                        // 存活监控不会消费它，若残留会把刚拉起的健康进程误杀重拉
                        mgr.restart_requested.store(false, Ordering::SeqCst);
                        *mgr.state.lock().unwrap() = SidecarState::Running;
                        emit(&app, SidecarState::Running, "ok");
                        reveal_main_from_splash(&app);
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
                            format!("服务启动超时（{healthz_attempts} 秒内未就绪）"),
                        );
                        kill_and_reap(&mgr);
                        emit(&app, SidecarState::Failed, "healthz timeout");
                        log::warn!("sidecar healthz failed (attempt {failed})");

                        if failed >= MAX_RESTARTS {
                            emit(&app, SidecarState::Failed, "已达重启上限，停止自动重启");
                            // 熔断也收尾启动序列：关 splash 亮主窗，红条（重试/日志/诊断）接管
                            log::error!("sidecar healthz 连续失败达上限（{failed} 次），停止自动重启，等待手动触发");
                            reveal_main_from_splash(&app);
                            // 等待手动触发（restart_sidecar 会置 restart_requested）
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
                            reveal_main_from_splash(&app);
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

                // Some((描述, 人话失败分类))=已退出；None=仍在运行
                let exited: Option<(String, FailureInfo)> = {
                    let mut c = mgr.child.lock().unwrap();
                    match c.as_mut() {
                        Some(h) => h.poll_exit(),
                        None => Some((
                            "句柄缺失".into(),
                            FailureInfo {
                                kind: "exited".into(),
                                detail: "进程退出（退出状态未知）".into(),
                            },
                        )),
                    }
                };

                if let Some((how, failure)) = exited {
                    if mgr.stopping.load(Ordering::SeqCst) {
                        break 'outer;
                    }
                    // bundled 句柄自发退出（bootloader 被杀软/OOM 单独杀死）时
                    // python 子进程可能成孤儿继续占旧端口，重拉前清一次——
                    // dev 单进程形态无此问题
                    #[cfg(unix)]
                    if matches!(mgr.child.lock().unwrap().as_ref(), Some(SidecarHandle::Plugin { .. })) {
                        if let Some(port) = mgr.info.lock().unwrap().as_ref().map(|i| i.port) {
                            sweep_port_orphans(port);
                        }
                    }
                    let failed = {
                        let mut f = mgr.fail_count.lock().unwrap();
                        *f += 1;
                        *f
                    };
                    *mgr.state.lock().unwrap() = SidecarState::Failed;
                    set_failure(&mgr, &failure.kind, failure.detail.clone());
                    emit(&app, SidecarState::Failed, &failure.detail);
                    // 退出状态是崩溃诊断的第一现场（信号退出在 unix 下由 code() 反映）
                    log::warn!("sidecar exited unexpectedly: {how} (attempt {failed})");

                    if failed >= MAX_RESTARTS {
                        emit(&app, SidecarState::Failed, "已达重启上限，停止自动重启");
                        log::error!("sidecar 连续意外退出达上限（{failed} 次），停止自动重启，等待手动触发");
                        reveal_main_from_splash(&app);
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

    #[test]
    fn classify_plugin_termination_matches_std_semantics() {
        // 插件句柄拿不到 ExitStatus，分类必须与 std 路径同语义
        let f = classify_termination(Some(0), None);
        assert_eq!(f.kind, "exited");
        assert!(f.detail.contains("自行退出"));

        let f = classify_termination(Some(42), None);
        assert_eq!(f.kind, "exited");
        assert!(f.detail.contains("42"));

        let f = classify_termination(None, None);
        assert_eq!(f.kind, "exited");
        assert!(f.detail.contains("未知"));

        #[cfg(unix)]
        {
            let f = classify_termination(Some(0), Some(libc::SIGKILL));
            assert_eq!(f.kind, "crashed");
            assert!(f.detail.contains("强制终止"));
        }
    }

    /// 临时目录下的 (new, legacy) 一对，调用方自行造内容。
    fn tmp_dirs(name: &str) -> (PathBuf, PathBuf) {
        let root = std::env::temp_dir().join(format!("tender-migrate-{name}-{}", Uuid::new_v4()));
        (root.join("lingyan.ddmdj.com"), root.join(LEGACY_BUNDLE_ID))
    }

    fn write_marker(dir: &Path, file: &str, body: &str) {
        std::fs::create_dir_all(dir).unwrap();
        std::fs::write(dir.join(file), body).unwrap();
    }

    #[test]
    fn migrate_moves_legacy_data_dir() {
        let (new, legacy) = tmp_dirs("move");
        write_marker(&legacy, "agent.db", "old-state");

        assert!(migrate_data_dir_if_legacy(&new, &legacy));
        assert_eq!(std::fs::read_to_string(new.join("agent.db")).unwrap(), "old-state");
        assert!(!legacy.exists()); // 是搬迁不是拷贝：旧目录不留残骸

        // 再跑一次幂等（新目录已非空）
        assert!(!migrate_data_dir_if_legacy(&new, &legacy));
        let _ = std::fs::remove_dir_all(new.parent().unwrap());
    }

    #[test]
    fn migrate_replaces_empty_new_dir_without_touching_content() {
        let (new, legacy) = tmp_dirs("empty-new");
        std::fs::create_dir_all(&new).unwrap(); // 用户曾启动过一次新版留下的空目录
        write_marker(&legacy, "app.db", "old-state");

        assert!(migrate_data_dir_if_legacy(&new, &legacy));
        assert_eq!(std::fs::read_to_string(new.join("app.db")).unwrap(), "old-state");
        let _ = std::fs::remove_dir_all(new.parent().unwrap());
    }

    #[test]
    fn migrate_keeps_existing_new_data() {
        let (new, legacy) = tmp_dirs("keep-new");
        write_marker(&new, "app.db", "new-state");
        write_marker(&legacy, "app.db", "old-state");

        assert!(!migrate_data_dir_if_legacy(&new, &legacy));
        assert_eq!(std::fs::read_to_string(new.join("app.db")).unwrap(), "new-state");
        // 旧目录原样保留（绝不删——用户可手工抢救）
        assert_eq!(std::fs::read_to_string(legacy.join("app.db")).unwrap(), "old-state");
        let _ = std::fs::remove_dir_all(new.parent().unwrap());
    }

    #[test]
    fn migrate_noop_when_no_legacy() {
        let (new, legacy) = tmp_dirs("no-legacy");
        assert!(!migrate_data_dir_if_legacy(&new, &legacy)); // 全新安装
        assert!(!new.exists());
    }
}
