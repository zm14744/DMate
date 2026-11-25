#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod guest_session;
mod offline_bundle;
mod offline_vault;

fn main() {
    let builder = offline_bundle::configure(offline_vault::configure(guest_session::configure(
        tauri::Builder::default(),
    )));
    builder
        .run(tauri::generate_context!())
        .expect("DMate desktop failed to start");
}
