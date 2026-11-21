# Snap native vault and release checks

The Snap uses strict confinement and the existing GNOME extension. Online
features and the packaged app identity, input DEB name, and version are unchanged.

## Secret storage

Within a Snap, `SystemStore` uses libsecret's file backend. Libsecret requests an
application-scoped master secret from `org.freedesktop.portal.Secret`, then stores
the vault keys in an encrypted collection in the Snap's XDG data directory. The
desktop interface supplied by the GNOME extension permits the portal request;
the global `password-manager-service` interface is not required.

The Snap sets `SECRET_BACKEND=file` before the application starts. The native
adapter rejects a missing/different backend selection and libsecret's
`SECRET_FILE_TEST_PASSWORD` / `SECRET_FILE_TEST_PATH` overrides. If the Secret
portal, its backend, or its protected master secret is unavailable, operations
fail with `KEYSTORE_UNAVAILABLE`; there is no direct Secret Service, plaintext
file, browser-key, or session-only fallback. Portal operations have a 30-second
cancellation limit. The host may request unlocking its normal credential store.

Non-Snap Linux installations continue using the existing keyring Secret Service
backend. macOS and Windows continue using their existing native stores. The
service `app.dmate.offline-vault.v1`, public key IDs, AES-GCM envelope format, and
JavaScript bridge stay unchanged. Snap and unconfined installations deliberately
do not share their secret collections. A missing key must never be silently
replaced or treated as a reason to discard the existing encrypted records.

Build dependencies on Linux include `libsecret-1-dev` and the existing Tauri
dependencies. The Snap stages `libsecret-1-0`; core24 supplies a version newer
than 0.20.5, the first version with Snap Secret portal support. The Rust binding
is libsecret 0.4 because it uses GLib/GIO 0.18, matching the current Tauri stack.
The host needs a working Secret portal backend, for example current
`xdg-desktop-portal` and GNOME Keyring on an Ubuntu desktop. A mock DBus response
is not a substitute for this requirement.

## Packaged release probe

The build includes `usr/lib/dmate/dmate-vault-probe` as an explicit diagnostic
binary. It is not a launcher entry or a new Snap app; tests run it through
`snap run --shell dmate` so it gets the application's actual confinement and
environment. The probe uses the production `SystemStore` and crypto dispatcher,
creates a random disposable key, and writes only its public key ID and an
encrypted public test message under `$SNAP_USER_COMMON/dmate-vault-probe`.

Build the helper and provide the declared Snap build input:

```sh
cargo build --release --manifest-path desktop/src-tauri/offline-vault/Cargo.toml --bin dmate-vault-probe
mkdir -p snap-test
cp desktop/src-tauri/offline-vault/target/release/dmate-vault-probe snap-test/dmate-vault-probe
```

After installing the resulting strict Snap, use a unique public run ID. Each
line below must be a separate process; `read` verifies persistence beyond the
creating process. Run from a normal desktop session whose Secret portal and
credential store are available:

```sh
snap run --shell dmate -c '$SNAP/usr/lib/dmate/dmate-vault-probe create release-check-1'
snap run --shell dmate -c '$SNAP/usr/lib/dmate/dmate-vault-probe read release-check-1'
snap run --shell dmate -c '$SNAP/usr/lib/dmate/dmate-vault-probe delete release-check-1'
```

Successful output is respectively `DMATE_VAULT_PROBE_CREATED`,
`DMATE_VAULT_PROBE_PASSED`, and `DMATE_VAULT_PROBE_CLEANED`. Any failure is a
nonzero exit and must block publication. Always attempt cleanup after a failed
read. A release also needs a real application launch check, not only this helper.
Repeat on a supported clean desktop and confirm the offline workspace still
opens its encrypted records after restarting the installed application.

Unit tests run with `cargo test --manifest-path
desktop/src-tauri/offline-vault/Cargo.toml`. They cover protocol errors,
encryption, invalid stored keys, and refusal of insecure backend overrides.
They do not claim to validate Snap confinement. The separately ignored real
system-store roundtrip test requires an actual unlocked OS credential service.

## References

- [Canonical: Secret portal and Tauri clients](https://snapcraft.io/docs/how-to-guides/snap-development/use-the-secret-portal/)
- [Canonical: GNOME extension interfaces](https://ubuntu.com/docs/snapcraft/9/reference/extensions/gnome-extension/)
- [GNOME: libsecret simple API](https://gnome.pages.gitlab.gnome.org/libsecret/libsecret-simple-api.html)
