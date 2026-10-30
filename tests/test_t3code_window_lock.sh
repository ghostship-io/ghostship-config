#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
export WINDOW_DIR="$tmp/window"
mkdir -p "$WINDOW_DIR"
touch "$WINDOW_DIR/window.start"
# A live writer retains the shared lock until it exits.
bash -c 'source "$1"; announce_intent deploy; touch "$2"; read -r _ || true' _ "$root/packages/t3code/window-intent.sh" "$tmp/ready" < <(sleep 2) &
writer=$!
for _ in {1..100}; do [[ -e $tmp/ready ]] && break; sleep 0.01; done
[[ -e $tmp/ready ]]
if flock -n -x "$WINDOW_DIR/window.lock" true; then echo 'exclusive lock was not blocked' >&2; exit 1; fi
wait "$writer"
compgen -G "$WINDOW_DIR/effect-intent.deploy.*" >/dev/null
# Exclusive window operation prevents another writer from announcing.
exec 8>"$WINDOW_DIR/window.lock"
flock -x 8
bash -c 'source "$1"; announce_intent activate; touch "$2"' _ "$root/packages/t3code/window-intent.sh" "$tmp/second" 8>&- &
writer=$!
sleep 0.2
[[ ! -e $tmp/second ]]
flock -u 8
wait "$writer"
[[ -e $tmp/second ]]
echo 'Window locks serialize writers and exclusive transitions.'
