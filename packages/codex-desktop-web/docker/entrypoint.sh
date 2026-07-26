#!/bin/sh
set -eu

export HOME="${HOME:-/home/codex}"
export CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
export CODEX_WEB_HOST="${CODEX_WEB_HOST:-0.0.0.0}"
export CODEX_WEB_PORT="${CODEX_WEB_PORT:-8214}"
export CODEX_WEB_UPLOAD_ROOT="${CODEX_WEB_UPLOAD_ROOT:-/tmp/codex-web-uploads}"
export DISPLAY="${DISPLAY:-:99}"

mkdir -p "$CODEX_HOME" "$CODEX_WEB_UPLOAD_ROOT" /workspace
display_number="${DISPLAY#:}"
rm -f "/tmp/.X${display_number}-lock" "/tmp/.X11-unix/X${display_number}"
Xvfb "$DISPLAY" -screen 0 1440x1000x24 -nolisten tcp &
xvfb_pid=$!
electron_pid=

cleanup() {
  if [ -n "$electron_pid" ]; then
    kill "$electron_pid" 2>/dev/null || true
  fi
  kill "$xvfb_pid" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

for _ in $(seq 1 100); do
  [ -S "/tmp/.X11-unix/X${display_number}" ] && break
  sleep 0.1
done

/opt/codex-desktop/runtime/electron \
  --no-sandbox \
  --disable-dev-shm-usage &
electron_pid=$!
set +e
wait "$electron_pid"
status=$?
set -e
electron_pid=
exit "$status"
