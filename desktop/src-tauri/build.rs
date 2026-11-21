use std::{env, fs, io, path::PathBuf, process::Command};

fn stage_offline_bundle() -> Result<(), Box<dyn std::error::Error>> {
    let manifest = PathBuf::from(env::var("CARGO_MANIFEST_DIR")?);
    let root = manifest.join("../..");
    let script = root.join("scripts/stage_native_offline.py");
    let output = PathBuf::from(env::var("OUT_DIR")?);
    let destination = output.join("dmate-offline");
    println!("cargo:rerun-if-changed={}", script.display());
    println!(
        "cargo:rerun-if-changed={}",
        root.join("static/offline-service-worker.js").display()
    );

    let run = |python| {
        Command::new(python)
            .arg(&script)
            .arg("--destination")
            .arg(&destination)
            .status()
    };
    let status = match run("python3") {
        Err(error) if error.kind() == io::ErrorKind::NotFound => run("python")?,
        result => result?,
    };
    if !status.success() {
        return Err(io::Error::other("The offline workspace asset staging failed").into());
    }

    let mut source =
        String::from("fn bundled_asset(path: &str) -> Option<&'static [u8]> {\n    match path {\n");
    for path in fs::read_to_string(destination.join("paths.txt"))?.lines() {
        let file = if matches!(path, "/offline" | "/static/offline.html") {
            "offline.html"
        } else {
            path.strip_prefix('/')
                .ok_or_else(|| io::Error::other("Invalid bundled asset path"))?
        };
        let input = if file == "offline.html" {
            "static/offline.html"
        } else {
            file
        };
        println!("cargo:rerun-if-changed={}", root.join(input).display());
        source.push_str(&format!(
            "        {path:?} => Some(include_bytes!(concat!(env!(\"OUT_DIR\"), \"/dmate-offline/\", {file:?}))),\n"
        ));
    }
    source.push_str("        _ => None,\n    }\n}\n");
    fs::write(output.join("dmate_offline_assets.rs"), source)?;
    Ok(())
}

fn main() {
    stage_offline_bundle().expect("DMate offline workspace could not be bundled");
    // Custom application commands must be in the ACL manifest; otherwise older
    // Tauri versions treat app commands more broadly than plugin commands.
    tauri_build::try_build(
        tauri_build::Attributes::new()
            .app_manifest(tauri_build::AppManifest::new().commands(&["dmate_offline_vault"])),
    )
    .expect("DMate permission manifest could not be built");
}
