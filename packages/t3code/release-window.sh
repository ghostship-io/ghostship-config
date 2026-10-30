#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
source "${WINDOW_INTENT_HELPER:?}"
: "${STATE_DIR:?}" "${SYSTEMCTL_BIN:?}" "${PODMAN_BIN:?}" "${PODMAN_TARGET:?}" "${WINDOW_UNIT:?}" "${HOLD_FILE:?}" "${LOCK_CANDIDATE:?}" "${LOCK_HARDENING:?}" "${PROFILE:?}" "${SYSTEMD_RUN_BIN:?}"
window_root
fail() { echo "STOP: $*" >&2; exit 1; }
unit_state() { "$SYSTEMCTL_BIN" show "$1.service" -p ActiveState --value; }
preflight() {
  [[ -d $WINDOW_ROOT && -f $WINDOW_ROOT/window.lock && -f $STATE_DIR/deploy.lock ]] || fail 'missing stable lock or state'
  [[ -f $STATE_DIR/applied && -f $STATE_DIR/desired ]] || fail 'deployment state missing'
  flock -n -s "$STATE_DIR/deploy.lock" true || fail 'deploy writer holds lock'
  [[ $(unit_state ghostship-t3code-deploy) == inactive ]] || fail 'deploy service active or failed'
  [[ $(unit_state t3code-podman-candidate) == inactive ]] || fail 'candidate service active or failed'
  [[ $("$PODMAN_BIN" inspect "$PODMAN_TARGET" --format '{{.State.Health.Status}}') == healthy ]] || fail 'target unhealthy or unknown'
}
lock_window() { exec 8<"$WINDOW_ROOT/window.lock"; flock -x 8; }
read_active() {
  [[ -f $WINDOW_ROOT/active-window && ! -L $WINDOW_ROOT/active-window ]] || fail 'missing active window'
  id=$(cat "$WINDOW_ROOT/active-window")
  window_id_valid "$id" || fail 'invalid active window'
  dir=$WINDOW_ROOT/$id
  [[ -d $dir && ! -L $dir && -f $dir/window.start && ! -L $dir/window.start ]] || fail 'missing start record'
}
snapshot() {
  [[ -L $PROFILE && -f $STATE_DIR/applied && -f $STATE_DIR/desired ]] || return 1
  printf 'generation=%s\napplied=%s\ndesired=%s\n' "$(readlink "$PROFILE")" "$(cat "$STATE_DIR/applied")" "$(cat "$STATE_DIR/desired")"
  if [[ -e $STATE_DIR/failed-candidate ]]; then
    [[ -f $STATE_DIR/failed-candidate && ! -L $STATE_DIR/failed-candidate ]] || return 1
    printf 'failed=%s\n' "$(sha256sum "$STATE_DIR/failed-candidate" | cut -d' ' -f1)"
  else printf 'failed=absent\n'; fi
}
case ${1:-} in
 preflight) preflight ;;
 start)
  [[ $# == 2 ]] || fail 'usage: start WINDOW_ID'
  id=$2; window_id_valid "$id" || fail 'invalid window id'
  : "${WINDOW_SECONDS:?}"
  preflight
  lock_window
  preflight
  [[ ! -e $WINDOW_ROOT/active-window && ! -e $WINDOW_ROOT/$id ]] || fail 'window already exists or active'
  [[ $(unit_state "$WINDOW_UNIT") == inactive ]] || fail 'window holder not inactive'
  [[ -f $LOCK_CANDIDATE && -f $LOCK_HARDENING ]] || fail 'candidate lock missing'
  flock -n -s "$LOCK_CANDIDATE" true && flock -n -s "$LOCK_HARDENING" true || fail 'candidate lock held'
  baseline=$(snapshot) || fail 'baseline unknown'
  mkdir -m 0700 "$WINDOW_ROOT/$id"
  dir=$WINDOW_ROOT/$id
  { printf 'started=%s\n' "$(date -u +%FT%TZ)"; printf '%s\n' "$baseline"; } > "$dir/window.start.tmp"
  sync -f "$dir/window.start.tmp"; mv "$dir/window.start.tmp" "$dir/window.start"; sync -f "$dir"
  printf '%s\n' "$id" > "$WINDOW_ROOT/active-window.tmp"
  sync -f "$WINDOW_ROOT/active-window.tmp"
  mv "$WINDOW_ROOT/active-window.tmp" "$WINDOW_ROOT/active-window"; sync -f "$WINDOW_ROOT"
  "$SYSTEMD_RUN_BIN" --quiet --unit="$WINDOW_UNIT" --collect -p "RuntimeMaxSec=$WINDOW_SECONDS" -- bash -c 'exec 7<>"$1" 9<>"$2"; flock -n 7 && flock -n 9 && exec sleep infinity' _ "$LOCK_CANDIDATE" "$LOCK_HARDENING"
  [[ $(unit_state "$WINDOW_UNIT") == active ]] || fail 'window holder not active; inspect before recovery'
  install -d -m 0700 "$(dirname "$HOLD_FILE")"; : > "$HOLD_FILE"
  "$SYSTEMCTL_BIN" stop t3code-recovery.service
  [[ $(unit_state t3code-recovery) == inactive ]] || fail 'recovery did not stop'
  ;;
 end-no-activation)
  preflight
  lock_window
  preflight
  read_active
  [[ ! -e $dir/complete.started ]] || fail 'switch intent exists'
  shopt -s nullglob dotglob
  intents=("$dir"/effect-intent.*)
  (( ${#intents[@]} == 0 )) || fail 'effect intent exists'
  baseline=$(snapshot) || fail 'state unknown'
  [[ $(tail -n +2 "$dir/window.start") == "$baseline" ]] || fail 'state changed'
  [[ ! -e $STATE_DIR/failed-candidate ]] || fail 'failed candidate exists'
  [[ $(unit_state "$WINDOW_UNIT") == active && -f $HOLD_FILE ]] || fail 'window state unknown'
  "$SYSTEMCTL_BIN" stop "$WINDOW_UNIT.service"
  "$SYSTEMCTL_BIN" start t3code-recovery.service
  [[ $(unit_state t3code-recovery) == active ]] || fail 'recovery not active'
  rm "$HOLD_FILE"
  rm "$WINDOW_ROOT/active-window"; sync -f "$WINDOW_ROOT"
  ;;
 *) echo 'usage: release-window preflight|start WINDOW_ID|end-no-activation' >&2; exit 2 ;;
esac
