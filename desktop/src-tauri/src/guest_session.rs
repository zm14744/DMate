use std::time::{SystemTime, UNIX_EPOCH};
use tauri::{Builder, Runtime};

/// A fresh process gets a new marker; navigation and reload reuse this script.
pub fn configure<R: Runtime>(builder: Builder<R>) -> Builder<R> {
    let stamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    let token = format!("desktop-{}-{stamp}", std::process::id());
    builder.append_invoke_initialization_script(
        include_str!("guest-session.js").replace("__DMATE_GUEST_SESSION_TOKEN__", &token),
    )
}
