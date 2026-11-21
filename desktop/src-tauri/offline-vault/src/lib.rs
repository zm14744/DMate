//! UI-independent native crypto. Keys never cross the JavaScript bridge.
//!
//! OS credential stores protect keys at rest, not against malicious code already
//! running as the same unlocked OS user. This is not a hardware-key guarantee.

use aes_gcm::{
    aead::{Aead, Payload},
    Aes256Gcm, KeyInit, Nonce,
};
use base64::{engine::general_purpose::STANDARD, Engine};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use zeroize::Zeroizing;

pub const MAX_PLAINTEXT: usize = 16 * 1024 * 1024;
pub const MAX_AAD: usize = 4096;

#[derive(Clone, Debug, Serialize, PartialEq, Eq)]
pub struct VaultError {
    pub code: &'static str,
    pub message: &'static str,
}

impl VaultError {
    pub const fn new(code: &'static str, message: &'static str) -> Self {
        Self { code, message }
    }
    pub const fn invalid() -> Self {
        Self::new("INVALID_REQUEST", "Invalid offline vault request")
    }
    pub const fn unavailable() -> Self {
        Self::new(
            "KEYSTORE_UNAVAILABLE",
            "The system credential store is unavailable or locked",
        )
    }
    pub const fn missing() -> Self {
        Self::new("KEY_MISSING", "The offline vault key is missing")
    }
}

pub type Result<T> = std::result::Result<T, VaultError>;

#[cfg(all(feature = "system-keyring", target_os = "linux"))]
mod snap_portal;

/// No Debug implementation: requests may contain plaintext.
#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct Request {
    pub op: String,
    pub key_id: Option<String>,
    pub plaintext: Option<String>,
    pub aad: Option<String>,
    pub iv: Option<String>,
    pub ciphertext: Option<String>,
}

/// create() must be atomic with respect to other create()/delete() operations.
pub trait SecretStore {
    fn probe(&self) -> Result<()>;
    fn create(&self, id: &str, secret: &[u8]) -> Result<()>;
    fn read(&self, id: &str) -> Result<Zeroizing<Vec<u8>>>;
    fn delete(&self, id: &str) -> Result<()>;
}

pub fn trusted_page(url: &url::Url) -> bool {
    url.scheme() == "https"
        && url.host_str() == Some("dmate.zeabur.app")
        && url.port_or_known_default() == Some(443)
        && url.username().is_empty()
        && url.password().is_none()
        && matches!(url.path(), "/offline" | "/static/offline.html")
}

fn key_id(request: &Request) -> Result<&str> {
    request
        .key_id
        .as_deref()
        .filter(|id| {
            id.len() == 32
                && id
                    .bytes()
                    .all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c))
        })
        .ok_or_else(VaultError::invalid)
}

fn decode(value: Option<&str>, maximum: usize) -> Result<Zeroizing<Vec<u8>>> {
    let value = value.ok_or_else(VaultError::invalid)?;
    // Check before allocation and reject noncanonical encodings/whitespace.
    if value.len() > maximum.div_ceil(3) * 4 {
        return Err(VaultError::new(
            "VALUE_TOO_LARGE",
            "The offline vault value exceeds its size limit",
        ));
    }
    let bytes = Zeroizing::new(STANDARD.decode(value).map_err(|_| VaultError::invalid())?);
    if bytes.len() > maximum {
        return Err(VaultError::new(
            "VALUE_TOO_LARGE",
            "The offline vault value exceeds its size limit",
        ));
    }
    if STANDARD.encode(&bytes) != value {
        return Err(VaultError::invalid());
    }
    Ok(bytes)
}

fn cipher(store: &impl SecretStore, id: &str) -> Result<Aes256Gcm> {
    let secret = store.read(id)?;
    if secret.len() != 32 {
        return Err(VaultError::new(
            "KEY_INVALID",
            "The system credential store contains an invalid vault key",
        ));
    }
    Aes256Gcm::new_from_slice(&secret).map_err(|_| VaultError::unavailable())
}

