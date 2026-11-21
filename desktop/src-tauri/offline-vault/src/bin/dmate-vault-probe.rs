//! Explicit release-test helper, run inside the application's Snap confinement.
//! Persists only a public test identifier and an encrypted public test message;
//! it never prints, exports, or writes a vault key.

#[cfg(target_os = "linux")]
mod probe {
    use base64::{engine::general_purpose::STANDARD, Engine};
    use dmate_offline_vault::{dispatch, system::SystemStore, Request, SecretStore};
    use serde::{Deserialize, Serialize};
    use serde_json::{json, Value};
    use std::{
        fs,
        io::{Read, Write},
        os::unix::fs::OpenOptionsExt,
        path::PathBuf,
    };

    const MESSAGE: &str = "DMate packaged vault release check";
    const AAD: &str = "DMate snap probe v1";

    #[derive(Serialize, Deserialize)]
    #[serde(deny_unknown_fields)]
    struct State {
        key_id: String,
        sealed: Value,
    }

    fn call(store: &SystemStore, value: Value) -> Result<Value, String> {
        let request: Request =
            serde_json::from_value(value).map_err(|_| "Invalid probe request")?;
        dispatch(store, request).map_err(|error| error.code.to_string())
    }

    pub fn run() -> Result<(), String> {
        let args: Vec<String> = std::env::args().skip(1).collect();
        if args.len() != 2
            || !matches!(args[0].as_str(), "create" | "read" | "delete")
            || args[1].is_empty()
            || args[1].len() > 64
            || !args[1]
                .bytes()
                .all(|value| value.is_ascii_alphanumeric() || value == b'-')
        {
            return Err("Usage: dmate-vault-probe create|read|delete RUN-ID".into());
        }
        if std::env::var_os("SNAP_NAME").is_none() {
            return Err("The release probe must run inside the DMate Snap".into());
        }
        let directory = PathBuf::from(
            std::env::var_os("SNAP_USER_COMMON").ok_or("The Snap data directory is unavailable")?,
        )
        .join("dmate-vault-probe");
        fs::create_dir_all(&directory).map_err(|_| "Cannot create probe directory")?;
        let store = SystemStore::new(directory.join("vault.lock"));
        call(&store, json!({"op":"capabilities"}))?;
        let state_path = directory.join(format!("{}.json", args[1]));
        if args[0] == "create" {
            let mut random = [0u8; 16];
            getrandom::getrandom(&mut random).map_err(|_| "Secure randomness unavailable")?;
            let id: String = random.iter().map(|byte| format!("{byte:02x}")).collect();
            let mut file = fs::OpenOptions::new()
                .write(true)
                .create_new(true)
                .mode(0o600)
                .open(&state_path)
                .map_err(|_| "The probe state exists or cannot be created")?;
            let result = (|| {
                call(&store, json!({"op":"create","keyId":id}))?;
                let sealed = call(
                    &store,
                    json!({"op":"encrypt","keyId":id,
                    "plaintext":STANDARD.encode(MESSAGE),"aad":STANDARD.encode(AAD)}),
                )?;
                let state = serde_json::to_vec(&State {
                    key_id: id.clone(),
                    sealed,
                })
                .map_err(|_| "Cannot encode public probe state")?;
                file.write_all(&state)
                    .and_then(|_| file.sync_all())
                    .map_err(|_| "Cannot persist public probe state")?;
                Ok::<(), String>(())
            })();
            if result.is_err() {
                let _ = call(&store, json!({"op":"delete","keyId":id}));
                let _ = fs::remove_file(&state_path);
            }
            result?;
            println!("DMATE_VAULT_PROBE_CREATED");
        } else {
            let mut public_state = Vec::new();
            fs::File::open(&state_path)
                .map_err(|_| "Cannot read public probe state")?
                .take(8193)
                .read_to_end(&mut public_state)
                .map_err(|_| "Cannot read public probe state")?;
            if public_state.len() > 8192 {
                return Err("The public probe state exceeds its size limit".into());
            }
            let state: State =
                serde_json::from_slice(&public_state).map_err(|_| "Invalid public probe state")?;
            if args[0] == "read" {
                let restored = call(
                    &store,
                    json!({"op":"decrypt","keyId":state.key_id,
                    "iv":state.sealed["iv"],"ciphertext":state.sealed["ciphertext"],
                    "aad":STANDARD.encode(AAD)}),
                )?;
                if restored["plaintext"] != STANDARD.encode(MESSAGE) {
                    return Err("The persisted vault roundtrip did not match".into());
                }
                println!("DMATE_VAULT_PROBE_PASSED");
            } else {
                call(&store, json!({"op":"delete","keyId":state.key_id}))?;
                match store.read(&state.key_id) {
                    Err(error) if error.code == "KEY_MISSING" => {}
                    _ => return Err("The probe key was not removed".into()),
                }
                fs::remove_file(&state_path).map_err(|_| "Cannot remove public probe state")?;
                println!("DMATE_VAULT_PROBE_CLEANED");
            }
        }
        Ok(())
    }
}

fn main() {
    #[cfg(target_os = "linux")]
    match probe::run() {
        Ok(()) => {}
        Err(error) => {
            eprintln!("Snap vault probe failed: {error}");
            std::process::exit(1);
        }
    }
    #[cfg(not(target_os = "linux"))]
    {
        eprintln!("The packaged Snap vault probe requires Linux");
        std::process::exit(1);
    }
}
