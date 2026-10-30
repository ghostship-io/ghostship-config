#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
# shellcheck disable=SC1090
source "${WINDOW_INTENT_HELPER:?}"
: "${STATE_DIR:?}" "${SYSTEMCTL_BIN:?}" "${PODMAN_BIN:?}" "${PODMAN_TARGET:?}" "${WINDOW_UNIT:?}" "${HOLD_FILE:?}" "${LOCK_CANDIDATE:?}" "${LOCK_HARDENING:?}" "${PROFILE:?}" "${SYSTEMD_RUN_BIN:?}"
window_root
fail() { echo "STOP: $*" >&2; exit 1; }
unit_state() { "$SYSTEMCTL_BIN" show "$1.service" -p ActiveState --value; }
preflight_core() {
  [[ -f $STATE_DIR/deploy.lock && ! -L $STATE_DIR/deploy.lock ]] || fail 'missing deploy lock'
  [[ -f $STATE_DIR/applied && -f $STATE_DIR/desired ]] || fail 'deployment state missing'
  flock -n -x "$STATE_DIR/deploy.lock" true || fail 'deploy writer holds lock'
  [[ $(unit_state ghostship-t3code-deploy) == inactive ]] || fail 'deploy service active or failed'
  [[ $(unit_state t3code-podman-candidate) == inactive ]] || fail 'candidate service active or failed'
  [[ $("$PODMAN_BIN" inspect "$PODMAN_TARGET" --format '{{.State.Health.Status}}') == healthy ]] || fail 'target unhealthy or unknown'
}
candidate_locks_free() {
  [[ -f $LOCK_CANDIDATE && ! -L $LOCK_CANDIDATE && -f $LOCK_HARDENING && ! -L $LOCK_HARDENING ]] || fail 'candidate lock missing'
  if ! flock -n -x "$LOCK_CANDIDATE" true || ! flock -n -x "$LOCK_HARDENING" true; then fail 'candidate lock held'; fi
}
complete_locks_free() {
  local f
  shopt -s nullglob
  for f in "$WINDOW_ROOT"/*/complete.lock; do
    [[ -f $f && ! -L $f ]] || fail 'invalid complete lock'
    flock -n -x "$f" true || fail 'complete writer holds lock'
  done
}
preflight() {
  preflight_core
  [[ ! -e $HOLD_FILE && ! -L $HOLD_FILE ]] || fail 'recovery hold already exists'
  if [[ -e $WINDOW_ROOT || -L $WINDOW_ROOT ]]; then
    [[ -d $WINDOW_ROOT && ! -L $WINDOW_ROOT && -f $WINDOW_ROOT/window.lock && ! -L $WINDOW_ROOT/window.lock ]] || fail 'window root or lock invalid'
    flock -n -x "$WINDOW_ROOT/window.lock" true || fail 'window lock held'
  else
    [[ -d $(dirname "$WINDOW_ROOT") ]] || fail 'window root parent missing'
  fi
  candidate_locks_free
  complete_locks_free
}
holder_ready() {
  local pid current
  [[ -f $dir/holder.ready && ! -L $dir/holder.ready ]] || return 1
  read -r pid < "$dir/holder.ready"
  [[ $pid =~ ^[1-9][0-9]*$ ]] || return 1
  [[ $(unit_state "$WINDOW_UNIT") == active ]] || return 1
  current=$("$SYSTEMCTL_BIN" show "$WINDOW_UNIT.service" -p MainPID --value) || return 1
  [[ $current == "$pid" && /proc/$pid/fd/7 -ef $LOCK_CANDIDATE && /proc/$pid/fd/9 -ef $LOCK_HARDENING ]] || return 1
  ! flock -n -s "$LOCK_CANDIDATE" true && ! flock -n -s "$LOCK_HARDENING" true
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
  if [[ ! -e $WINDOW_ROOT && ! -L $WINDOW_ROOT ]]; then
    : "${WINDOW_BOOTSTRAP:?}"
    bash "$WINDOW_BOOTSTRAP"
  fi
  lock_window
  preflight_core
  candidate_locks_free
  complete_locks_free
  [[ ! -e $HOLD_FILE && ! -L $HOLD_FILE ]] || fail 'recovery hold already exists'
  [[ $(unit_state t3code-recovery) == active ]] || fail 'recovery is not active'
  [[ ! -e $WINDOW_ROOT/active-window && ! -e $WINDOW_ROOT/$id ]] || fail 'window already exists or active'
  [[ $(unit_state "$WINDOW_UNIT") == inactive ]] || fail 'window holder not inactive'
  exec 6<"$LOCK_CANDIDATE" 7<"$LOCK_HARDENING"
  flock -n -x 6 || fail 'candidate lock held'
  flock -n -x 7 || fail 'hardening lock held'
  acquired_at=$(date -u +%FT%TZ)
  baseline=$(snapshot) || fail 'baseline unknown'
  mkdir -m 0700 "$WINDOW_ROOT/$id"
  dir=$WINDOW_ROOT/$id
  { printf 'started=%s acquired_by=%s\n' "$acquired_at" "$$"; printf '%s\n' "$baseline"; } > "$dir/window.start.tmp"
  sync -f "$dir/window.start.tmp"; mv "$dir/window.start.tmp" "$dir/window.start"; sync -f "$dir"
  printf '%s\n' "$id" > "$WINDOW_ROOT/active-window.tmp"
  sync -f "$WINDOW_ROOT/active-window.tmp"
  mv "$WINDOW_ROOT/active-window.tmp" "$WINDOW_ROOT/active-window"; sync -f "$WINDOW_ROOT"
  # Arguments are expanded by the holder shell.
  # shellcheck disable=SC2016
  "$SYSTEMD_RUN_BIN" --quiet --unit="$WINDOW_UNIT" --collect -p "RuntimeMaxSec=$WINDOW_SECONDS" -- bash -c 'set -e; exec 7<>"$1" 9<>"$2"; flock -w 10 7; flock -w 10 9; printf "%s\n" "$$" > "$3/holder.ready.tmp"; mv "$3/holder.ready.tmp" "$3/holder.ready"; exec sleep infinity' _ "$LOCK_CANDIDATE" "$LOCK_HARDENING" "$dir"
  exec 6<&- 7<&-
  for _ in {1..100}; do [[ -f $dir/holder.ready ]] && break; sleep 0.05; done
  holder_ready || fail 'window holder has not acquired both locks'
  read -r holder_pid < "$dir/holder.ready"
  { printf 'started=%s acquired_by=%s\n' "$acquired_at" "$$"; printf 'holder_pid=%s held_at=%s\n' "$holder_pid" "$(date -u +%FT%TZ)"; printf '%s\n' "$baseline"; } > "$dir/window.start.tmp"
  sync -f "$dir/window.start.tmp"; mv "$dir/window.start.tmp" "$dir/window.start"; sync -f "$dir"
  install -d -m 0700 "$(dirname "$HOLD_FILE")"; : > "$HOLD_FILE"
  holder_ready || fail 'window holder lost its locks; recovery not stopped'
  "$SYSTEMCTL_BIN" stop t3code-recovery.service
  [[ $(unit_state t3code-recovery) == inactive ]] || fail 'recovery did not stop'
  ;;
 switch)
  shift
  [[ ${1:-} == -- && $# -ge 2 ]] || fail 'usage: switch -- COMMAND [ARG...]'
  shift
  preflight_core
  # Retain the shared lock through the switch and all its effects. Announcing
  # before any effect is deliberately conservative if later checks fail.
  announce_intent switch
  read_active
  if [[ ! -f $HOLD_FILE ]] || ! holder_ready; then fail 'window state unknown'; fi
  exec 9>"$dir/complete.lock"
  flock -n -x 9 || fail 'switch already running'
  [[ ! -e $dir/complete.started ]] || fail 'switch already started; outcome unknown'
  printf '%s\n' "$(date -u +%FT%TZ)" > "$dir/complete.started"
  sync -f "$dir/complete.started"; sync -f "$dir"
  "$@"
  ;;
 end-no-activation)
  preflight_core
  lock_window
  preflight_core
  read_active
  [[ ! -e $dir/complete.started ]] || fail 'switch intent exists'
  shopt -s nullglob dotglob
  intents=("$dir"/effect-intent.*)
  (( ${#intents[@]} == 0 )) || fail 'effect intent exists'
  baseline=$(snapshot) || fail 'state unknown'
  [[ $(tail -n +3 "$dir/window.start") == "$baseline" ]] || fail 'state changed'
  [[ ! -e $STATE_DIR/failed-candidate ]] || fail 'failed candidate exists'
  if [[ ! -f $HOLD_FILE ]] || ! holder_ready; then fail 'window state unknown'; fi
  "$SYSTEMCTL_BIN" stop "$WINDOW_UNIT.service"
  "$SYSTEMCTL_BIN" start t3code-recovery.service
  [[ $(unit_state t3code-recovery) == active ]] || fail 'recovery not active'
  rm "$HOLD_FILE"
  rm "$WINDOW_ROOT/active-window"; sync -f "$WINDOW_ROOT"
  ;;
 *) echo 'usage: release-window preflight|start WINDOW_ID|switch -- COMMAND [ARG...]|end-no-activation' >&2; exit 2 ;;
esac
