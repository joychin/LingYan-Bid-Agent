mod sidecar;

use std::path::PathBuf;
use std::sync::Arc;
use std::time::{Duration, Instant};

use tauri::{AppHandle, Manager, RunEvent, State};
use tauri_plugin_opener::OpenerExt;

use sidecar::{SidecarInfo, SidecarManager};

/// 返回 sidecar 地址（port + token）。sidecar 拉起前会短暂等待，保证前端总能拿到真值。
///
/// 注意：state 以 `Arc<SidecarManager>` 注册（supervisor 线程 + commands + 退出钩子共享同一实例），
/// 命令签名必须用 `State<Arc<SidecarManager>>`，否则 Tauri 报「state not managed」。
#[tauri::command]
fn get_sidecar_info(state: State<'_, Arc<SidecarManager>>) -> Result<SidecarInfo, String> {
    let deadline = Instant::now() + Duration::from_secs(20);
    loop {
        if let Some(info) = state.info.lock().unwrap().clone() {
            return Ok(info);
        }
        if Instant::now() >= deadline {
            return Err("sidecar 尚未就绪".into());
        }
        std::thread::sleep(Duration::from_millis(200));
    }
}

/// 保存某模型 profile 的 API Key 到钥匙串 account model-key-<id>，成功后重启 sidecar
/// 使 MODEL_KEYS 注入生效。key 非空才写（留空 = 保持原值）、永不返回、永不进 HTTP；
/// profile 的 base_url/model 等非机密字段经 HTTP PUT /settings/models 持久化。
#[tauri::command]
fn set_model_key(state: State<'_, Arc<SidecarManager>>, model_id: String, api_key: String) -> Result<(), String> {
    let pid = model_id.trim();
    if pid.is_empty() {
        return Err("缺少模型 id".into());
    }
    let key = api_key.trim();
    if key.is_empty() {
        return Err("请填写 API Key".into());
    }
    let account = format!("model-key-{pid}");
    sidecar::keychain_set(&account, key).map_err(|e| format!("保存钥匙串失败: {e}"))?;
    // 触发 supervisor 重启 sidecar（新 MODEL_KEYS 生效）
    state.restart_requested.store(true, std::sync::atomic::Ordering::SeqCst);
    Ok(())
}

/// 保存百度云文档解析凭证（PaddleOCR-VL 的 AK/SK）到钥匙串两 account，成功后重启 sidecar
/// 使 spawn env 注入生效。字段非空才写（留空 = 保持原值）；两字段全空报错。
/// 凭证永不返回、永不进 HTTP。
#[tauri::command]
fn set_baidu_ocr_keys(api_key: String, secret_key: String) -> Result<(), String> {
    let ak = api_key.trim();
    let sk = secret_key.trim();
    if ak.is_empty() && sk.is_empty() {
        return Err("请填写 API Key 与 Secret Key".into());
    }
    if !ak.is_empty() {
        sidecar::keychain_set(sidecar::KEYRING_ACCOUNT_BAIDU_AK, ak)
            .map_err(|e| format!("保存钥匙串失败: {e}"))?;
    }
    if !sk.is_empty() {
        sidecar::keychain_set(sidecar::KEYRING_ACCOUNT_BAIDU_SK, sk)
            .map_err(|e| format!("保存钥匙串失败: {e}"))?;
    }
    Ok(())
}

/// 只返回布尔：钥匙串对应 account 是否已有值（永不返回本体）。
/// role = "llm" | "vlm" | "baidu-ocr-api" | "baidu-ocr-secret" | "model:<profile_id>"
/// （model: 前缀按 profile 查 model-key-<id>，旧 account 兜底语义同 resolve_model_key）。
#[tauri::command]
fn get_api_key_has_value(role: String) -> Result<bool, String> {
    if let Some(pid) = role.strip_prefix("model:") {
        if pid.trim().is_empty() {
            return Err("缺少模型 id".into());
        }
        return Ok(sidecar::resolve_model_key(pid).is_some());
    }
    let account = match role.as_str() {
        "llm" => sidecar::KEYRING_ACCOUNT_LLM,
        "vlm" => sidecar::KEYRING_ACCOUNT_VLM,
        "baidu-ocr-api" => sidecar::KEYRING_ACCOUNT_BAIDU_AK,
        "baidu-ocr-secret" => sidecar::KEYRING_ACCOUNT_BAIDU_SK,
        _ => return Err(format!("未知角色: {role}")),
    };
    Ok(sidecar::keychain_has_value(account))
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
            if let Some(w) = app.get_webview_window("main") {
                let _ = w.unminimize();
                let _ = w.show();
                let _ = w.set_focus();
            }
        }))
        // 记住窗口大小/位置（退出自动持久化到系统 app 配置目录），纯 plumbing 无 IPC
        .plugin(tauri_plugin_window_state::Builder::default().build())
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
        .manage(mgr.clone())
        .setup(move |app| {
            sidecar::run_supervisor(app.handle().clone(), mgr.clone());
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            get_sidecar_info,
            set_model_key,
            set_baidu_ocr_keys,
            get_api_key_has_value,
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
