#!/usr/bin/env bash
# Exercise the installed package with real confinement, a graphical session,
# and the host Secret portal. Only disposable CI keys and messages are used.
set -euo pipefail

if [[ "${GITHUB_ACTIONS:-}" != true || "${RUNNER_OS:-}" != Linux ]]; then
  echo 'This installation smoke check runs only on a disposable Linux Actions runner.' >&2
  exit 1
fi

if [[ "${1:-}" == --session ]]; then
  smoke_dir="$2"
  probe_id="release-check-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"
  [[ "$probe_id" =~ ^[a-zA-Z0-9-]{1,64}$ ]]
  export XDG_CONFIG_HOME="$smoke_dir/config"
  export XDG_DATA_HOME="$smoke_dir/data"
  export XDG_CACHE_HOME="$smoke_dir/cache"
  export XDG_CURRENT_DESKTOP=GNOME XDG_SESSION_TYPE=x11 GDK_BACKEND=x11
  export LIBGL_ALWAYS_SOFTWARE=1
  mkdir -p "$XDG_CONFIG_HOME/xdg-desktop-portal" "$XDG_DATA_HOME" "$XDG_CACHE_HOME"
  cat > "$XDG_CONFIG_HOME/xdg-desktop-portal/portals.conf" <<'PORTALS'
[preferred]
default=gtk
org.freedesktop.impl.portal.Secret=gnome-keyring
PORTALS
  dbus-update-activation-environment DISPLAY XAUTHORITY XDG_CURRENT_DESKTOP \
    XDG_SESSION_TYPE XDG_CONFIG_HOME XDG_DATA_HOME XDG_CACHE_HOME
  # This password protects an ephemeral CI-only host keyring, never a user key.
  printf '%s' 'dmate-disposable-ci-keyring' | \
    gnome-keyring-daemon --unlock --components=secrets > "$smoke_dir/keyring.env" 2> "$smoke_dir/keyring.log"
  /usr/libexec/xdg-desktop-portal > "$smoke_dir/portal.log" 2>&1 &
  portal_pid=$!
  app_pid=''
  probe_started=false
  # Only the host portal/keyring use these temporary XDG directories. Let the
  # Snap command chain establish its normal, confined application directories.
  snap_command=(env -u XDG_CONFIG_HOME -u XDG_DATA_HOME -u XDG_CACHE_HOME snap)
  cleanup_session() {
    if [[ "$probe_started" == true ]]; then
      timeout 30s "${snap_command[@]}" run --shell dmate -c \
        '"$SNAP/usr/lib/dmate/dmate-vault-probe" delete '"$probe_id" \
        >> "$smoke_dir/probe-cleanup.log" 2>&1 || true
    fi
    if [[ -n "$app_pid" ]]; then kill "$app_pid" 2>/dev/null || true; fi
    kill "$portal_pid" 2>/dev/null || true
  }
  trap cleanup_session EXIT
  portal_ready=false
  for attempt in {1..20}; do
    if timeout 3s gdbus call --session --dest org.freedesktop.portal.Desktop \
      --object-path /org/freedesktop/portal/desktop \
      --method org.freedesktop.DBus.Properties.Get org.freedesktop.portal.Secret version \
      > "$smoke_dir/portal-version.log" 2>&1; then
      portal_ready=true
      break
    fi
    sleep 1
  done
  if [[ "$portal_ready" != true ]]; then
    echo 'The real host Secret portal did not become available; no Snap artifact will be released.' >&2
    exit 1
  fi

  # Each invocation is a new confined process. The read must recover the same
  # key via the portal, not a process-local mock or an artifact-supplied claim.
  probe_started=true
  for phase in create read delete; do
    timeout 45s "${snap_command[@]}" run --shell dmate -c \
      '"$SNAP/usr/lib/dmate/dmate-vault-probe" '"$phase $probe_id" \
      > "$smoke_dir/probe-$phase.log" 2>&1
    case "$phase" in
      create) expected=DMATE_VAULT_PROBE_CREATED ;;
      read) expected=DMATE_VAULT_PROBE_PASSED ;;
      delete) expected=DMATE_VAULT_PROBE_CLEANED ;;
    esac
    grep -Fx "$expected" "$smoke_dir/probe-$phase.log"
  done
  probe_started=false

  "${snap_command[@]}" run dmate > "$smoke_dir/application.log" 2>&1 &
  app_pid=$!
  window_ready=false
  for attempt in {1..45}; do
    if ! kill -0 "$app_pid" 2>/dev/null; then
      echo 'The installed DMate application exited before opening a window.' >&2
      exit 1
    fi
    if xdotool search --onlyvisible --name DMate > "$smoke_dir/windows.log" 2>/dev/null; then
      window_ready=true
      break
    fi
    sleep 1
  done
  [[ "$window_ready" == true ]] || { echo 'No visible DMate window appeared.' >&2; exit 1; }
  sleep 3
  kill -0 "$app_pid"
  echo 'DMATE_SNAP_INSTALL_LAUNCH_AND_VAULT_PASSED'
  exit 0
fi

[[ $# -eq 1 && -f "$1" ]] || { echo 'Pass the built .snap file.' >&2; exit 1; }
if snap list dmate >/dev/null 2>&1; then
  echo 'Refusing to replace an existing DMate installation during the smoke check.' >&2
  exit 1
fi
[[ "$(snap debug confinement)" == strict ]] || {
  echo 'Strict Snap confinement is required for this package check.' >&2
  exit 1
}
smoke_dir="${RUNNER_TEMP:?}/dmate-snap-smoke-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"
mkdir -p "$smoke_dir" artifacts/snap-smoke
cleanup_package() {
  result=$?
  # Retain diagnostic logs only, never the temporary keyring or encrypted data.
  find "$smoke_dir" -maxdepth 1 -type f -name '*.log' -exec cp {} artifacts/snap-smoke/ \;
  sudo snap remove --purge dmate >/dev/null 2>&1 || true
  rm -rf -- "$smoke_dir"
  exit "$result"
}
trap cleanup_package EXIT
sudo snap install --dangerous "$(realpath "$1")"
snap connections dmate > "$smoke_dir/connections.log"

# An abstract session socket remains reachable through Snap's private /tmp;
# normal desktop/DBus interface confinement still applies to every request.
cat > "$smoke_dir/dbus-daemon" <<'DAEMON'
#!/usr/bin/env bash
exec /usr/bin/dbus-daemon --address="unix:abstract=/tmp/dbus-DMateSmoke-${UID}-$$" "$@"
DAEMON
chmod 700 "$smoke_dir/dbus-daemon"
xvfb-run --auto-servernum --server-args='-screen 0 1440x900x24' \
  dbus-run-session --dbus-daemon="$smoke_dir/dbus-daemon" -- \
  bash "$(realpath "$0")" --session "$smoke_dir"
