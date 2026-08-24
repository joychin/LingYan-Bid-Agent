mod sidecar;

use std::path::PathBuf;
use std::sync::Arc;
use std::time::{Duration, Instant};

use tauri::{AppHandle, Manager, RunEvent, State};
use tauri_plugin_opener::OpenerExt;

use sidecar::{LlmSettings, SidecarInfo, SidecarManager};

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

#[tauri::command]
fn get_llm_settings(state: State<'_, Arc<SidecarManager>>) -> LlmSettings {
    state.settings.lock().unwrap().clone()
}

/// 保存 api_key 到钥匙串（service=tender-agent, account=llm-api-key），
/// 更新 base_url/model 并重启 sidecar 使其生效。api_key 永不返回、永不进 HTTP。
#[tauri::command]
fn set_llm_settings(
    state: State<'_, Arc<SidecarManager>>,
    base_url: Option<String>,
    model: Option<String>,
    api_key: Option<String>,
) -> Result<(), String> {
    if let Some(key) = api_key {
        if !key.is_empty() {
            sidecar::keychain_set(&key).map_err(|e| format!("保存钥匙串失败: {e}"))?;
        }
    }
    let (eff_base, eff_model) = {
        let mut s = state.settings.lock().unwrap();
        if let Some(b) = base_url {
            if !b.trim().is_empty() {
                s.base_url = b.trim().to_string();
            }
        }
        if let Some(m) = model {
            if !m.trim().is_empty() {
                s.model = m.trim().to_string();
            }
        }
        (s.base_url.clone(), s.model.clone())
    };
    // 持久化到 settings.json（与 sidecar HTTP PUT 共享单一真值），避免重启后回滚
    sidecar::write_settings_file(&eff_base, &eff_model).map_err(|e| format!("保存设置失败: {e}"))?;
    // 触发 supervisor 重启 sidecar（新 env 生效）
    state.restart_requested.store(true, std::sync::atomic::Ordering::SeqCst);
    Ok(())
}

/// 只返回布尔：钥匙串里是否已有 key（永不返回 key 本体）。
#[tauri::command]
fn get_api_key_has_value() -> bool {
    sidecar::keychain_has_value()
}

/// 在系统文件管理器中定位工作区里的产物文件。
///
/// path 仅允许 `data/workspace/` 下的绝对路径（做 canonicalize 前缀校验），
/// 防止被诱导去打开工作区外的敏感文件。非 Tauri 环境不可用。
#[tauri::command]
fn reveal_in_folder(app: AppHandle, path: String) -> Result<(), String> {
    let root = sidecar::workspace_dir()
        .canonicalize()
        .map_err(|e| format!("无法解析工作区路径: {e}"))?;
    let target = PathBuf::from(&path)
        .canonicalize()
        .map_err(|e| format!("无法解析文件路径: {e}"))?;
    if !target.starts_with(&root) {
        return Err("路径不在工作区范围内".into());
    }
    app.opener()
        .reveal_item_in_dir(target.to_str().ok_or("路径含非法字符")?)
        .map_err(|e| format!("打开所在目录失败: {e}"))
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let mgr = Arc::new(SidecarManager::default());

    let app = tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .manage(mgr.clone())
        .setup(move |app| {
            sidecar::run_supervisor(app.handle().clone(), mgr.clone());
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            get_sidecar_info,
            get_llm_settings,
            set_llm_settings,
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
