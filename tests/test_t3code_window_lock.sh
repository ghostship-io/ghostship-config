#!/usr/bin/env bash
# shellcheck disable=SC2016
set -euo pipefail
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
tmp=$(mktemp -d)
writer=
cleanup() {
  if [[ -n $writer ]]; then
    kill -- "-$writer" 2>/dev/null || true
    wait "$writer" 2>/dev/null || true
  fi
  rm -rf "$tmp"
}
trap cleanup EXIT
export WINDOW_DIR="$tmp/window" WINDOW_CONFIG="$tmp/config"
mkdir -p "$WINDOW_DIR/current"
printf '%s\n' "$WINDOW_DIR" > "$WINDOW_CONFIG"
touch "$WINDOW_DIR/window.lock" "$WINDOW_DIR/current/window.start"
printf '%s\n' current > "$WINDOW_DIR/active-window"
mkfifo "$tmp/control"
exec 3<>"$tmp/control"
wait_for_file() {
  local file=$1
  for _ in {1..600}; do
    [[ -e $file ]] && return 0
    kill -0 "$writer" 2>/dev/null || return 1
    sleep 0.05
  done
  echo "timed out waiting for fixture writer" >&2
  return 1
}
# The writer holds its lock until the parent explicitly releases it. Cleanup
# kills and reaps its process group before removing the fixture directory.
setsid bash -c 'set -e; source "$1"; announce_intent deploy; touch "$2"; read -r _' _ "$root/packages/t3code/window-intent.sh" "$tmp/ready" < "$tmp/control" &
writer=$!
wait_for_file "$tmp/ready"
if flock -n -x "$WINDOW_DIR/window.lock" true; then echo 'exclusive lock was not blocked' >&2; exit 1; fi
printf 'release\n' >&3
wait "$writer"
shopt -s nullglob
intents=("$WINDOW_DIR/current"/effect-intent.deploy.*)
(( ${#intents[@]} > 0 ))
# Exclusive window operation prevents another writer from announcing.
exec 8>"$WINDOW_DIR/window.lock"
flock -x 8
setsid bash -c 'set -e; source "$1"; touch "$2"; announce_intent activate; touch "$3"' _ "$root/packages/t3code/window-intent.sh" "$tmp/attempt" "$tmp/second" 8>&- &
writer=$!
wait_for_file "$tmp/attempt"
[[ ! -e $tmp/second ]]
flock -u 8
wait "$writer"
writer=
[[ -e $tmp/second ]]
echo 'Window locks serialize writers and exclusive transitions.'
