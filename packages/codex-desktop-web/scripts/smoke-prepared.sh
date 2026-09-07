#!/usr/bin/env bash
set -euo pipefail
runtime=${1:?prepared runtime directory is required}
work=$(mktemp -d)
app_pid=
display_pid=
# shellcheck disable=SC2329 # Invoked by the EXIT trap.
cleanup() {
  if [[ -n "$app_pid" ]]; then kill -- "-$app_pid" 2>/dev/null || true; fi
  if [[ -n "$display_pid" ]]; then kill "$display_pid" 2>/dev/null || true; fi
  if [[ -n "$app_pid" ]]; then wait "$app_pid" 2>/dev/null || true; fi
  if [[ -n "$display_pid" ]]; then wait "$display_pid" 2>/dev/null || true; fi
  rm -r "$work"
}
trap cleanup EXIT
trap 'exit 130' INT TERM
mkdir -m0700 "$work/home" "$work/run"
cat > "$work/session.conf" <<'EOF'
<!DOCTYPE busconfig PUBLIC "-//freedesktop//DTD D-Bus Bus Configuration 1.0//EN"
 "http://www.freedesktop.org/standards/dbus/1.0/busconfig.dtd">
<busconfig>
  <type>session</type>
  <listen>unix:tmpdir=/tmp</listen>
  <auth>EXTERNAL</auth>
  <policy context="default">
    <allow send_destination="*"/>
    <allow receive_sender="*"/>
    <allow own="*"/>
  </policy>
</busconfig>
EOF
Xvfb :98 -screen 0 1440x1000x24 -nolisten tcp > "$work/display.log" 2>&1 &
display_pid=$!
for _ in $(seq 1 100); do
  kill -0 "$display_pid" || { cat "$work/display.log" >&2; exit 1; }
  [[ -S /tmp/.X11-unix/X98 ]] && break
  sleep .1
done
# A fresh environment prevents the candidate from attaching to the active
# app-server, user profile, login state, or credentials during validation.
setsid env -i HOME="$work/home" PATH="$PATH" DISPLAY=:98 \
  XDG_RUNTIME_DIR="$work/run" CODEX_HOME="$work/home/.codex" \
  CODEX_WEB_HOST=127.0.0.1 CODEX_WEB_PORT=18214 CODEX_WEB_NATIVE_HOST_PORT=15175 \
  FONTCONFIG_FILE="${FONTCONFIG_FILE:-}" \
  dbus-run-session --config-file="$work/session.conf" -- "$runtime/electron" --no-sandbox --disable-gpu --disable-dev-shm-usage \
  > "$work/app.log" 2>&1 &
app_pid=$!
for _ in $(seq 1 60); do
  if ! kill -0 "$app_pid" 2>/dev/null; then cat "$work/app.log" >&2; exit 1; fi
  if curl -fsS --max-time 2 http://127.0.0.1:18214/health | jq -e '.status == "ok" and .relayConnected == true' >/dev/null; then
    curl -fsS --max-time 2 http://127.0.0.1:18214/ | rg -q '__codexElectronModule|/__bridge/electron-shim.js'
    exit 0
  fi
  sleep 1
done
cat "$work/app.log" >&2
exit 1