/// Invoke only after the native host has verified caller origin and capability.
pub fn dispatch(store: &impl SecretStore, request: Request) -> Result<Value> {
    // Keep wire plaintext out of automatic diagnostic formatting and best-effort
    // erase its native String after dispatch; JS/IPC copies are not erasable here.
    let Request {
        op,
        key_id: id,
        plaintext,
        aad,
        iv,
        ciphertext,
    } = request;
    let plaintext = plaintext.map(Zeroizing::new);
    let request = Request {
        op,
        key_id: id,
        plaintext: None,
        aad,
        iv,
        ciphertext,
    };
    match request.op.as_str() {
        "capabilities" => {
            if request.key_id.is_some()
                || plaintext.is_some()
                || request.aad.is_some()
                || request.iv.is_some()
                || request.ciphertext.is_some()
            {
                return Err(VaultError::invalid());
            }
            store.probe()?;
            Ok(
                json!({"version":1,"provider":"desktop-keyring","protection":"os-keystore","hardwareBacked":null}),
            )
        }
        "create" => {
            let id = key_id(&request)?;
            if plaintext.is_some()
                || request.aad.is_some()
                || request.iv.is_some()
                || request.ciphertext.is_some()
            {
                return Err(VaultError::invalid());
            }
            let mut key = Zeroizing::new([0u8; 32]);
            getrandom::getrandom(key.as_mut()).map_err(|_| {
                VaultError::new("RANDOM_UNAVAILABLE", "Secure randomness is unavailable")
            })?;
            store.create(id, key.as_ref())?;
            Ok(json!({"keyId":id,"hardwareBacked":null}))
        }
        "delete" => {
            let id = key_id(&request)?;
            if plaintext.is_some()
                || request.aad.is_some()
                || request.iv.is_some()
                || request.ciphertext.is_some()
            {
                return Err(VaultError::invalid());
            }
            store.delete(id)?;
            Ok(json!({}))
        }
        "encrypt" => {
            let id = key_id(&request)?;
            if request.iv.is_some() || request.ciphertext.is_some() {
                return Err(VaultError::invalid());
            }
            let plaintext = decode(plaintext.as_ref().map(|s| s.as_str()), MAX_PLAINTEXT)?;
            let aad = decode(request.aad.as_deref(), MAX_AAD)?;
            let cipher = cipher(store, id)?;
            let mut iv = [0u8; 12];
            getrandom::getrandom(&mut iv).map_err(|_| {
                VaultError::new("RANDOM_UNAVAILABLE", "Secure randomness is unavailable")
            })?;
            let ciphertext = cipher
                .encrypt(
                    Nonce::from_slice(&iv),
                    Payload {
                        msg: &plaintext,
                        aad: &aad,
                    },
                )
                .map_err(|_| {
                    VaultError::new("ENCRYPTION_FAILED", "Offline vault encryption failed")
                })?;
            Ok(json!({"iv":STANDARD.encode(iv),"ciphertext":STANDARD.encode(ciphertext)}))
        }
        "decrypt" => {
            let id = key_id(&request)?;
            if plaintext.is_some() {
                return Err(VaultError::invalid());
            }
            let ciphertext = decode(request.ciphertext.as_deref(), MAX_PLAINTEXT + 16)?;
            let aad = decode(request.aad.as_deref(), MAX_AAD)?;
            let iv = decode(request.iv.as_deref(), 12)?;
            if iv.len() != 12 || ciphertext.len() < 16 {
                return Err(VaultError::invalid());
            }
            let cipher = cipher(store, id)?;
            let plaintext = Zeroizing::new(
                cipher
                    .decrypt(
                        Nonce::from_slice(&iv),
                        Payload {
                            msg: &ciphertext,
                            aad: &aad,
                        },
                    )
                    .map_err(|_| {
                        VaultError::new(
                            "AUTHENTICATION_FAILED",
                            "Offline vault authentication failed",
                        )
                    })?,
            );
            Ok(json!({"plaintext":STANDARD.encode(&plaintext)}))
        }
        _ => Err(VaultError::invalid()),
    }
}

#[cfg(feature = "system-keyring")]
pub mod system {
    use super::*;
    use fs2::FileExt;
    use std::{
        fs::{File, OpenOptions},
        path::PathBuf,
        sync::Mutex,
    };

