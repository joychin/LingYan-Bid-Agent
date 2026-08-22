mod sidecar;

use std::sync::Arc;
use std::time::{Duration, Instant};

use tauri::{Manager, RunEvent, State};

use sidecar::{LlmSettings, SidecarInfo, SidecarManager};

/// 返回 sidecar 地址（port + token）。sidecar 拉起前会短暂等待，保证前端总能拿到真值。
#[tauri::command]
fn get_sidecar_info(state: State<'_, SidecarManager>) -> Result<SidecarInfo, String> {
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
fn get_llm_settings(state: State<'_, SidecarManager>) -> LlmSettings {
    state.settings.lock().unwrap().clone()
}

/// 保存 api_key 到钥匙串（service=tender-agent, account=llm-api-key），
/// 更新 base_url/model 并重启 sidecar 使其生效。api_key 永不返回、永不进 HTTP。
#[tauri::command]
fn set_llm_settings(
    state: State<'_, SidecarManager>,
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

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let mgr = Arc::new(SidecarManager::default());

    let app = tauri::Builder::default()
        .manage(mgr.clone())
        .setup(move |app| {
            sidecar::run_supervisor(app.handle().clone(), mgr.clone());
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            get_sidecar_info,
            get_llm_settings,
            set_llm_settings,
            get_api_key_has_value
        ])
        .build(tauri::generate_context!())
        .expect("error while building tauri application");

    app.run(|app_handle, event| {
        if let RunEvent::Exit = event {
            // 退出时杀 sidecar 进程树
            if let Some(state) = app_handle.try_state::<SidecarManager>() {
                sidecar::shutdown(state.inner());
            }
        }
    });
}
