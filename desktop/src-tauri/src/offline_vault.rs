use dmate_offline_vault::{dispatch, system::SystemStore, trusted_page, Request, VaultError};
use serde_json::Value;
use std::sync::{
    atomic::{AtomicU64, Ordering},
    Arc, Mutex,
};
use tauri::{Builder, Manager, Runtime, State, Url, Webview};
use tauri_plugin_opener::OpenerExt;
use zeroize::Zeroizing;

struct BridgeState {
    token: Zeroizing<String>,
    generation: AtomicU64,
    store: Mutex<Option<Arc<SystemStore>>>,
}

fn trusted_origin(url: &Url) -> bool {
    url.scheme() == "https"
        && url.host_str() == Some("dmate.zeabur.app")
        && url.port_or_known_default() == Some(443)
        && url.username().is_empty()
        && url.password().is_none()
}

fn trusted_window<R: Runtime>(webview: &Webview<R>) -> bool {
    webview.label() == "main"
        && webview.window().label() == "main"
        && webview.url().is_ok_and(|url| trusted_page(&url))
}

#[tauri::command]
async fn dmate_offline_vault<R: Runtime>(
    webview: Webview<R>,
    state: State<'_, Arc<BridgeState>>,
    request: Request,
    bridge_token: String,
) -> Result<Value, VaultError> {
    let bridge_token = Zeroizing::new(bridge_token);
    if !trusted_window(&webview) || bridge_token.as_str() != state.token.as_str() {
        return Err(VaultError::new(
            "ACCESS_DENIED",
            "The offline vault is unavailable to this page",
        ));
    }
    let generation = state.generation.load(Ordering::SeqCst);
    let store = {
        let mut slot = state.store.lock().map_err(|_| VaultError::unavailable())?;
        if slot.is_none() {
            let directory = webview
                .app_handle()
                .path()
                .app_local_data_dir()
                .map_err(|_| VaultError::unavailable())?;
            std::fs::create_dir_all(&directory).map_err(|_| VaultError::unavailable())?;
            *slot = Some(Arc::new(SystemStore::new(
                directory.join("offline-vault.lock"),
            )));
        }
        slot.as_ref().ok_or_else(VaultError::unavailable)?.clone()
    };
    // Keyring access may wait for the OS to unlock; keep it off the WebView/UI
    // thread. No OS error or user payload is logged or returned verbatim.
    let result = tauri::async_runtime::spawn_blocking(move || dispatch(store.as_ref(), request))
        .await
        .map_err(|_| VaultError::unavailable())?;
    if state.generation.load(Ordering::SeqCst) != generation || !trusted_window(&webview) {
        return Err(VaultError::new(
            "CONTEXT_CHANGED",
            "The offline page changed before the operation completed",
        ));
    }
    result
}

pub fn configure<R: Runtime>(builder: Builder<R>) -> Builder<R> {
    let mut bytes = Zeroizing::new([0u8; 32]);
    // Fail closed: the app can still run if secure randomness is unavailable,
    // but no vault bridge or native capability handler will be registered.
    if getrandom::getrandom(bytes.as_mut()).is_err() {
        return builder;
    }
    let token: String = bytes.iter().map(|byte| format!("{byte:02x}")).collect();
    let script = include_str!("offline-vault.js").replace("__DMATE_OFFLINE_VAULT_TOKEN__", &token);
    let state = Arc::new(BridgeState {
        token: Zeroizing::new(token),
        generation: AtomicU64::new(0),
        store: Mutex::new(None),
    });
    let navigation_state = state.clone();
    builder
        .manage(state)
        .plugin(
            tauri_plugin_opener::Builder::new()
                .open_js_links_on_click(false)
                .build(),
        )
        .plugin(
            tauri::plugin::Builder::<R>::new("offline-vault-navigation")
                .on_navigation(move |webview, url| {
                    if webview.label() != "main" {
                        return false;
                    }
                    if crate::offline_bundle::startup_document(url) {
                        return true;
                    }
                    if trusted_origin(url) {
                        navigation_state.generation.fetch_add(1, Ordering::SeqCst);
                        return true;
                    }
                    // Never load an untrusted document into a WebView holding
                    // asynchronous decrypt callbacks. Outside links use the system
                    // browser; webpage JS receives no opener or shell permission.
                    if matches!(url.scheme(), "https" | "http")
                        && url.username().is_empty()
                        && url.password().is_none()
                    {
                        let _ = webview
                            .app_handle()
                            .opener()
                            .open_url(url.as_str(), None::<&str>);
                    }
                    false
                })
                .build(),
        )
        .append_invoke_initialization_script(script)
        .invoke_handler(tauri::generate_handler![dmate_offline_vault])
}