    const SERVICE: &str = "app.dmate.offline-vault.v1";

    /// A file contains only an OS advisory lock, never a key or user data. It
    /// serializes check-then-create across simultaneous DMate processes, since
    /// credential-store set_secret() is an upsert on several platforms.
    pub struct SystemStore {
        lock_path: PathBuf,
        process_lock: Mutex<()>,
        #[cfg(target_os = "linux")]
        snap: bool,
    }

    impl SystemStore {
        pub fn new(lock_path: PathBuf) -> Self {
            Self {
                lock_path,
                process_lock: Mutex::new(()),
                #[cfg(target_os = "linux")]
                snap: ["SNAP", "SNAP_NAME", "SNAP_INSTANCE_NAME"]
                    .iter()
                    .any(|name| std::env::var_os(name).is_some()),
            }
        }

        fn locked<T>(&self, operation: impl FnOnce() -> Result<T>) -> Result<T> {
            let _guard = self
                .process_lock
                .lock()
                .map_err(|_| VaultError::unavailable())?;
            let mut options = OpenOptions::new();
            options.read(true).write(true).create(true).truncate(false);
            #[cfg(unix)]
            {
                use std::os::unix::fs::OpenOptionsExt;
                options.mode(0o600);
            }
            let lock: File = options
                .open(&self.lock_path)
                .map_err(|_| VaultError::unavailable())?;
            lock.lock_exclusive()
                .map_err(|_| VaultError::unavailable())?;
            let result = operation();
            // Closing releases the advisory lock on all supported platforms.
            drop(lock);
            result
        }

        fn entry(id: &str) -> Result<keyring::Entry> {
            keyring::Entry::new(SERVICE, id).map_err(|_| VaultError::unavailable())
        }

        fn lookup(&self, id: &str) -> Result<Option<Zeroizing<Vec<u8>>>> {
            #[cfg(target_os = "linux")]
            if self.snap {
                return super::snap_portal::lookup(SERVICE, id);
            }
            match Self::entry(id)?.get_secret() {
                Ok(secret) => Ok(Some(Zeroizing::new(secret))),
                Err(keyring::Error::NoEntry) => Ok(None),
                Err(_) => Err(VaultError::unavailable()),
            }
        }

        fn store(&self, id: &str, secret: &[u8]) -> Result<()> {
            #[cfg(target_os = "linux")]
            if self.snap {
                return super::snap_portal::store(SERVICE, id, secret);
            }
            Self::entry(id)?
                .set_secret(secret)
                .map_err(|_| VaultError::unavailable())
        }

        fn remove(&self, id: &str) -> Result<()> {
            #[cfg(target_os = "linux")]
            if self.snap {
                return super::snap_portal::remove(SERVICE, id);
            }
            match Self::entry(id)?.delete_credential() {
                Ok(()) | Err(keyring::Error::NoEntry) => Ok(()),
                Err(_) => Err(VaultError::unavailable()),
            }
        }
    }

    impl SecretStore for SystemStore {
        fn probe(&self) -> Result<()> {
            self.locked(|| {
                // Never creates a vault key. On Snap, libsecret may initialize
                // its app-scoped portal secret and encrypted collection.
                self.lookup("backend-health-probe").map(|_| ())
            })
        }

        fn create(&self, id: &str, secret: &[u8]) -> Result<()> {
            self.locked(|| {
                if self.lookup(id)?.is_some() {
                    return Err(VaultError::new(
                        "KEY_EXISTS",
                        "The offline vault key already exists",
                    ));
                }
                self.store(id, secret)?;
                let saved = self.lookup(id)?.ok_or_else(VaultError::unavailable)?;
                if saved.as_slice() != secret {
                    return Err(VaultError::unavailable());
                }
                Ok(())
            })
        }

        fn read(&self, id: &str) -> Result<Zeroizing<Vec<u8>>> {
            self.locked(|| self.lookup(id)?.ok_or_else(VaultError::missing))
        }

