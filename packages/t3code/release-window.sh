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
  case $(unit_state ghostship-t3code-deploy) in inactive|failed) ;; *) fail 'deploy service active or unknown' ;; esac
  case $(unit_state t3code-podman-candidate) in inactive|failed) ;; *) fail 'candidate service active or unknown' ;; esac
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
legacy_preflight() {
  : "${LEGACY_DIR:?}" "${LEGACY_UNIT:?}"
  [[ $LEGACY_DIR == /* && -d $LEGACY_DIR && ! -L $LEGACY_DIR ]] || fail 'legacy evidence directory invalid'
  [[ -f $HOLD_FILE && ! -L $HOLD_FILE ]] || fail 'legacy recovery inhibit missing'
  [[ -f $LEGACY_DIR/window.opened && ! -L $LEGACY_DIR/window.opened && -f $LEGACY_DIR/window.until && ! -L $LEGACY_DIR/window.until ]] || fail 'legacy window evidence missing'
  local opened until
  opened=$(cat "$LEGACY_DIR/window.opened"); until=$(cat "$LEGACY_DIR/window.until")
  [[ $opened =~ ^[0-9]+$ && $until =~ ^[0-9]+$ ]] || fail 'legacy window timing unknown'
  (( until >= opened && $(date +%s) >= until )) || fail 'legacy window has not expired'
  case $(unit_state "$LEGACY_UNIT") in inactive|failed) ;; *) fail 'legacy holder active or unknown' ;; esac
  [[ -f $LEGACY_DIR/complete.lock && ! -L $LEGACY_DIR/complete.lock ]] || fail 'legacy complete lock missing'
  flock -n -x "$LEGACY_DIR/complete.lock" true || fail 'legacy complete writer active'
  [[ ! -L $LEGACY_DIR/complete.started ]] || fail 'legacy switch marker invalid'
}
preflight() {
  local mode=${1:-}
  [[ -z $mode || $mode == --adopt-inhibit ]] || fail 'invalid preflight option'
  preflight_core
  if [[ $mode == --adopt-inhibit ]]; then
    legacy_preflight
  else
    [[ ! -e $HOLD_FILE && ! -L $HOLD_FILE ]] || fail 'recovery hold already exists'
  fi
  [[ ! -e $STATE_DIR/recovery-unknown.json && ! -L $STATE_DIR/recovery-unknown.json ]] || fail 'recorded UNKNOWN requires investigation'
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
lock_window() { exec 8<"$WINDOW_ROOT/window.lock"; flock -n -x 8 || fail 'window writer active'; }
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
serving_identity() {
  local before after cid image started pid entered
  before=$("$PODMAN_BIN" inspect "$PODMAN_TARGET" --format '{{.Id}} {{.Image}} {{.State.StartedAt}}') || return 1
  read -r cid image started <<< "$before"
  [[ $cid =~ ^[0-9a-f]{64}$ && ${image#sha256:} =~ ^[0-9a-f]{64}$ && -n $started && $before == "$cid $image $started" ]] || return 1
  pid=$("$PODMAN_BIN" exec "$PODMAN_TARGET" systemctl show t3code-server.service -p MainPID --value) || return 1
  entered=$("$PODMAN_BIN" exec "$PODMAN_TARGET" systemctl show t3code-server.service -p ActiveEnterTimestampMonotonic --value) || return 1
  [[ $pid =~ ^[1-9][0-9]*$ && $entered =~ ^[1-9][0-9]*$ ]] || return 1
  after=$("$PODMAN_BIN" inspect "$PODMAN_TARGET" --format '{{.Id}} {{.Image}} {{.State.StartedAt}}') || return 1
  [[ $before == "$after" ]] || return 1
  printf '%s\n%s %s\n' "$before" "$pid" "$entered"
}
lock_managed_tools() {
  : "${HOME_DIR:?}"
  local tool="$HOME_DIR/.local/state/t3code-tool-update/tool-update.lock"
  local refresh="$HOME_DIR/.local/state/t3code-shared-agents/refresh.lock"
  local t3="$HOME_DIR/.local/share/t3code-tools/t3/update.lock"
  [[ -f $tool && ! -L $tool && -f $refresh && ! -L $refresh && -f $t3 && ! -L $t3 ]] || fail 'managed writer locks missing'
  exec 4<"$tool"; flock -n -x 4 || fail 'tool maintenance writer active'
  exec 5<"$refresh"; flock -n -x 5 || fail 'agent refresh writer active'
  exec 7<"$t3"; flock -n -x 7 || fail 'T3 update writer active'
}
no_pending_restart() {
  : "${HOME_DIR:?}"
  local f
  for f in "$STATE_DIR/restart.pending" "$HOME_DIR/.local/state/t3code-tool-update/restart.pending" \
    "$HOME_DIR/.local/state/t3code-tool-update/update-deferred.pending" "$HOME_DIR/.local/state/t3code-tool-update/hold" \
    "$HOME_DIR/.local/share/t3code-tools/t3/activation.pending"; do
    [[ ! -e $f && ! -L $f ]] || fail 'pending restart or maintenance marker'
  done
  # shellcheck disable=SC2016
  "$PODMAN_BIN" exec "$PODMAN_TARGET" sh -c \
    'for f in /run/t3code-tool-update/restart.pending /run/t3code-tool-update/update-deferred.pending /run/t3code-tool-update/hold /run/t3code-tool-update/maintenance; do [ ! -e "$f" ] && [ ! -L "$f" ] || exit 1; done' || fail 'container maintenance state unknown or pending'
}
serving_matches_start() {
  [[ -f $dir/serving.before && ! -L $dir/serving.before ]] || fail 'serving identity baseline missing'
  local current
  current=$(serving_identity) || fail 'serving identity unknown'
  [[ $current == "$(cat "$dir/serving.before")" ]] || fail 'serving T3 changed since window start'
  [[ $("$PODMAN_BIN" inspect "$PODMAN_TARGET" --format '{{.State.Health.Status}}') == healthy ]] || fail 'serving container unhealthy'
  "$PODMAN_BIN" exec "$PODMAN_TARGET" systemctl is-active --quiet t3code-server.service || fail 'serving server inactive'
  lock_managed_tools
  no_pending_restart
}
known_good_receipt() {
  : "${CANDIDATE_HOME_TARGET:?}" "${JQ_BIN:?}"
  local cid image started revision tooling inode receipt
  read -r cid image started < "$dir/serving.before"
  image=${image#sha256:}
  tooling=$("$PODMAN_BIN" exec "$PODMAN_TARGET" readlink -f "$CANDIDATE_HOME_TARGET/.local/state/ghostship-t3-tools/current") || return 2
  revision=$("$PODMAN_BIN" exec "$PODMAN_TARGET" cat "$CANDIDATE_HOME_TARGET/.local/state/t3code-shared-agents/release.json" | "$JQ_BIN" -er '.revision | select(type == "string" and length > 0)') || return 2
  inode=$("$PODMAN_BIN" exec "$PODMAN_TARGET" stat -Lc '%i' /run/secrets/t3code.env) || return 2
  [[ -n $tooling && $inode =~ ^[0-9]+$ ]] || return 2
  [[ ! -L $STATE_DIR/receipts ]] || return 2
  [[ ! -e $STATE_DIR/receipts || -d $STATE_DIR/receipts ]] || return 2
  shopt -s nullglob
  for receipt in "$STATE_DIR"/receipts/*.json; do
    [[ -f $receipt && ! -L $receipt && -r $receipt ]] || return 2
    # shellcheck disable=SC2016
    if "$JQ_BIN" -e --arg i "$image" --arg a "$revision" --arg p "$tooling" --arg s "$inode" '
      (.image_id | sub("^sha256:"; "")) == $i and
      (.deployment_id | type == "string" and length > 0) and
      (.candidate_name | type == "string" and startswith("t3code-candidate-")) and
      .live_before != null and .live_before == .live_after and .agent_revision == $a and
      .agent_path == $p and .provider_secret_inode == $s and
      ([.checks.app_ready,.checks.provider_turn,.checks.agent_cli,.checks.skills,.checks.desktop_transport] | all(. == true))' "$receipt" >/dev/null 2>&1; then
      printf '%s\n' "$receipt"
      return 0
    fi
  done
  return 1
}
require_matching_receipt_and_alias() {
  : "${ACCEPTED_IMAGE_REF:?}"
  local status=0 cid image started alias hash marker="$dir/alias-restore.started"
  matched_receipt=$(known_good_receipt) || status=$?
  [[ $status == 0 ]] || fail 'no exact known-good receipt or receipt state unknown'
  read -r cid image started < "$dir/serving.before"
  image=${image#sha256:}
  alias=$("$PODMAN_BIN" image inspect "$ACCEPTED_IMAGE_REF" --format '{{.Id}}') || fail 'accepted image alias unknown'
  [[ ${alias#sha256:} != "$image" ]] || return 0
  [[ ${alias#sha256:} =~ ^[0-9a-f]{64}$ ]] || fail 'accepted image alias invalid'
  hash=$(sha256sum < "$matched_receipt" | cut -d ' ' -f1)
  if [[ -e $marker || -L $marker ]]; then
    [[ -f $marker && ! -L $marker ]] || fail 'UNKNOWN: alias restore evidence invalid'
    local previous_target previous_alias previous_hash
    read -r previous_target previous_alias previous_hash < "$marker" || fail 'UNKNOWN: alias restore evidence unreadable'
    [[ $previous_target == "$image" && $previous_alias == "${alias#sha256:}" && $previous_hash == "$hash" ]] || fail 'UNKNOWN: alias restore state changed'
    # Reapplying the same receipt-bound tag is idempotent; the previous effect
    # stays UNKNOWN until the alias is read back as the exact target.
  else
    printf '%s %s %s\n' "$image" "${alias#sha256:}" "$hash" > "$marker.tmp"
    chmod 0600 "$marker.tmp"; sync -f "$marker.tmp"; mv "$marker.tmp" "$marker"; sync -f "$dir"
  fi
  # The exact existing receipt above authorizes this alias move. The serving
  # container is not restarted; a lost tag acknowledgement is read back.
  "$PODMAN_BIN" tag "sha256:$image" "$ACCEPTED_IMAGE_REF" || true
  alias=$("$PODMAN_BIN" image inspect "$ACCEPTED_IMAGE_REF" --format '{{.Id}}') || fail 'UNKNOWN: alias restore readback unavailable'
  [[ ${alias#sha256:} == "$image" ]] || fail 'UNKNOWN: alias restore did not reconcile'
}
record_known_good() {
  local destination=$1 hash desired applied
  hash=$(sha256sum < "$matched_receipt" | cut -d ' ' -f1)
  desired=$(cat "$STATE_DIR/desired"); applied=$(cat "$STATE_DIR/applied")
  # shellcheck disable=SC2016
  "$JQ_BIN" -cn --arg desired "$desired" --arg applied "$applied" --arg receipt "$(basename "$matched_receipt")" --arg hash "$hash" --arg at "$(date -u +%FT%TZ)" \
    '{state:"KNOWN_GOOD_SERVING",desired:$desired,applied:$applied,receipt:$receipt,receipt_sha256:$hash,at:$at}' > "$destination.tmp"
  chmod 0600 "$destination.tmp"; sync -f "$destination.tmp"; mv "$destination.tmp" "$destination"; sync -f "$(dirname "$destination")"
}
post_verify() {
  : "${EXPECTED_DEPLOYMENT:?}" "${EXPECTED_IMAGE:?}" "${EXPECTED_AGENT_REVISION:?}" "${EXPECTED_TOOLING_PATH:?}" "${PROVIDER_SECRETS_FILE:?}" "${CURRENT_SYSTEM:?}" "${EXPECTED_SYSTEM:?}" "${CANDIDATE_HOME_TARGET:?}" "${JQ_BIN:?}" "${ACCEPTED_IMAGE_REF:?}"
  [[ $EXPECTED_DEPLOYMENT =~ ^[0-9a-f]{64}$ && $EXPECTED_IMAGE =~ ^[0-9a-f]{64}$ ]] || fail 'invalid expected identity'
  [[ -f $dir/complete.started && -f $dir/complete.lock && ! -L $dir/complete.lock ]] || fail 'switch evidence missing'
  exec 6<"$dir/complete.lock"; flock -n -x 6 || fail 'switch outcome unknown: writer active'
  exec 9<"$STATE_DIR/deploy.lock"; flock -n -x 9 || fail 'deploy outcome unknown: writer active'
  [[ $(unit_state ghostship-t3code-deploy) == inactive && $(unit_state t3code-podman-candidate) == inactive ]] || fail 'deploy or candidate service not inactive'
  [[ $("$SYSTEMCTL_BIN" show ghostship-t3code-deploy.service -p Result --value) == success ]] || fail 'deploy service result not success'
  [[ ! -e $STATE_DIR/failed-candidate && ! -L $STATE_DIR/failed-candidate ]] || fail 'failed candidate exists'
  [[ $(cat "$STATE_DIR/applied") == "$EXPECTED_DEPLOYMENT" && $(cat "$STATE_DIR/desired") == "$EXPECTED_DEPLOYMENT" ]] || fail 'deployment state not reconciled'
  [[ $(readlink -f "$CURRENT_SYSTEM") == "$EXPECTED_SYSTEM" && $(readlink -f "$PROFILE") == "$EXPECTED_SYSTEM" ]] || fail 'system generation not reconciled'
  local receipt="$STATE_DIR/receipts/$EXPECTED_DEPLOYMENT.json" attempt="$STATE_DIR/attempts/$EXPECTED_DEPLOYMENT.json" inode image switch_at switch_ms
  read -r switch_at switch_ms < "$dir/complete.started" || fail 'switch start evidence malformed'
  [[ $switch_at =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$ && $switch_ms =~ ^[0-9]+$ ]] || fail 'switch start time unknown'
  [[ -f $receipt && ! -L $receipt && -f $attempt && ! -L $attempt && -f $PROVIDER_SECRETS_FILE ]] || fail 'receipt or attempt missing'
  inode=$(stat -Lc %i "$PROVIDER_SECRETS_FILE") || fail 'provider secret identity unknown'
  # shellcheck disable=SC2016
  "$JQ_BIN" -e --arg d "$EXPECTED_DEPLOYMENT" --arg i "$EXPECTED_IMAGE" --arg a "$EXPECTED_AGENT_REVISION" --arg p "$EXPECTED_TOOLING_PATH" --arg s "$inode" '
    .deployment_id == $d and (.image_id | sub("^sha256:"; "")) == $i and
    (.candidate_name | type == "string" and startswith("t3code-candidate-")) and
    .live_before != null and .live_before == .live_after and .agent_revision == $a and
    .agent_path == $p and .provider_secret_inode == $s and
    ([.checks.app_ready,.checks.provider_turn,.checks.agent_cli,.checks.skills,.checks.desktop_transport] | all(. == true))' "$receipt" >/dev/null || fail 'exact-image receipt invalid'
  # shellcheck disable=SC2016
  "$JQ_BIN" -e --arg d "$EXPECTED_DEPLOYMENT" --argjson min "$switch_ms" '.deployment_id == $d and .exit_code == 0 and (.status == null) and (.outcome == null) and (.started_at_ms | type == "number" and . >= $min)' "$attempt" >/dev/null || fail 'deployment attempt failed or unknown'
  image=$("$PODMAN_BIN" inspect "$PODMAN_TARGET" --format '{{.Image}}') || fail 'live image unknown'
  [[ ${image#sha256:} == "$EXPECTED_IMAGE" ]] || fail 'live image differs from receipt'
  image=$("$PODMAN_BIN" image inspect "$ACCEPTED_IMAGE_REF" --format '{{.Id}}') || fail 'accepted alias unknown'
  [[ ${image#sha256:} == "$EXPECTED_IMAGE" ]] || fail 'accepted alias differs from receipt'
  [[ $("$PODMAN_BIN" inspect "$PODMAN_TARGET" --format '{{.State.Health.Status}}') == healthy ]] || fail 'live container unhealthy'
  "$PODMAN_BIN" exec "$PODMAN_TARGET" systemctl is-active --quiet t3code-server.service || fail 'server inactive'
  "$PODMAN_BIN" exec "$PODMAN_TARGET" curl -fsS --max-time 5 http://127.0.0.1:3773/ >/dev/null || fail 'server unresponsive'
  [[ $("$PODMAN_BIN" exec "$PODMAN_TARGET" readlink -f "$CANDIDATE_HOME_TARGET/.local/state/ghostship-t3-tools/current") == "$EXPECTED_TOOLING_PATH" ]] || fail 'live tooling differs from receipt'
  [[ $("$PODMAN_BIN" exec "$PODMAN_TARGET" stat -Lc '%i' /run/secrets/t3code.env) == "$inode" ]] || fail 'live secret differs from receipt'
  lock_managed_tools
  no_pending_restart
}
case ${1:-} in
 preflight)
  [[ $# -le 2 ]] || fail 'usage: preflight [--adopt-inhibit]'
  preflight "${2:-}"
  printf 'PASS preflight\n'
  ;;
 start)
  adopt=0
  if [[ ${2:-} == --adopt-inhibit ]]; then adopt=1; shift; fi
  [[ $# == 2 ]] || fail 'usage: start [--adopt-inhibit] WINDOW_ID'
  id=$2; window_id_valid "$id" || fail 'invalid window id'
  : "${WINDOW_SECONDS:?}"
  if (( adopt )); then preflight --adopt-inhibit; else preflight; fi
  if [[ ! -e $WINDOW_ROOT && ! -L $WINDOW_ROOT ]]; then
    : "${WINDOW_BOOTSTRAP:?}"
    bash "$WINDOW_BOOTSTRAP"
  fi
  lock_window
  preflight_core
  candidate_locks_free
  complete_locks_free
  if (( adopt )); then
    legacy_preflight
    exec 3<"$LEGACY_DIR/complete.lock"; flock -n -x 3 || fail 'legacy complete writer active'
  else
    [[ ! -e $HOLD_FILE && ! -L $HOLD_FILE ]] || fail 'recovery hold already exists'
  fi
  [[ $(unit_state t3code-recovery) == active ]] || fail 'recovery is not active'
  [[ ! -e $WINDOW_ROOT/active-window && ! -e $WINDOW_ROOT/$id ]] || fail 'window already exists or active'
  [[ $(unit_state "$WINDOW_UNIT") == inactive ]] || fail 'window holder not inactive'
  exec 6<"$LOCK_CANDIDATE" 7<"$LOCK_HARDENING"
  flock -n -x 6 || fail 'candidate lock held'
  flock -n -x 7 || fail 'hardening lock held'
  acquired_at=$(date -u +%FT%TZ)
  baseline=$(snapshot) || fail 'baseline unknown'
  serving=$(serving_identity) || fail 'serving identity unknown'
  mkdir -m 0700 "$WINDOW_ROOT/$id"
  dir=$WINDOW_ROOT/$id
  if (( adopt )); then
    started=absent
    if [[ -e $LEGACY_DIR/complete.started ]]; then
      [[ -f $LEGACY_DIR/complete.started && ! -L $LEGACY_DIR/complete.started ]] || fail 'legacy switch marker invalid'
      started=present
    fi
    printf 'opened=%s until=%s complete_started=%s\n' "$(cat "$LEGACY_DIR/window.opened")" "$(cat "$LEGACY_DIR/window.until")" "$started" > "$dir/legacy.adopted"
    sync -f "$dir/legacy.adopted"
  fi
  printf '%s\n' "$serving" > "$dir/serving.before"
  sync -f "$dir/serving.before"
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
  if (( ! adopt )); then install -d -m 0700 "$(dirname "$HOLD_FILE")"; : > "$HOLD_FILE"; fi
  holder_ready || fail 'window holder lost its locks; recovery not stopped'
  "$SYSTEMCTL_BIN" stop t3code-recovery.service
  [[ $(unit_state t3code-recovery) == inactive ]] || fail 'recovery did not stop'
  if (( adopt )); then printf 'PASS window started id=%s mode=adopted-inhibit\n' "$id"; else printf 'PASS window started id=%s mode=new\n' "$id"; fi
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
  if [[ ! -f $HOLD_FILE || -L $HOLD_FILE ]] || ! holder_ready; then fail 'window state unknown'; fi
  exec 9>"$dir/complete.lock"
  flock -n -x 9 || fail 'switch already running'
  [[ ! -e $dir/complete.started ]] || fail 'switch already started; outcome unknown'
  printf '%s %s\n' "$(date -u +%FT%TZ)" "$(date +%s%3N)" > "$dir/complete.started"
  sync -f "$dir/complete.started"; sync -f "$dir"
  switch_rc=0
  "$@" || switch_rc=$?
  printf 'exit_code=%s\n' "$switch_rc" > "$dir/switch.result.tmp"
  sync -f "$dir/switch.result.tmp"; mv "$dir/switch.result.tmp" "$dir/switch.result"; sync -f "$dir"
  exit "$switch_rc"
  ;;
 post)
  [[ -f $WINDOW_ROOT/window.lock ]] || fail 'window lock missing'
  exec 8<"$WINDOW_ROOT/window.lock"; flock -n -s 8 || fail 'window transition in progress'
  read_active
  if [[ ! -f $HOLD_FILE || -L $HOLD_FILE ]] || ! holder_ready; then fail 'window state unknown'; fi
  post_verify
  printf 'PASS post deployment=%s image=%s\n' "$EXPECTED_DEPLOYMENT" "$EXPECTED_IMAGE"
  ;;
 end-post)
  [[ $# -le 2 ]] || fail 'usage: end-post [WINDOW_ID]'
  lock_window
  if [[ ! -e $WINDOW_ROOT/active-window && ! -L $WINDOW_ROOT/active-window ]]; then
    [[ $# == 2 ]] || fail 'missing active window; provide the recorded window ID'
    id=$2; window_id_valid "$id" || fail 'invalid window ID'
    dir=$WINDOW_ROOT/$id
    [[ -f $dir/post.verified && ! -L $dir/post.verified && ! -e $HOLD_FILE && $(unit_state "$WINDOW_UNIT") == inactive ]] || fail 'completed post state unknown'
    candidate_locks_free
    post_verify
    printf 'PASS post; window already released deployment=%s image=%s\n' "$EXPECTED_DEPLOYMENT" "$EXPECTED_IMAGE"
    exit 0
  fi
  read_active
  [[ $# == 1 || $2 == "$id" ]] || fail 'window ID does not match'
  case $(unit_state "$WINDOW_UNIT") in
    active) if [[ ! -f $HOLD_FILE || -L $HOLD_FILE ]] || ! holder_ready; then fail 'window state unknown'; fi ;;
    inactive) [[ -f $dir/post.verified && ! -L $dir/post.verified ]] || fail 'holder absent without post evidence'; candidate_locks_free ;;
    *) fail 'window holder state unknown' ;;
  esac
  post_verify
  # Post evidence is not a receipt: it references the existing receipt only.
  # shellcheck disable=SC2016
  "$JQ_BIN" -cn --arg d "$EXPECTED_DEPLOYMENT" --arg i "$EXPECTED_IMAGE" --arg at "$(date -u +%FT%TZ)" '{deployment_id:$d,image_id:$i,verified_at:$at}' > "$dir/post.verified.tmp"
  chmod 0600 "$dir/post.verified.tmp"; sync -f "$dir/post.verified.tmp"; mv "$dir/post.verified.tmp" "$dir/post.verified"; sync -f "$dir"
  "$SYSTEMCTL_BIN" start t3code-recovery.service
  [[ $(unit_state t3code-recovery) == active ]] || fail 'recovery not active; inhibit retained'
  if [[ $(unit_state "$WINDOW_UNIT") == active ]]; then
    holder_ready || fail 'holder lost before release; inhibit retained'
    "$SYSTEMCTL_BIN" stop "$WINDOW_UNIT.service"
  fi
  [[ $(unit_state "$WINDOW_UNIT") == inactive ]] || fail 'holder stop outcome unknown'
  [[ ! -L $HOLD_FILE ]] || fail 'recovery hold is a symlink'
  [[ ! -e $HOLD_FILE ]] || rm "$HOLD_FILE"
  rm "$WINDOW_ROOT/active-window"; sync -f "$WINDOW_ROOT"
  printf 'PASS post and window released deployment=%s image=%s\n' "$EXPECTED_DEPLOYMENT" "$EXPECTED_IMAGE"
  ;;
 rollback)
  : "${JQ_BIN:?}"
  [[ $# -le 2 ]] || fail 'usage: rollback [WINDOW_ID]'
  lock_window
  already_released=0
  if [[ ! -e $WINDOW_ROOT/active-window && ! -L $WINDOW_ROOT/active-window ]]; then
    [[ $# == 2 ]] || fail 'missing active window; provide the recorded window ID'
    id=$2; window_id_valid "$id" || fail 'invalid window ID'
    dir=$WINDOW_ROOT/$id
    [[ -f $dir/known-good.json && ! -L $dir/known-good.json && ! -e $HOLD_FILE && ! -L $HOLD_FILE && $(unit_state "$WINDOW_UNIT") == inactive ]] || fail 'completed rollback state unknown'
    candidate_locks_free
    already_released=1
  else
    read_active
    [[ $# == 1 || $2 == "$id" ]] || fail 'window ID does not match'
    case $(unit_state "$WINDOW_UNIT") in
      active) if [[ ! -f $HOLD_FILE || -L $HOLD_FILE ]] || ! holder_ready; then fail 'window state unknown'; fi ;;
      inactive) [[ -f $dir/known-good.json && ! -L $dir/known-good.json ]] || fail 'holder absent without known-good evidence'; candidate_locks_free ;;
      *) fail 'window holder state unknown' ;;
    esac
  fi
  [[ -f $STATE_DIR/deploy.lock && ! -L $STATE_DIR/deploy.lock ]] || fail 'deploy lock missing'
  exec 9<"$STATE_DIR/deploy.lock"; flock -n -x 9 || fail 'deploy writer active'
  case $(unit_state ghostship-t3code-deploy) in inactive|failed) ;; *) fail 'deploy service active or unknown' ;; esac
  case $(unit_state t3code-podman-candidate) in inactive|failed) ;; *) fail 'candidate service active or unknown' ;; esac
  serving_matches_start
  require_matching_receipt_and_alias
  if (( already_released )); then
    printf '%s\n' 'PASS known-good serving identity and existing receipt; window already released.'
    exit 0
  fi
  record_known_good "$dir/known-good.json"
  "$SYSTEMCTL_BIN" start t3code-recovery.service
  [[ $(unit_state t3code-recovery) == active ]] || fail 'recovery not active; inhibit retained'
  if [[ $(unit_state "$WINDOW_UNIT") == active ]]; then
    holder_ready || fail 'holder lost before release; inhibit retained'
    "$SYSTEMCTL_BIN" stop "$WINDOW_UNIT.service"
  fi
  [[ $(unit_state "$WINDOW_UNIT") == inactive ]] || fail 'holder stop outcome unknown'
  [[ ! -L $HOLD_FILE ]] || fail 'recovery hold is a symlink'
  [[ ! -e $HOLD_FILE ]] || rm "$HOLD_FILE"
  rm "$WINDOW_ROOT/active-window"; sync -f "$WINDOW_ROOT"
  printf '%s\n' 'PASS known-good serving identity and existing receipt; window released without T3 restart.'
  ;;
 resolve-unknown)
  : "${JQ_BIN:?}"
  [[ -f $WINDOW_ROOT/window.lock && -f $STATE_DIR/recovery-unknown.json && ! -L $STATE_DIR/recovery-unknown.json ]] || fail 'UNKNOWN record missing'
  lock_window
  [[ ! -e $WINDOW_ROOT/active-window && ! -L $WINDOW_ROOT/active-window ]] || fail 'window still active'
  [[ $(unit_state "$WINDOW_UNIT") == inactive ]] || fail 'window holder still active'
  id=$("$JQ_BIN" -er 'select(.state == "UNKNOWN" and .recovery_inhibit == "retained") | .window' "$STATE_DIR/recovery-unknown.json") || fail 'UNKNOWN record invalid'
  window_id_valid "$id" || fail 'UNKNOWN window identity invalid'
  dir=$WINDOW_ROOT/$id
  [[ -d $dir && ! -L $dir && -f $HOLD_FILE && ! -L $HOLD_FILE ]] || fail 'UNKNOWN inhibit or evidence missing'
  [[ -f $STATE_DIR/deploy.lock && ! -L $STATE_DIR/deploy.lock ]] || fail 'deploy lock missing'
  exec 9<"$STATE_DIR/deploy.lock"; flock -n -x 9 || fail 'deploy writer active'
  candidate_locks_free
  complete_locks_free
  case $(unit_state ghostship-t3code-deploy) in inactive|failed) ;; *) fail 'deploy service active or unknown' ;; esac
  case $(unit_state t3code-podman-candidate) in inactive|failed) ;; *) fail 'candidate service active or unknown' ;; esac
  serving_matches_start
  require_matching_receipt_and_alias
  record_known_good "$dir/unknown-resolved.json"
  "$SYSTEMCTL_BIN" start t3code-recovery.service
  [[ $(unit_state t3code-recovery) == active ]] || fail 'recovery not active; inhibit retained'
  rm "$HOLD_FILE"
  rm "$STATE_DIR/recovery-unknown.json"; sync -f "$STATE_DIR"
  printf '%s\n' 'PASS UNKNOWN resolved with exact serving receipt; recovery inhibit cleared without T3 restart.'
  ;;
 end-unknown)
  : "${JQ_BIN:?}"
  lock_window
  [[ -f $STATE_DIR/recovery-unknown.json && ! -L $STATE_DIR/recovery-unknown.json ]] && recorded=1 || recorded=0
  if [[ ! -e $WINDOW_ROOT/active-window && ! -L $WINDOW_ROOT/active-window ]]; then
    (( recorded )) || fail 'missing active window'
    id=$("$JQ_BIN" -er 'select(.state == "UNKNOWN" and .recovery_inhibit == "retained") | .window' "$STATE_DIR/recovery-unknown.json") || fail 'UNKNOWN record invalid'
    window_id_valid "$id" || fail 'invalid recorded window'
    dir=$WINDOW_ROOT/$id
    [[ -f $HOLD_FILE && ! -L $HOLD_FILE && $(unit_state "$WINDOW_UNIT") == inactive ]] || fail 'UNKNOWN release state ambiguous'
    [[ -f $STATE_DIR/deploy.lock && ! -L $STATE_DIR/deploy.lock ]] || fail 'deploy lock missing'
    exec 9<"$STATE_DIR/deploy.lock"; flock -n -x 9 || fail 'deploy writer active'
    candidate_locks_free
    complete_locks_free
    case $(unit_state ghostship-t3code-deploy) in inactive|failed) ;; *) fail 'deploy service active or unknown' ;; esac
    case $(unit_state t3code-podman-candidate) in inactive|failed) ;; *) fail 'candidate service active or unknown' ;; esac
    serving_matches_start
    printf '%s\n' 'UNKNOWN: window already released; recovery inhibit retained. After investigation and an exact matching receipt, run ghostship-t3code-release-window resolve-unknown.'
    exit 77
  fi
  read_active
  [[ -f $HOLD_FILE ]] || fail 'recovery inhibit missing'
  case $(unit_state "$WINDOW_UNIT") in
    active) holder_ready || fail 'window holder state unknown' ;;
    inactive) (( recorded )) || fail 'window holder absent without UNKNOWN record'; candidate_locks_free ;;
    *) fail 'window holder state unknown' ;;
  esac
  [[ -f $STATE_DIR/deploy.lock && ! -L $STATE_DIR/deploy.lock ]] || fail 'deploy lock missing'
  exec 9<"$STATE_DIR/deploy.lock"; flock -n -x 9 || fail 'deploy writer active'
  case $(unit_state ghostship-t3code-deploy) in inactive|failed) ;; *) fail 'deploy service active or unknown' ;; esac
  case $(unit_state t3code-podman-candidate) in inactive|failed) ;; *) fail 'candidate service active or unknown' ;; esac
  serving_matches_start
  [[ -f $STATE_DIR/applied && -f $STATE_DIR/desired ]] || fail 'deployment state missing'
  applied=$(cat "$STATE_DIR/applied"); desired=$(cat "$STATE_DIR/desired")
  [[ $applied =~ ^[0-9a-f]{64}$ && $desired =~ ^[0-9a-f]{64}$ ]] || fail 'deployment identity unknown'
  failed_hash=absent
  if [[ -e $STATE_DIR/failed-candidate || -L $STATE_DIR/failed-candidate ]]; then
    [[ -f $STATE_DIR/failed-candidate && ! -L $STATE_DIR/failed-candidate ]] || fail 'failed marker state unknown'
    failed_hash=$(sha256sum < "$STATE_DIR/failed-candidate" | cut -d ' ' -f1)
  fi
  if (( recorded )); then
    # shellcheck disable=SC2016
    "$JQ_BIN" -e --arg id "$id" --arg desired "$desired" --arg applied "$applied" --arg failed "$failed_hash" --arg serving "$(cat "$dir/serving.before")" '
      .state == "UNKNOWN" and (.reason == "route_unknown" or .reason == "route_unavailable" or .reason == "candidate_failed" or .reason == "switch_unknown" or .reason == "legacy_unknown") and .window == $id and .desired == $desired and .applied == $applied and .receipt == "absent" and .serving == $serving and .failed_marker_sha256 == $failed and .recovery_inhibit == "retained"' "$STATE_DIR/recovery-unknown.json" >/dev/null || fail 'recorded UNKNOWN differs from current evidence'
  else
    attempt="$STATE_DIR/attempts/$desired.json"
    [[ ! -e $STATE_DIR/receipts/$desired.json && ! -L $STATE_DIR/receipts/$desired.json ]] || fail 'absent receipt not established'
    [[ ! -L $attempt ]] || fail 'attempt state unknown'
    complete_locks_free
    # shellcheck disable=SC2016
    if [[ -f $attempt ]] && "$JQ_BIN" -e --arg d "$desired" '.deployment_id == $d and .outcome == "route_unknown" and .exit_code == 77 and .status == null' "$attempt" >/dev/null; then
      reason=route_unknown
    elif [[ -f $attempt ]] && "$JQ_BIN" -e --arg d "$desired" '.deployment_id == $d and .outcome == "route_unavailable" and .exit_code == 76 and .status == null' "$attempt" >/dev/null; then
      reason=route_unavailable
    elif [[ -f $attempt ]] && "$JQ_BIN" -e --arg d "$desired" '.deployment_id == $d and .exit_code == 1 and .status == null' "$attempt" >/dev/null && [[ $failed_hash != absent ]] && [[ $(cat "$STATE_DIR/failed-candidate") =~ ^${desired}\ [0-9a-f]{64}$ ]]; then
      reason=candidate_failed
    elif [[ -f $dir/complete.started && ! -L $dir/complete.started ]]; then
      reason=switch_unknown
    elif [[ -f $dir/legacy.adopted && ! -L $dir/legacy.adopted ]]; then
      reason=legacy_unknown
    else
      fail 'route UNKNOWN or definitive candidate failure not established'
    fi
    receipt_status=0; known_good_receipt >/dev/null || receipt_status=$?
    [[ $receipt_status != 0 ]] || fail 'existing exact known-good receipt available'
    [[ $receipt_status == 1 ]] || fail 'known-good receipt status unknown'
    [[ ! -e $STATE_DIR/recovery-unknown.json && ! -L $STATE_DIR/recovery-unknown.json ]] || fail 'existing recovery UNKNOWN requires investigation'
    # Existing recovery inhibit remains: gen-590 recovery cannot read this record.
    # shellcheck disable=SC2016
    "$JQ_BIN" -cn --arg id "$id" --arg desired "$desired" --arg applied "$applied" --arg reason "$reason" --arg failed "$failed_hash" \
      --arg serving "$(cat "$dir/serving.before")" --arg at "$(date -u +%FT%TZ)" \
      '{state:"UNKNOWN",reason:$reason,window:$id,desired:$desired,applied:$applied,receipt:"absent",failed_marker_sha256:$failed,serving:$serving,at:$at,recovery_inhibit:"retained",inhibit_reason:"gen-590 recovery cannot verify the unreceipted serving image",clear_command:"ghostship-t3code-release-window resolve-unknown"}' > "$STATE_DIR/recovery-unknown.json.tmp"
    chmod 0600 "$STATE_DIR/recovery-unknown.json.tmp"; sync -f "$STATE_DIR/recovery-unknown.json.tmp"
    mv "$STATE_DIR/recovery-unknown.json.tmp" "$STATE_DIR/recovery-unknown.json"; sync -f "$STATE_DIR"
  fi
  if [[ $(unit_state "$WINDOW_UNIT") == active ]]; then "$SYSTEMCTL_BIN" stop "$WINDOW_UNIT.service"; fi
  [[ $(unit_state "$WINDOW_UNIT") == inactive ]] || fail 'holder stop outcome unknown'
  rm "$WINDOW_ROOT/active-window"; sync -f "$WINDOW_ROOT"
  printf '%s\n' 'UNKNOWN: window released; serving T3 unchanged; recovery inhibit retained because the attempt had no exact receipt.'
  printf '%s\n' 'After investigation and an exact matching receipt, run ghostship-t3code-release-window resolve-unknown.'
  exit 77
  ;;
 end-no-activation)
  [[ $(unit_state ghostship-t3code-deploy) == inactive && $(unit_state t3code-podman-candidate) == inactive ]] || fail 'failed service requires post or recovery'
  preflight_core
  lock_window
  preflight_core
  read_active
  [[ ! -e $dir/legacy.adopted ]] || fail 'legacy window history is unknown; use post or recovery'
  [[ ! -e $dir/complete.started ]] || fail 'switch intent exists'
  shopt -s nullglob dotglob
  intents=("$dir"/effect-intent.*)
  (( ${#intents[@]} == 0 )) || fail 'effect intent exists'
  baseline=$(snapshot) || fail 'state unknown'
  [[ $(tail -n +3 "$dir/window.start") == "$baseline" ]] || fail 'state changed'
  [[ ! -e $STATE_DIR/failed-candidate ]] || fail 'failed candidate exists'
  if [[ ! -f $HOLD_FILE || -L $HOLD_FILE ]] || ! holder_ready; then fail 'window state unknown'; fi
  "$SYSTEMCTL_BIN" stop "$WINDOW_UNIT.service"
  "$SYSTEMCTL_BIN" start t3code-recovery.service
  [[ $(unit_state t3code-recovery) == active ]] || fail 'recovery not active'
  rm "$HOLD_FILE"
  rm "$WINDOW_ROOT/active-window"; sync -f "$WINDOW_ROOT"
  ;;
 *) echo 'usage: release-window preflight [--adopt-inhibit]|start [--adopt-inhibit] WINDOW_ID|switch -- COMMAND [ARG...]|post|end-post [WINDOW_ID]|rollback [WINDOW_ID]|end-unknown|resolve-unknown|end-no-activation' >&2; exit 2 ;;
esac
