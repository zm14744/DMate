//! Snap uses libsecret's encrypted file backend with a master secret supplied
//! by the desktop Secret portal. It must never fall back to direct Secret
//! Service access or libsecret's test-password environment hooks.

use super::{Result, VaultError};
use base64::{engine::general_purpose::STANDARD, Engine};
use gio::prelude::CancellableExt;
use libsecret::{Schema, SchemaAttributeType, SchemaFlags, Value};
use std::{collections::HashMap, ffi::OsStr, sync::mpsc, time::Duration};
use zeroize::Zeroizing;

const CONTENT_TYPE: &str = "application/vnd.dmate.vault-key.base64";

fn safe_environment(
    snap_name: Option<&OsStr>,
    backend: Option<&OsStr>,
    test_password: bool,
    test_path: bool,
) -> bool {
    snap_name.is_some_and(|name| !name.is_empty())
        && backend == Some(OsStr::new("file"))
        && !test_password
        && !test_path
}

fn check_environment() -> Result<()> {
    if safe_environment(
        std::env::var_os("SNAP_NAME").as_deref(),
        std::env::var_os("SECRET_BACKEND").as_deref(),
        std::env::var_os("SECRET_FILE_TEST_PASSWORD").is_some(),
        std::env::var_os("SECRET_FILE_TEST_PATH").is_some(),
    ) {
        Ok(())
    } else {
        Err(VaultError::unavailable())
    }
}

fn schema(service: &str) -> Schema {
    Schema::new(
        service,
        SchemaFlags::NONE,
        HashMap::from([
            ("service", SchemaAttributeType::String),
            ("username", SchemaAttributeType::String),
        ]),
    )
}

fn attributes<'a>(service: &'a str, id: &'a str) -> HashMap<&'a str, &'a str> {
    HashMap::from([("service", service), ("username", id)])
}

// Calls already run on the host's blocking worker, never the WebView thread.
// Bound an unavailable/unanswered portal request instead of waiting forever.
fn with_cancellation<T>(operation: impl FnOnce(&gio::Cancellable) -> Result<T>) -> Result<T> {
    check_environment()?;
    let cancellable = gio::Cancellable::new();
    let timeout = cancellable.clone();
    let (finished, wait) = mpsc::channel();
    let worker = std::thread::Builder::new()
        .name("dmate-vault-timeout".into())
        .spawn(move || {
            if matches!(
                wait.recv_timeout(Duration::from_secs(30)),
                Err(mpsc::RecvTimeoutError::Timeout)
            ) {
                timeout.cancel();
            }
        })
        .map_err(|_| VaultError::unavailable())?;
    let result = operation(&cancellable);
    let _ = finished.send(());
    let _ = worker.join();
    result
}

fn decode_secret(content_type: &str, encoded: &[u8]) -> Result<Zeroizing<Vec<u8>>> {
    if content_type != CONTENT_TYPE || encoded.len() != 44 {
        return Err(VaultError::new(
            "KEY_INVALID",
            "The system credential store contains an invalid vault key",
        ));
    }
    let key = Zeroizing::new(STANDARD.decode(encoded).map_err(|_| {
        VaultError::new(
            "KEY_INVALID",
            "The system credential store contains an invalid vault key",
        )
    })?);
    let canonical = Zeroizing::new(STANDARD.encode(&key));
    if key.len() != 32 || canonical.as_bytes() != encoded {
        return Err(VaultError::new(
            "KEY_INVALID",
            "The system credential store contains an invalid vault key",
        ));
    }
    Ok(key)
}

pub(super) fn lookup(service: &str, id: &str) -> Result<Option<Zeroizing<Vec<u8>>>> {
    with_cancellation(|cancellable| {
        let value = libsecret::password_lookup_binary_sync(
            Some(&schema(service)),
            attributes(service, id),
            Some(cancellable),
        )
        .map_err(|_| VaultError::unavailable())?;
        value
            .map(|value| {
                let encoded = Zeroizing::new(value.get());
                decode_secret(value.content_type().as_str(), &encoded)
            })
            .transpose()
    })
}

pub(super) fn store(service: &str, id: &str, key: &[u8]) -> Result<()> {
    if key.len() != 32 {
        return Err(VaultError::invalid());
    }
    with_cancellation(|cancellable| {
        let encoded = Zeroizing::new(STANDARD.encode(key));
        // SecretValue owns a separate libsecret-managed secret buffer, which
        // libsecret clears on its last unref. DMate never logs or writes a
        // plaintext key; the file backend encrypts its collection via the portal.
        let value = Value::new(&encoded, CONTENT_TYPE);
        libsecret::password_store_binary_sync(
            Some(&schema(service)),
            attributes(service, id),
            None,
            "DMate offline vault",
            &value,
            Some(cancellable),
        )
        .map_err(|_| VaultError::unavailable())
    })
}

pub(super) fn remove(service: &str, id: &str) -> Result<()> {
    with_cancellation(|cancellable| {
        libsecret::password_clear_sync(
            Some(&schema(service)),
            attributes(service, id),
            Some(cancellable),
        )
        .map_err(|_| VaultError::unavailable())
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rejects_unconfined_backend_and_libsecret_test_hooks() {
        let snap = Some(OsStr::new("dmate"));
        let file = Some(OsStr::new("file"));
        assert!(safe_environment(snap, file, false, false));
        for (name, backend, password, path) in [
            (None, file, false, false),
            (Some(OsStr::new("")), file, false, false),
            (snap, None, false, false),
            (snap, Some(OsStr::new("service")), false, false),
            (snap, file, true, false),
            (snap, file, false, true),
        ] {
            assert!(!safe_environment(name, backend, password, path));
        }
    }

    #[test]
    fn rejects_malformed_stored_keys_without_replacing_them() {
        let encoded = Zeroizing::new(STANDARD.encode([0x42u8; 32]));
        assert_eq!(
            decode_secret(CONTENT_TYPE, encoded.as_bytes())
                .unwrap()
                .len(),
            32
        );
        assert_eq!(
            decode_secret("text/plain", encoded.as_bytes())
                .unwrap_err()
                .code,
            "KEY_INVALID"
        );
        assert_eq!(
            decode_secret(CONTENT_TYPE, &[b'!'; 44]).unwrap_err().code,
            "KEY_INVALID"
        );
        assert_eq!(
            decode_secret(CONTENT_TYPE, STANDARD.encode([0u8; 31]).as_bytes())
                .unwrap_err()
                .code,
            "KEY_INVALID"
        );
    }
}