        fn delete(&self, id: &str) -> Result<()> {
            self.locked(|| self.remove(id))
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{collections::HashMap, sync::Mutex};
    #[derive(Default)]
    struct MemoryStore(Mutex<HashMap<String, Vec<u8>>>);
    impl SecretStore for MemoryStore {
        fn probe(&self) -> Result<()> {
            Ok(())
        }
        fn create(&self, id: &str, key: &[u8]) -> Result<()> {
            let mut entries = self.0.lock().unwrap();
            if entries.contains_key(id) {
                return Err(VaultError::new("KEY_EXISTS", "exists"));
            }
            entries.insert(id.to_owned(), key.to_vec());
            Ok(())
        }
        fn read(&self, id: &str) -> Result<Zeroizing<Vec<u8>>> {
            self.0
                .lock()
                .unwrap()
                .get(id)
                .cloned()
                .map(Zeroizing::new)
                .ok_or_else(VaultError::missing)
        }
        fn delete(&self, id: &str) -> Result<()> {
            self.0.lock().unwrap().remove(id);
            Ok(())
        }
    }
    const ID: &str = "0123456789abcdef0123456789abcdef";
    const ID2: &str = "abcdef0123456789abcdef0123456789";
    fn call(store: &impl SecretStore, request: Value) -> Result<Value> {
        dispatch(store, serde_json::from_value(request).unwrap())
    }
    fn encrypt(store: &impl SecretStore, aad: &str) -> Value {
        call(store, json!({"op":"encrypt","keyId":ID,"plaintext":STANDARD.encode("private 数学 note"),"aad":STANDARD.encode(aad)})).unwrap()
    }
    fn decrypt(store: &impl SecretStore, encrypted: &Value, aad: &str, id: &str) -> Result<Value> {
        call(
            store,
            json!({"op":"decrypt","keyId":id,"ciphertext":encrypted["ciphertext"],"iv":encrypted["iv"],"aad":STANDARD.encode(aad)}),
        )
    }

    #[test]
    fn data_round_trips_with_fresh_nonces() {
        let store = MemoryStore::default();
        call(&store, json!({"op":"create","keyId":ID})).unwrap();
        let first = encrypt(&store, "vault|notes|one");
        let second = encrypt(&store, "vault|notes|one");
        assert_ne!(first["iv"], second["iv"]);
        assert_ne!(first["ciphertext"], second["ciphertext"]);
        assert_eq!(
            decrypt(&store, &first, "vault|notes|one", ID).unwrap()["plaintext"],
            STANDARD.encode("private 数学 note")
        );
        assert_eq!(
            STANDARD
                .decode(first["iv"].as_str().unwrap())
                .unwrap()
                .len(),
            12
        );
    }
    #[test]
    fn tampering_swapping_and_wrong_key_fail() {
        let store = MemoryStore::default();
        for id in [ID, ID2] {
            call(&store, json!({"op":"create","keyId":id})).unwrap();
        }
        let mut value = encrypt(&store, "vault|notes|one");
        for (aad, id) in [
            ("other|notes|one", ID),
            ("vault|notes|two", ID),
            ("vault|notes|one", ID2),
        ] {
            assert_eq!(
                decrypt(&store, &value, aad, id).unwrap_err().code,
                "AUTHENTICATION_FAILED"
            );
        }
        let mut cipher = STANDARD
            .decode(value["ciphertext"].as_str().unwrap())
            .unwrap();
        cipher[0] ^= 1;
        value["ciphertext"] = json!(STANDARD.encode(cipher));
        assert_eq!(
            decrypt(&store, &value, "vault|notes|one", ID)
                .unwrap_err()
                .code,
            "AUTHENTICATION_FAILED"
        );
    }
    #[test]
    fn missing_or_existing_keys_are_never_replaced() {
        let store = MemoryStore::default();
        call(&store, json!({"op":"create","keyId":ID})).unwrap();
        let value = encrypt(&store, "");
        assert_eq!(
            call(&store, json!({"op":"create","keyId":ID}))
                .unwrap_err()
                .code,
            "KEY_EXISTS"
        );
        decrypt(&store, &value, "", ID).unwrap();
        call(&store, json!({"op":"delete","keyId":ID})).unwrap();
        assert_eq!(
            decrypt(&store, &value, "", ID).unwrap_err().code,
            "KEY_MISSING"
        );
        assert!(!store.0.lock().unwrap().contains_key(ID));
    }
    #[test]
    fn validates_untrusted_wire_input() {
        let store = MemoryStore::default();
        for id in ["", "../../secret", "0123456789ABCDEF0123456789ABCDEF"] {
            assert_eq!(
                call(&store, json!({"op":"create","keyId":id}))
                    .unwrap_err()
                    .code,
                "INVALID_REQUEST"
            );
        }
        assert!(serde_json::from_value::<Request>(
            json!({"op":"capabilities","service":"foreign"})
        )
        .is_err());
        for value in ["!", "YQ", "YQ==\n", "YR=="] {
            assert_eq!(
                call(
                    &store,
                    json!({"op":"encrypt","keyId":ID,"plaintext":value,"aad":""})
                )
                .unwrap_err()
                .code,
                "INVALID_REQUEST"
            );
        }
        assert_eq!(call(&store,json!({"op":"encrypt","keyId":ID,"plaintext":"","aad":STANDARD.encode(vec![0u8;MAX_AAD+1])})).unwrap_err().code,"VALUE_TOO_LARGE");
    }
    #[test]
    fn limits_native_access_to_exact_https_offline_pages() {
        for text in [
            "https://dmate.zeabur.app/offline",
            "https://dmate.zeabur.app:443/static/offline.html?v=1",
        ] {
            assert!(trusted_page(&url::Url::parse(text).unwrap()));
        }
        for text in [
            "http://dmate.zeabur.app/offline",
            "https://dmate.zeabur.app:444/offline",
            "https://dmate.zeabur.app.evil.test/offline",
            "https://evil.test/offline",
            "https://dmate.zeabur.app/",
            "https://dmate.zeabur.app/offline/",
            "https://user@dmate.zeabur.app/offline",
            "https://dmate.zeabur.app/%6fffline",
        ] {
            assert!(!trusted_page(&url::Url::parse(text).unwrap()), "{text}");
        }
    }

    #[cfg(feature = "system-keyring")]
    #[test]
    fn inaccessible_system_store_fails_without_a_plaintext_fallback() {
        let store = system::SystemStore::new(
            std::env::temp_dir()
                .join("dmate-missing-parent-never-created")
                .join("vault.lock"),
        );
        assert_eq!(
            call(&store, json!({"op":"capabilities"})).unwrap_err().code,
            "KEYSTORE_UNAVAILABLE"
        );
        assert_eq!(
            call(&store, json!({"op":"create","keyId":ID}))
                .unwrap_err()
                .code,
            "KEYSTORE_UNAVAILABLE"
        );
    }

    /// Run explicitly on each supported OS with its unlocked real credential
    /// service: cargo test real_system_keyring_roundtrip -- --ignored
    #[cfg(feature = "system-keyring")]
    #[test]
    #[ignore = "requires a real OS credential store; never substitute a mock"]
    fn real_system_keyring_roundtrip() {
        let mut random = [0u8; 16];
        getrandom::getrandom(&mut random).unwrap();
        let id: String = random.iter().map(|b| format!("{b:02x}")).collect();
        let lock = std::env::temp_dir().join(format!("dmate-vault-test-{id}.lock"));
        let store = system::SystemStore::new(lock.clone());
        let result = (|| -> Result<()> {
            call(&store, json!({"op":"capabilities"}))?;
            call(&store, json!({"op":"create","keyId":id}))?;
            let value = call(
                &store,
                json!({"op":"encrypt","keyId":id,"plaintext":STANDARD.encode("test only"),"aad":""}),
            )?;
            let restored = call(
                &store,
                json!({"op":"decrypt","keyId":id,"iv":value["iv"],"ciphertext":value["ciphertext"],"aad":""}),
            )?;
            assert_eq!(restored["plaintext"], STANDARD.encode("test only"));
            Ok(())
        })();
        let _ = call(&store, json!({"op":"delete","keyId":id}));
        let _ = std::fs::remove_file(lock);
        result.unwrap();
    }
}
