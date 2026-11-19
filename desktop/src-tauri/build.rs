fn main() {
    // Custom application commands must be in the ACL manifest; otherwise older
    // Tauri versions treat app commands more broadly than plugin commands.
    tauri_build::try_build(
        tauri_build::Attributes::new()
            .app_manifest(tauri_build::AppManifest::new().commands(&["dmate_offline_vault"])),
    )
    .expect("DMate permission manifest could not be built");
}
