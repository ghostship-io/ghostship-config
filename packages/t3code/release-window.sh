#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
# shellcheck disable=SC1090
source "${WINDOW_INTENT_HELPER:?}"
: "${STATE_DIR:?}" "${SYSTEMCTL_BIN:?}" "${PODMAN_BIN:?}" "${PODMAN_TARGET:?}" "${WINDOW_UNIT:?}" "${HOLD_FILE:?}" "${LOCK_CANDIDATE:?}" "${LOCK_HARDENING:?}" "${PROFILE:?}" "${SYSTEMD_RUN_BIN:?}" "${WINDOW_HOLDER_BIN:?}"
window_root
validated_serving_image=
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
  local mode=${1:-} skip_record=${2:-}
  [[ -z $mode || $mode == --adopt-inhibit ]] || fail 'invalid preflight option'
  [[ -z $skip_record || $skip_record == --supersede-unknown ]] || fail 'invalid preflight option'
  [[ -z $skip_record || $mode == --adopt-inhibit ]] || fail '--supersede-unknown requires --adopt-inhibit'
  preflight_core
  if [[ $mode == --adopt-inhibit ]]; then
    legacy_preflight
  else
    [[ ! -e $HOLD_FILE && ! -L $HOLD_FILE ]] || fail 'recovery hold already exists'
  fi
  if [[ -z $skip_record ]]; then
    [[ ! -e $STATE_DIR/recovery-unknown.json && ! -L $STATE_DIR/recovery-unknown.json ]] || fail 'recorded UNKNOWN requires investigation'
  fi
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
candidate_pair_locked=0
lock_candidate_pair() {
  (( candidate_pair_locked == 0 )) || return 0
  [[ -f $LOCK_CANDIDATE && ! -L $LOCK_CANDIDATE && -f $LOCK_HARDENING && ! -L $LOCK_HARDENING ]] || fail 'candidate locks missing'
  exec 10<"$LOCK_CANDIDATE"; flock -n -x 10 || fail 'candidate writer active'
  exec 11<"$LOCK_HARDENING"; flock -n -x 11 || fail 'hardening writer active'
  candidate_pair_locked=1
}
expired_holder_locks() {
  local pid recorded
  [[ $(unit_state "$WINDOW_UNIT") == inactive && -f $dir/holder.ready && ! -L $dir/holder.ready ]] || fail 'holder state unknown'
  read -r pid < "$dir/holder.ready"
  [[ $pid =~ ^[1-9][0-9]*$ ]] || fail 'holder evidence invalid'
  recorded=$(sed -n '2p' "$dir/window.start")
  [[ $recorded == "holder_pid=$pid held_at="* ]] || fail 'holder start evidence incomplete'
  lock_candidate_pair
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
  if [[ ${1:-} == allow-stopped-server ]]; then
    [[ $pid =~ ^[0-9]+$ && $entered =~ ^[0-9]+$ ]] || return 1
  else
    [[ $pid =~ ^[1-9][0-9]*$ && $entered =~ ^[1-9][0-9]*$ ]] || return 1
  fi
  after=$("$PODMAN_BIN" inspect "$PODMAN_TARGET" --format '{{.Id}} {{.Image}} {{.State.StartedAt}}') || return 1
  [[ $before == "$after" ]] || return 1
  printf '%s\n%s %s\n' "$before" "$pid" "$entered"
}
lock_managed_tools() {
  : "${HOME_DIR:?}"
  local tool="$HOME_DIR/.local/state/t3code-tool-update/tool-update.lock"
  local refresh="$HOME_DIR/.local/state/t3code-shared-agents/refresh.lock"
  local t3="$HOME_DIR/.local/share/t3code-tools/t3/update.lock"
  # Commands acquire these early, before any mutation, and the verification
  # helpers acquire them again. Re-opening an fd that already holds the lock
  # would drop it and let another writer in between close and flock, so the
  # second acquisition must be a no-op.
  if (( ${managed_tools_locked:-0} )); then return 0; fi
  [[ -f $tool && ! -L $tool && -f $refresh && ! -L $refresh ]] || fail 'managed writer locks missing'
  exec 4<"$tool"; flock -n -x 4 || fail 'tool maintenance writer active'
  exec 5<"$refresh"; flock -n -x 5 || fail 'agent refresh writer active'
  if [[ ! -e $t3 && ! -L $t3 ]]; then
    # Older installations may not yet have run the standalone updater. Create
    # its existing lock as the home owner while maintenance locks are held;
    # this never replaces a lock another updater might have just opened.
    : "${SUEXEC_BIN:?}"
    [[ -d $HOME_DIR && ! -L $HOME_DIR ]] || fail 'home identity unknown'
    local owner part
    owner=$(stat -c '%u:%g' "$HOME_DIR") || fail 'home owner unknown'
    [[ $owner =~ ^[1-9][0-9]*:[0-9]+$ ]] || fail 'home owner invalid'
    for part in "$HOME_DIR/.local" "$HOME_DIR/.local/share" "$HOME_DIR/.local/share/t3code-tools" "$HOME_DIR/.local/share/t3code-tools/t3"; do
      [[ ! -L $part ]] || fail 'updater lock path is a symlink'
    done
    # shellcheck disable=SC2016
    "$SUEXEC_BIN" "$owner" bash -c 'set -eu; umask 077; mkdir -p "$1"; [ ! -L "$1/update.lock" ]; : >> "$1/update.lock"' _ "$(dirname "$t3")" || fail 'updater lock bootstrap failed'
  fi
  [[ -f $t3 && ! -L $t3 ]] || fail 'T3 update lock missing or indirect'
  exec 7<"$t3"; flock -n -x 7 || fail 'T3 update writer active'
  managed_tools_locked=1
}
no_pending_restart() {
  : "${HOME_DIR:?}"
  local allow=${1:-}
  local f
  # The container defers tool updates for as long as a window is open, so
  # update-deferred.pending is the expected consequence of holding the window,
  # not pending work. Tolerate it whenever a window is open — every ending runs
  # in that state — and keep refusing restart.pending, hold, activation and
  # in-container maintenance. With no window open the marker still refuses.
  local deferred_allowed=0
  [[ -e $WINDOW_ROOT/active-window || -L $WINDOW_ROOT/active-window ]] && deferred_allowed=1
  # Commands that run after the record is released (resolve-unknown, the
  # released end-unknown retry) have no active-window, so they ask explicitly.
  [[ $allow == allow-deferred ]] && deferred_allowed=1
  local deferred_marker="$HOME_DIR/.local/state/t3code-tool-update/update-deferred.pending"
  (( deferred_allowed )) && deferred_marker=/nonexistent-allowed
  for f in "$STATE_DIR/restart.pending" "$HOME_DIR/.local/state/t3code-tool-update/restart.pending" \
    "$deferred_marker" "$HOME_DIR/.local/state/t3code-tool-update/hold" \
    "$HOME_DIR/.local/share/t3code-tools/t3/activation.pending"; do
    [[ ! -e $f && ! -L $f ]] || fail 'pending restart or maintenance marker'
  done
  local container_markers=/run/t3code-tool-update/restart.pending
  if (( ! deferred_allowed )); then
    container_markers="$container_markers /run/t3code-tool-update/update-deferred.pending"
  fi
  container_markers="$container_markers /run/t3code-tool-update/hold /run/t3code-tool-update/maintenance"
  # shellcheck disable=SC2016
  "$PODMAN_BIN" exec "$PODMAN_TARGET" sh -c \
    'for f in $1; do [ ! -e "$f" ] && [ ! -L "$f" ] || exit 1; done' _ "$container_markers" || fail 'container maintenance state unknown or pending'
}
is_container_running() {
  local running
  running=$("$PODMAN_BIN" inspect "$PODMAN_TARGET" --format '{{.State.Running}}' 2>/dev/null) || return 1
  [[ $running == true ]] || return 1
  case $(unit_state "${PODMAN_SERVICE:-podman-t3code}") in
    inactive|failed) return 1 ;;
    *) return 0 ;;
  esac
}
receipt_for_image() {
  : "${JQ_BIN:?}"
  local img=${1#sha256:} receipt wanted="${2:-}"
  [[ ! -L $STATE_DIR/receipts && -d $STATE_DIR/receipts ]] || return 2
  shopt -s nullglob
  for receipt in "$STATE_DIR"/receipts/*.json; do
    [[ -f $receipt && ! -L $receipt && -r $receipt ]] || return 2
    # shellcheck disable=SC2016
    if "$JQ_BIN" -e --arg i "$img" --arg wanted "$wanted" '
      (.image_id | sub("^sha256:"; "")) == $i and
      (.deployment_id | type == "string" and length > 0) and ($wanted == "" or .deployment_id == $wanted) and
      (.candidate_name | type == "string" and startswith("t3code-candidate-")) and
      .live_before != null and .live_before == .live_after and
      ([.checks.app_ready,.checks.provider_turn,.checks.agent_cli,.checks.skills,.checks.desktop_transport] | all(. == true))' "$receipt" >/dev/null 2>&1; then
      printf '%s\n' "$receipt"
      return 0
    fi
  done
  return 1
}
wait_and_verify_serving() {
  local expected_image=${1#sha256:} allow=${2:-} mode=${3:-} cur_img
  for _ in {1..100}; do
    if [[ $("$PODMAN_BIN" inspect "$PODMAN_TARGET" --format '{{.State.Health.Status}}' 2>/dev/null) == healthy ]] &&
       "$PODMAN_BIN" exec "$PODMAN_TARGET" systemctl is-active --quiet t3code-server.service 2>/dev/null &&
       "$PODMAN_BIN" exec "$PODMAN_TARGET" curl -fsS --max-time 5 http://127.0.0.1:3773/ >/dev/null 2>&1; then
      break
    fi
    sleep 0.1
  done
  [[ $("$PODMAN_BIN" inspect "$PODMAN_TARGET" --format '{{.State.Health.Status}}' ) == healthy ]] || fail 'recovered container unhealthy'
  "$PODMAN_BIN" exec "$PODMAN_TARGET" systemctl is-active --quiet t3code-server.service || fail 'recovered server inactive'
  "$PODMAN_BIN" exec "$PODMAN_TARGET" curl -fsS --max-time 5 http://127.0.0.1:3773/ >/dev/null || fail 'recovered server unresponsive'
  cur_img=$("$PODMAN_BIN" inspect "$PODMAN_TARGET" --format '{{.Image}}') || fail 'recovered container image unknown'
  [[ ${cur_img#sha256:} == "$expected_image" ]] || fail 'recovered container running unexpected image'
  matched_receipt=$(known_good_receipt "$expected_image" "" "$mode") || fail 'recovered container inputs do not match receipt'
  lock_managed_tools
  no_pending_restart "$allow"
}
serving_matches_start() {
  [[ -f $dir/serving.before && ! -L $dir/serving.before ]] || fail 'serving identity baseline missing'
  local current
  current=$(serving_identity) || fail 'serving identity unknown'
  [[ $current == "$(cat "$dir/serving.before")" ]] || fail 'serving T3 changed since window start'
  [[ $("$PODMAN_BIN" inspect "$PODMAN_TARGET" --format '{{.State.Health.Status}}') == healthy ]] || fail 'serving container unhealthy'
  "$PODMAN_BIN" exec "$PODMAN_TARGET" systemctl is-active --quiet t3code-server.service || fail 'serving server inactive'
  lock_managed_tools
  no_pending_restart "${1:-}"
}
# The release's declared target identity. A failed release advances the home
# tools before acceptance, so the previous receipt no longer describes the live
# identity. Callers may accept the receipt's identity or this declared target,
# never an inferred one.
declared_target_from_unit() {
  local system unit revision tooling
  # The generation the window recorded when it opened is the only source; a
  # caller cannot redirect it through PROFILE or CURRENT_SYSTEM.
  system=$(sed -n '1p' "$dir/window.start" | sed -n 's/.* generation=\([^ ]*\).*/\1/p')
  [[ -n $system && -d $system ]] || return 1
  unit=$system/etc/systemd/system/ghostship-t3code-deploy.service
  # A generation's unit is itself a symlink into the units directory; -f follows
  # it and still rejects a disabled or missing unit.
  [[ -f $unit ]] || return 1
  revision=$(sed -n 's/.*AGENT_REVISION=\([^"[:space:]]*\).*/\1/p' "$unit" | head -n1)
  tooling=$(sed -n 's/.*TOOLING_PATH=\([^"[:space:]]*\).*/\1/p' "$unit" | head -n1)
  [[ -n $revision && -n $tooling ]] || return 1
  printf '%s %s\n' "$revision" "$tooling"
}
record_declared_target() {
  local target
  target=$(declared_target_from_unit) || return 1
  printf '%s\n' "$target" > "$dir/declared-target.tmp" || return 1
  chmod 0600 "$dir/declared-target.tmp"
  sync -f "$dir/declared-target.tmp"
  mv "$dir/declared-target.tmp" "$dir/declared-target"; sync -f "$dir"
}
declared_target() {
  local revision tooling
  [[ -f $dir/declared-target && ! -L $dir/declared-target ]] || fail 'declared release target not recorded for this window; refusing to infer it'
  read -r revision tooling < "$dir/declared-target" || fail 'declared release target unreadable; refusing to infer it'
  [[ $revision =~ ^[0-9a-zA-Z][0-9a-zA-Z._-]{0,127}$ ]] || fail 'declared release target (agent revision) invalid; refusing to infer it'
  [[ $tooling == /* && $tooling != *$'\n'* ]] || fail 'declared release target (tooling path) invalid; refusing to infer it'
  printf '%s %s\n' "$revision" "$tooling"
}
# Which identity a matched receipt describes: the live one, or the release's
# declared target that superseded it.
receipt_identity_of() {
  local receipt=$1 revision tooling bound_revision bound_tooling
  revision=$("$PODMAN_BIN" exec "$PODMAN_TARGET" cat "$CANDIDATE_HOME_TARGET/.local/state/t3code-shared-agents/release.json" | "$JQ_BIN" -er '.revision | select(type == "string" and length > 0)') || return 1
  tooling=$("$PODMAN_BIN" exec "$PODMAN_TARGET" readlink -f "$CANDIDATE_HOME_TARGET/.local/state/ghostship-t3-tools/current") || return 1
  local identity_program
  identity_program=$(cat <<'JQ'
.agent_revision == $a and .agent_path == $p
JQ
)
  read -r bound_revision bound_tooling <<< "$(declared_target)" || return 1
  if "$JQ_BIN" -e --arg a "$revision" --arg p "$tooling" "$identity_program" "$receipt" >/dev/null 2>&1; then
    printf 'live\n'
  elif "$JQ_BIN" -e --arg a "$bound_revision" --arg p "$bound_tooling" "$identity_program" "$receipt" >/dev/null 2>&1; then
    printf 'declared\n'
  else
    printf 'unknown\n'
  fi
}
known_good_receipt() {
  : "${CANDIDATE_HOME_TARGET:?}" "${JQ_BIN:?}"
  local cid image started revision tooling inode receipt wanted="${2:-}" mode="${3:-}" declared_revision="" declared_tooling=""
  if [[ $# -ge 1 ]]; then image=$1; else read -r cid image started < "$dir/serving.before"; fi
  image=${image#sha256:}
  tooling=$("$PODMAN_BIN" exec "$PODMAN_TARGET" readlink -f "$CANDIDATE_HOME_TARGET/.local/state/ghostship-t3-tools/current") || return 2
  revision=$("$PODMAN_BIN" exec "$PODMAN_TARGET" cat "$CANDIDATE_HOME_TARGET/.local/state/t3code-shared-agents/release.json" | "$JQ_BIN" -er '.revision | select(type == "string" and length > 0)') || return 2
  inode=$("$PODMAN_BIN" exec "$PODMAN_TARGET" stat -Lc '%i' /run/secrets/t3code.env) || return 2
  [[ -n $tooling && $inode =~ ^[0-9]+$ ]] || return 2
  if [[ $mode == advanced ]]; then
    read -r declared_revision declared_tooling < <(declared_target) || return 2
  fi
  [[ ! -L $STATE_DIR/receipts ]] || return 2
  [[ ! -e $STATE_DIR/receipts || -d $STATE_DIR/receipts ]] || return 2
  shopt -s nullglob
  for receipt in "$STATE_DIR"/receipts/*.json; do
    [[ -f $receipt && ! -L $receipt && -r $receipt ]] || return 2
    # shellcheck disable=SC2016
    if "$JQ_BIN" -e --arg i "$image" --arg a "$revision" --arg p "$tooling" --arg s "$inode" --arg wanted "$wanted" \
      --arg da "$declared_revision" --arg dp "$declared_tooling" --arg adv "${mode:+1}" '
      (.image_id | sub("^sha256:"; "")) == $i and
      (.deployment_id | type == "string" and length > 0) and ($wanted == "" or .deployment_id == $wanted) and
      (.candidate_name | type == "string" and startswith("t3code-candidate-")) and
      .live_before != null and .live_before == .live_after and
      .provider_secret_inode == $s and
      ((.agent_revision == $a and .agent_path == $p) or
        ($adv == "1" and .agent_revision == $da and .agent_path == $dp)) and
      ([.checks.app_ready,.checks.provider_turn,.checks.agent_cli,.checks.skills,.checks.desktop_transport] | all(. == true))' "$receipt" >/dev/null 2>&1; then
      printf '%s\n' "$receipt"
      return 0
    fi
  done
  return 1
}
restore_alias_to_image() {
  : "${ACCEPTED_IMAGE_REF:?}"
  local image=${1#sha256:} alias hash marker="$dir/alias-restore.started"
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
require_matching_receipt_and_alias() {
  local mode=${1:-} status=0 cid image started
  read -r cid image started < "$dir/serving.before"
  image=${validated_serving_image:-${image#sha256:}}
  matched_receipt=$(known_good_receipt "$image" "" "$mode") || status=$?
  [[ $status == 0 ]] || fail 'no exact known-good receipt or receipt state unknown'
  restore_alias_to_image "$image"
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
  local allow=${1:-} receipt="$STATE_DIR/receipts/$EXPECTED_DEPLOYMENT.json" attempt="$STATE_DIR/attempts/$EXPECTED_DEPLOYMENT.json" inode image switch_at switch_ms host_secret live_secret
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
  host_secret=$(sha256sum < "$PROVIDER_SECRETS_FILE") || fail 'provider secret content unknown'
  live_secret=$("$PODMAN_BIN" exec "$PODMAN_TARGET" sha256sum /run/secrets/t3code.env) || fail 'live secret content unknown'
  host_secret=${host_secret%% *}; live_secret=${live_secret%% *}
  [[ $host_secret =~ ^[0-9a-f]{64}$ && $live_secret == "$host_secret" ]] || fail 'live secret differs from receipt inputs'
  lock_managed_tools
  no_pending_restart "$allow"
}
# Retire a released window's UNKNOWN record as a recorded operator action.
# The record is never deleted: it moves into that window's archive beside an
# audit entry naming the reason, the record digest and the window that
# supersedes it. Only a terminal UNKNOWN for a different window whose own
# record predates this start can be superseded, and only while the inhibit it
# guarded is still held.
supersede_unknown() {
  : "${JQ_BIN:?}"
  local check="" expected_old=""
  if [[ ${1:-} == --check ]]; then check=1; shift; fi
  local reason=${1:-} new_id=${2:-} expected_old=${3:-} record="$STATE_DIR/recovery-unknown.json" old archive digest at now
  [[ -n $reason && ${#reason} -le 500 && $reason != *[[:cntrl:]]* ]] || fail 'supersede reason invalid'
  [[ -f $record && ! -L $record && -r $record ]] || fail 'no recorded UNKNOWN to supersede'
  [[ -f $HOLD_FILE && ! -L $HOLD_FILE ]] || fail 'supersede requires the retained recovery inhibit'
  [[ ! -e $WINDOW_ROOT/active-window && ! -L $WINDOW_ROOT/active-window ]] || fail 'supersede requires a released window'
  old=$("$JQ_BIN" -er 'select(.state == "UNKNOWN" and (.reason | test("^(route_unknown|route_unavailable|candidate_failed|switch_unknown|legacy_unknown|acceptance_unknown|receipted_runtime_failure)$"))) | .window' "$record") || fail 'recorded UNKNOWN is not a terminal outcome'
  window_id_valid "$old" || fail 'recorded window identity invalid'
  [[ $old != "$new_id" ]] || fail 'cannot supersede a record for the window being started'
  [[ -z $expected_old || $old == "$expected_old" ]] || fail 'recorded UNKNOWN changed during start; investigate it before superseding'
  at=$("$JQ_BIN" -er '.at | select(type == "string")' "$record") || fail 'recorded UNKNOWN has no recorded time'
  [[ $at =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$ ]] || fail 'recorded UNKNOWN time unknown'
  now=$(date -u +%FT%TZ)
  [[ ! $at > $now ]] || fail 'recorded UNKNOWN is not older than this start'
  archive=$WINDOW_ROOT/$old/archive
  [[ -d $WINDOW_ROOT/$old && ! -L $WINDOW_ROOT/$old ]] || fail 'recorded window evidence missing'
  (( check )) && return 0
  # The record may only move while this process holds the window lock. A second
  # exclusive attempt from a subshell must fail; if it succeeds, the call was
  # reached without the lock and nothing may be archived or removed.
  if flock -n -x "$WINDOW_ROOT/window.lock" true 2>/dev/null; then
    fail 'window lock not held; refusing to move the recorded UNKNOWN'
  fi
  digest=$(sha256sum < "$record") || fail 'recorded UNKNOWN digest unknown'
  digest=${digest%% *}
  install -d -m 0700 "$archive"
  cp --preserve=mode,timestamps -- "$record" "$archive/recovery-unknown.json.tmp" || fail 'record archive write failed'
  chmod 0600 "$archive/recovery-unknown.json.tmp"
  sync -f "$archive/recovery-unknown.json.tmp"
  [[ $(sha256sum < "$archive/recovery-unknown.json.tmp") == "$digest "* ]] || fail 'archived record differs from the live record'
  mv "$archive/recovery-unknown.json.tmp" "$archive/recovery-unknown.json"; sync -f "$archive"
  local audit_program
  audit_program=$(cat <<'JQ'
{state:"SUPERSEDED",window:$w,reason:$r,record_sha256:$h,superseded_by:$n,at:$at}
JQ
)
  "$JQ_BIN" -cn --arg w "$old" --arg r "$reason" --arg h "$digest" --arg n "$new_id" --arg at "$now" \
    "$audit_program" > "$archive/supersede.json.tmp" || fail 'supersede audit write failed'
  chmod 0600 "$archive/supersede.json.tmp"
  sync -f "$archive/supersede.json.tmp"
  mv "$archive/supersede.json.tmp" "$archive/supersede.json"; sync -f "$archive"
  # The archive and its audit are durable before the live record is retired.
  rm "$record"; sync -f "$STATE_DIR"
  printf 'PASS recorded UNKNOWN superseded window=%s superseded_by=%s\n' "$old" "$new_id"
}
case ${1:-} in
 preflight)
  [[ $# -le 2 ]] || fail 'usage: preflight [--adopt-inhibit]'
  preflight "${2:-}"
  printf 'PASS preflight\n'
  ;;
 start)
  adopt=0
  supersede=
  if [[ ${2:-} == --adopt-inhibit ]]; then adopt=1; shift; fi
  if [[ ${2:-} == --supersede-unknown ]]; then
    [[ -n ${3:-} ]] || fail 'usage: --supersede-unknown requires a reason'
    supersede=$3; shift 2
  fi
  [[ $# == 2 ]] || fail 'usage: start [--adopt-inhibit [--supersede-unknown REASON]] WINDOW_ID'
  id=$2; window_id_valid "$id" || fail 'invalid window id'
  : "${WINDOW_SECONDS:?}"
  supersede_record=
  if [[ -n $supersede ]]; then
    (( adopt )) || fail '--supersede-unknown requires --adopt-inhibit'
    supersede_unknown --check "$supersede" "$id"
    supersede_record=$("$JQ_BIN" -er 'select(.state == "UNKNOWN") | .window' "$STATE_DIR/recovery-unknown.json") || fail 'recorded UNKNOWN identity unknown'
  fi
  if (( adopt )); then
    if [[ -n $supersede ]]; then preflight --adopt-inhibit --supersede-unknown; else preflight --adopt-inhibit; fi
  else preflight; fi
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
  # Preflight is read-only and has now passed every guard, and this window's
  # lock is held: only here does the record move. A failure above leaves the
  # live UNKNOWN untouched.
  if [[ -n $supersede ]]; then supersede_unknown "$supersede" "$id" "$supersede_record"; fi
  exec 6<"$LOCK_CANDIDATE" 7<"$LOCK_HARDENING"
  flock -n -x 6 || fail 'candidate lock held'
  flock -n -x 7 || fail 'hardening lock held'
  acquired_at=$(date -u +%FT%TZ)
  acquired_ms=$(date +%s%3N)
  baseline=$(snapshot) || fail 'baseline unknown'
  serving=$(serving_identity) || fail 'serving identity unknown'
  # Pin the generation this window belongs to. /run/current-system is the fixed
  # system path; the resolved profile is the test/dev fallback when it is absent.
  generation_source=/run/current-system
  [[ -d $generation_source ]] || generation_source=$(readlink -f "$PROFILE") || fail 'generation path unknown'
  [[ -n $generation_source && -d $generation_source ]] || fail 'generation path unknown'
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
  { printf 'started=%s start_ms=%s acquired_by=%s generation=%s\n' "$acquired_at" "$acquired_ms" "$$" "$generation_source"; printf '%s\n' "$baseline"; } > "$dir/window.start.tmp"
  sync -f "$dir/window.start.tmp"; mv "$dir/window.start.tmp" "$dir/window.start"; sync -f "$dir"
  printf '%s\n' "$id" > "$WINDOW_ROOT/active-window.tmp"
  sync -f "$WINDOW_ROOT/active-window.tmp"
  mv "$WINDOW_ROOT/active-window.tmp" "$WINDOW_ROOT/active-window"; sync -f "$WINDOW_ROOT"
  # Arguments are expanded by the holder shell.
  # shellcheck disable=SC2016
  # The systemd manager starts this with its own minimal PATH, so `bash`, `mv`,
  # The holder is its own packaged program: it takes both locks and writes its
  # own PID. Inlined here, `$$` reached the built generator as a bare `$` and
  # holder.ready recorded "$", leaving the window permanently un-ready.
  "$SYSTEMD_RUN_BIN" --quiet --unit="$WINDOW_UNIT" --collect -p "RuntimeMaxSec=$WINDOW_SECONDS" -- \
    "$WINDOW_HOLDER_BIN" "$LOCK_CANDIDATE" "$LOCK_HARDENING" "$dir"
  exec 6<&- 7<&-
  for _ in {1..100}; do [[ -f $dir/holder.ready ]] && break; sleep 0.05; done
  holder_ready || fail 'window holder has not acquired both locks'
  read -r holder_pid < "$dir/holder.ready"
  { printf 'started=%s start_ms=%s acquired_by=%s generation=%s\n' "$acquired_at" "$acquired_ms" "$$" "$generation_source"; printf 'holder_pid=%s held_at=%s\n' "$holder_pid" "$(date -u +%FT%TZ)"; printf '%s\n' "$baseline"; } > "$dir/window.start.tmp"
  sync -f "$dir/window.start.tmp"; mv "$dir/window.start.tmp" "$dir/window.start"; sync -f "$dir"
  if (( ! adopt )); then install -d -m 0700 "$(dirname "$HOLD_FILE")"; : > "$HOLD_FILE"; fi
  holder_ready || fail 'window holder lost its locks; recovery not stopped'
  "$SYSTEMCTL_BIN" stop t3code-recovery.service
  [[ $(unit_state t3code-recovery) == inactive ]] || fail 'recovery did not stop'
  if (( adopt )); then printf 'PASS window started id=%s mode=adopted-inhibit\n' "$id"; else printf 'PASS window started id=%s mode=new\n' "$id"; fi
  ;;
 cancel-start)
  [[ $# == 1 ]] || fail 'usage: cancel-start'
  lock_window
  read_active
  [[ $(sed -n '2p' "$dir/window.start") != holder_pid=* ]] || fail 'window start completed; use post or recovery'
  [[ ! -e $dir/complete.started && ! -L $dir/complete.started ]] || fail 'switch intent exists'
  shopt -s nullglob dotglob
  intents=("$dir"/effect-intent.*)
  (( ${#intents[@]} == 0 )) || fail 'effect intent exists'
  preflight_core
  complete_locks_free
  [[ $(unit_state t3code-recovery) == active ]] || fail 'recovery state changed during start'
  if [[ -f $dir/legacy.adopted && ! -L $dir/legacy.adopted ]]; then
    [[ -f $HOLD_FILE && ! -L $HOLD_FILE ]] || fail 'legacy inhibit missing'
  else
    [[ ! -e $HOLD_FILE && ! -L $HOLD_FILE ]] || fail 'unexpected recovery inhibit'
  fi
  baseline=$(snapshot) || fail 'state unknown'
  [[ $(tail -n +2 "$dir/window.start") == "$baseline" ]] || fail 'state changed during start'
  exec 9<"$STATE_DIR/deploy.lock"; flock -n -x 9 || fail 'deploy writer active'
  serving_matches_start
  case $(unit_state "$WINDOW_UNIT") in
    active)
      if ! holder_ready; then
        # Ownership is still provable without a usable PID record: this window's
        # unit is active and active-window names this window, so the process
        # holding it is ours. Refusing here left a half-open window that nothing
        # could close until RuntimeMaxSec expired.
        printf 'warning: holder PID record unusable; identifying the holder by unit %s and window %s\n' \
          "$WINDOW_UNIT" "$id" >&2
      fi
      "$SYSTEMCTL_BIN" stop "$WINDOW_UNIT.service"
      [[ $(unit_state "$WINDOW_UNIT") == inactive ]] || fail 'holder stop outcome unknown'
      lock_candidate_pair ;;
    inactive|failed) lock_candidate_pair ;;
    *) fail 'starting holder state unknown' ;;
  esac
  printf 'cancelled=%s legacy_inhibit=%s\n' "$(date -u +%FT%TZ)" "$( [[ -f $dir/legacy.adopted ]] && printf retained || printf absent )" > "$dir/start-cancelled.tmp"
  sync -f "$dir/start-cancelled.tmp"; mv "$dir/start-cancelled.tmp" "$dir/start-cancelled"; sync -f "$dir"
  rm "$WINDOW_ROOT/active-window"; sync -f "$WINDOW_ROOT"
  printf '%s\n' 'PASS incomplete start cancelled; any legacy recovery inhibit remains unchanged.'
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
  # The active generation now carries the deploy unit this switch installed.
  # Bind its identity to the window so recovery cannot be told one by a caller.
  if ! record_declared_target; then
    printf 'at=%s reason=deploy unit identity unreadable\n' "$(date -u +%FT%TZ)" > "$dir/declared-target.absent"
    sync -f "$dir/declared-target.absent"
  fi
  printf 'exit_code=%s\n' "$switch_rc" > "$dir/switch.result.tmp"
  sync -f "$dir/switch.result.tmp"; mv "$dir/switch.result.tmp" "$dir/switch.result"; sync -f "$dir"
  exit "$switch_rc"
  ;;
 post)
  [[ -f $WINDOW_ROOT/window.lock ]] || fail 'window lock missing'
  exec 8<"$WINDOW_ROOT/window.lock"; flock -n -s 8 || fail 'window transition in progress'
  read_active
  [[ -f $HOLD_FILE && ! -L $HOLD_FILE ]] || fail 'window state unknown'
  case $(unit_state "$WINDOW_UNIT") in
    active) holder_ready || fail 'window holder state unknown' ;;
    inactive) expired_holder_locks ;;
    *) fail 'window holder state unknown' ;;
  esac
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
    lock_candidate_pair
    post_verify allow-deferred
    printf 'PASS post; window already released deployment=%s image=%s\n' "$EXPECTED_DEPLOYMENT" "$EXPECTED_IMAGE"
    exit 0
  fi
  read_active
  [[ $# == 1 || $2 == "$id" ]] || fail 'window ID does not match'
  [[ ! -e $STATE_DIR/recovery-unknown.json && ! -L $STATE_DIR/recovery-unknown.json ]] || fail 'recorded UNKNOWN remains; supersede it before this window can close'
  case $(unit_state "$WINDOW_UNIT") in
    active) if [[ ! -f $HOLD_FILE || -L $HOLD_FILE ]] || ! holder_ready; then fail 'window state unknown'; fi ;;
    inactive) expired_holder_locks ;;
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
  lock_candidate_pair
  [[ ! -L $HOLD_FILE ]] || fail 'recovery hold is a symlink'
  [[ ! -e $HOLD_FILE ]] || rm "$HOLD_FILE"
  rm "$WINDOW_ROOT/active-window"; sync -f "$WINDOW_ROOT"
  printf 'PASS post and window released deployment=%s image=%s\n' "$EXPECTED_DEPLOYMENT" "$EXPECTED_IMAGE"
  ;;
 rollback)
  : "${JQ_BIN:?}"
  [[ $# -le 2 ]] || fail 'usage: rollback [WINDOW_ID]'
  lock_window
  # Serialize with the managed app and tool writers before any mutation. The
  # verification helpers also acquire these locks, but they run after the alias
  # restore and the container start, so an activation could otherwise interleave
  # between restoring the accepted alias and proving what is being served.
  lock_managed_tools
  already_released=0
  if [[ ! -e $WINDOW_ROOT/active-window && ! -L $WINDOW_ROOT/active-window ]]; then
    [[ $# == 2 ]] || fail 'missing active window; provide the recorded window ID'
    id=$2; window_id_valid "$id" || fail 'invalid window ID'
    dir=$WINDOW_ROOT/$id
    [[ -f $dir/known-good.json && ! -L $dir/known-good.json && ! -e $HOLD_FILE && ! -L $HOLD_FILE && $(unit_state "$WINDOW_UNIT") == inactive ]] || fail 'completed rollback state unknown'
    lock_candidate_pair
    already_released=1
  else
    read_active
    [[ $# == 1 || $2 == "$id" ]] || fail 'window ID does not match'
    case $(unit_state "$WINDOW_UNIT") in
      active) if [[ ! -f $HOLD_FILE || -L $HOLD_FILE ]] || ! holder_ready; then fail 'window state unknown'; fi ;;
      inactive) expired_holder_locks ;;
      *) fail 'window holder state unknown' ;;
    esac
  fi
  [[ -f $STATE_DIR/deploy.lock && ! -L $STATE_DIR/deploy.lock ]] || fail 'deploy lock missing'
  exec 9<"$STATE_DIR/deploy.lock"; flock -n -x 9 || fail 'deploy writer active'
  case $(unit_state ghostship-t3code-deploy) in inactive|failed) ;; *) fail 'deploy service active or unknown' ;; esac
  case $(unit_state t3code-podman-candidate) in inactive|failed) ;; *) fail 'candidate service active or unknown' ;; esac
  container_was_stopped=0
  if (( already_released )); then
    is_container_running || fail 'container is stopped after release'
    serving_matches_start allow-deferred
    require_matching_receipt_and_alias advanced
    printf '%s\n' 'PASS known-good serving identity and existing receipt; window already released.'
    exit 0
  fi
  if ! is_container_running; then
    container_was_stopped=1
    receipt_status=0
    read -r _ baseline_image _ < "$dir/serving.before" || fail 'serving identity baseline missing'
    baseline_image=${baseline_image#sha256:}
    matched_receipt=$(receipt_for_image "$baseline_image") || receipt_status=$?
    [[ $receipt_status == 0 ]] || fail 'no exact known-good receipt for stopped container'
    restore_alias_to_image "$baseline_image"
    "$SYSTEMCTL_BIN" start "${PODMAN_SERVICE:-podman-t3code}.service"
    [[ $(unit_state "${PODMAN_SERVICE:-podman-t3code}") == active ]] || fail 'container service failed to start'
    recovery_mode=
    [[ ! -f $dir/declared-target ]] || recovery_mode=advanced
    wait_and_verify_serving "$baseline_image" "" "$recovery_mode"
  else
    serving_matches_start allow-deferred
    require_matching_receipt_and_alias
  fi
  record_known_good "$dir/known-good.json"
  "$SYSTEMCTL_BIN" start t3code-recovery.service
  [[ $(unit_state t3code-recovery) == active ]] || fail 'recovery not active; inhibit retained'
  if [[ $(unit_state "$WINDOW_UNIT") == active ]]; then
    holder_ready || fail 'holder lost before release; inhibit retained'
    "$SYSTEMCTL_BIN" stop "$WINDOW_UNIT.service"
  fi
  [[ $(unit_state "$WINDOW_UNIT") == inactive ]] || fail 'holder stop outcome unknown'
  lock_candidate_pair
  [[ ! -L $HOLD_FILE ]] || fail 'recovery hold is a symlink'
  [[ ! -e $HOLD_FILE ]] || rm "$HOLD_FILE"
  rm "$WINDOW_ROOT/active-window"; sync -f "$WINDOW_ROOT"
  if (( container_was_stopped )); then
    printf '%s\n' 'PASS known-good serving identity and existing receipt; container recovered and window released.'
  else
    printf '%s\n' 'PASS known-good serving identity and existing receipt; window released without T3 restart.'
  fi
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
  lock_candidate_pair
  complete_locks_free
  case $(unit_state ghostship-t3code-deploy) in inactive|failed) ;; *) fail 'deploy service active or unknown' ;; esac
  case $(unit_state t3code-podman-candidate) in inactive|failed) ;; *) fail 'candidate service active or unknown' ;; esac
  reason=$("$JQ_BIN" -er '.reason' "$STATE_DIR/recovery-unknown.json") || fail 'UNKNOWN reason missing'
  container_was_stopped=0
  if ! is_container_running; then
    container_was_stopped=1
    target_img=
    if [[ $reason == receipted_runtime_failure ]]; then
      recorded_serving=$("$JQ_BIN" -er '.serving' "$STATE_DIR/recovery-unknown.json") || fail 'recorded serving identity missing'
      read -r _ target_img _ <<< "$recorded_serving"
    else
      read -r _ target_img _ < "$dir/serving.before" || fail 'serving identity baseline missing'
    fi
    target_img=${target_img#sha256:}
    receipt_status=0
    matched_receipt=$(receipt_for_image "$target_img") || receipt_status=$?
    [[ $receipt_status == 0 ]] || fail 'no exact known-good receipt for stopped container'
    restore_alias_to_image "$target_img"
    "$SYSTEMCTL_BIN" start "${PODMAN_SERVICE:-podman-t3code}.service"
    [[ $(unit_state "${PODMAN_SERVICE:-podman-t3code}") == active ]] || fail 'container service failed to start'
    recovery_mode=
    if [[ $reason == acceptance_unknown || $reason == switch_unknown ]]; then
      [[ -f $dir/declared-target && ! -L $dir/declared-target ]] || fail 'switch did not start; refusing to infer the release target'
      recovery_mode=advanced
    fi
    wait_and_verify_serving "$target_img" allow-deferred "$recovery_mode"
    validated_serving_image=$target_img
    if [[ $recovery_mode == advanced ]]; then
      advanced_identity_record=$(serving_identity) || fail 'serving identity unknown'
      receipt_identity=$(receipt_identity_of "$matched_receipt") || fail 'receipt identity unknown'
    fi
  elif [[ $reason == acceptance_unknown || $reason == switch_unknown ]]; then
    # The switch may have advanced the home tools before acceptance failed.
    # Verify the served image in the record and accept a receipt whose identity
    # is either the live one or the release's declared target.
    [[ -f $dir/complete.started && ! -L $dir/complete.started ]] || fail 'switch did not start; refusing to infer the release target'
    declared_target >/dev/null
    recorded_serving=$("$JQ_BIN" -er '.serving | select(type == "string" and length > 0)' "$STATE_DIR/recovery-unknown.json") || fail 'recorded serving identity missing'
    current=$(serving_identity) || fail 'serving identity unknown'
    read -r _ recorded_image _ <<< "$recorded_serving"
    read -r _ current_image _ <<< "$current"
    [[ ${recorded_image#sha256:} =~ ^[0-9a-f]{64}$ && $recorded_image == "$current_image" ]] || fail 'serving image differs from the recorded UNKNOWN end'
    [[ $("$PODMAN_BIN" inspect "$PODMAN_TARGET" --format '{{.State.Health.Status}}') == healthy ]] || fail 'serving container unhealthy'
    "$PODMAN_BIN" exec "$PODMAN_TARGET" systemctl is-active --quiet t3code-server.service || fail 'serving server inactive'
    "$PODMAN_BIN" exec "$PODMAN_TARGET" curl -fsS --max-time 5 http://127.0.0.1:3773/ >/dev/null || fail 'serving server unresponsive'
    lock_managed_tools
    no_pending_restart allow-deferred
    read -r _ validated_serving_image _ <<< "$current"
    validated_serving_image=${validated_serving_image#sha256:}
    require_matching_receipt_and_alias advanced
    advanced_identity_record=$current
    receipt_identity=$(receipt_identity_of "$matched_receipt") || fail 'receipt identity unknown'
  elif [[ $reason == receipted_runtime_failure ]]; then
    current=$(serving_identity) || fail 'serving identity unknown'
    recorded_serving=$("$JQ_BIN" -er '.serving' "$STATE_DIR/recovery-unknown.json") || fail 'recorded serving identity missing'
    # Investigation may have restarted a receipted runtime. The current healthy
    # image and inputs are verified again below; keep both identities in audit.
    [[ $("$PODMAN_BIN" inspect "$PODMAN_TARGET" --format '{{.State.Health.Status}}') == healthy ]] || fail 'serving container unhealthy'
    "$PODMAN_BIN" exec "$PODMAN_TARGET" systemctl is-active --quiet t3code-server.service || fail 'serving server inactive'
    "$PODMAN_BIN" exec "$PODMAN_TARGET" curl -fsS --max-time 5 http://127.0.0.1:3773/ >/dev/null || fail 'serving server unresponsive'
    lock_managed_tools
    no_pending_restart allow-deferred
    read -r _ validated_serving_image _ <<< "$current"
    validated_serving_image=${validated_serving_image#sha256:}
    require_matching_receipt_and_alias
  else
    serving_matches_start allow-deferred
    require_matching_receipt_and_alias
  fi
  record_known_good "$dir/unknown-resolved.json"
  if [[ -n ${advanced_identity_record:-} ]]; then
    read -r bound_revision bound_tooling <<< "$(declared_target)" || fail 'declared release target unreadable'
    # shellcheck disable=SC2016
    "$JQ_BIN" --arg serving "$advanced_identity_record" --arg identity "${receipt_identity:-live}" \
      --arg revision "$bound_revision" --arg tooling "$bound_tooling" \
      '. + {serving_at_resolve:$serving,receipt_identity:$identity,declared_agent_revision:$revision,declared_tooling_path:$tooling}' \
      "$dir/unknown-resolved.json" > "$dir/unknown-resolved.json.tmp"
    chmod 0600 "$dir/unknown-resolved.json.tmp"; sync -f "$dir/unknown-resolved.json.tmp"
    mv "$dir/unknown-resolved.json.tmp" "$dir/unknown-resolved.json"; sync -f "$dir"
  fi
  if [[ $reason == receipted_runtime_failure && $container_was_stopped == 0 ]]; then
    # shellcheck disable=SC2016
    "$JQ_BIN" --arg before "$recorded_serving" --arg after "$current" '. + {serving_before:$before,serving_after:$after}' "$dir/unknown-resolved.json" > "$dir/unknown-resolved.json.tmp"
    chmod 0600 "$dir/unknown-resolved.json.tmp"; sync -f "$dir/unknown-resolved.json.tmp"; mv "$dir/unknown-resolved.json.tmp" "$dir/unknown-resolved.json"; sync -f "$dir"
  fi
  "$SYSTEMCTL_BIN" start t3code-recovery.service
  [[ $(unit_state t3code-recovery) == active ]] || fail 'recovery not active; inhibit retained'
  rm "$HOLD_FILE"
  rm "$STATE_DIR/recovery-unknown.json"; sync -f "$STATE_DIR"
  if (( container_was_stopped )); then
    printf '%s\n' 'PASS UNKNOWN resolved with exact serving receipt; container recovered and recovery inhibit cleared.'
  else
    printf '%s\n' 'PASS UNKNOWN resolved with exact serving receipt; recovery inhibit cleared without T3 restart.'
  fi
  ;;
 end-receipted-failure)
  : "${JQ_BIN:?}"
  lock_window
  [[ -f $STATE_DIR/recovery-unknown.json && ! -L $STATE_DIR/recovery-unknown.json ]] && recorded=1 || recorded=0
  already_released=0
  if [[ ! -e $WINDOW_ROOT/active-window && ! -L $WINDOW_ROOT/active-window ]]; then
    (( recorded )) || fail 'missing active window'
    id=$("$JQ_BIN" -er 'select(.state == "UNKNOWN" and .reason == "receipted_runtime_failure" and .recovery_inhibit == "retained") | .window' "$STATE_DIR/recovery-unknown.json") || fail 'UNKNOWN record invalid'
    window_id_valid "$id" || fail 'invalid recorded window'
    dir=$WINDOW_ROOT/$id
    [[ -f $HOLD_FILE && ! -L $HOLD_FILE && $(unit_state "$WINDOW_UNIT") == inactive ]] || fail 'UNKNOWN release state ambiguous'
    lock_candidate_pair
    already_released=1
  else
    read_active
    [[ -f $HOLD_FILE && ! -L $HOLD_FILE ]] || fail 'recovery inhibit missing'
    case $(unit_state "$WINDOW_UNIT") in
      active) holder_ready || fail 'window holder state unknown' ;;
      inactive) expired_holder_locks ;;
      *) fail 'window holder state unknown' ;;
    esac
  fi
  [[ -f $dir/complete.started && ! -L $dir/complete.started ]] || fail 'switch evidence missing'
  [[ -f $STATE_DIR/deploy.lock && ! -L $STATE_DIR/deploy.lock ]] || fail 'deploy lock missing'
  exec 9<"$STATE_DIR/deploy.lock"; flock -n -x 9 || fail 'deploy writer active'
  complete_locks_free
  case $(unit_state ghostship-t3code-deploy) in inactive|failed) ;; *) fail 'deploy service active or unknown' ;; esac
  case $(unit_state t3code-podman-candidate) in inactive|failed) ;; *) fail 'candidate service active or unknown' ;; esac
  [[ -f $STATE_DIR/applied && -f $STATE_DIR/desired ]] || fail 'deployment state missing'
  applied=$(cat "$STATE_DIR/applied"); desired=$(cat "$STATE_DIR/desired")
  [[ $applied =~ ^[0-9a-f]{64}$ && $desired =~ ^[0-9a-f]{64}$ ]] || fail 'deployment identity unknown'
  read -r switch_at switch_ms < "$dir/complete.started" || fail 'switch start evidence malformed'
  [[ $switch_at =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$ && $switch_ms =~ ^[0-9]+$ ]] || fail 'switch start time unknown'
  attempt="$STATE_DIR/attempts/$desired.json"
  [[ ! -L $attempt ]] || fail 'deployment attempt state unknown'
  attempt_state=absent
  if [[ -e $attempt ]]; then
    [[ -f $attempt && -r $attempt ]] || fail 'deployment attempt unreadable'
    # shellcheck disable=SC2016
    attempt_state=$("$JQ_BIN" -er --arg d "$desired" --argjson min "$switch_ms" '
      select(.deployment_id == $d and (.started_at_ms | type == "number")) |
      if .started_at_ms < $min then "stale"
      elif (.exit_code | type == "number" and . != 0) then "failed"
      elif .status == "running" and .exit_code == null then "unfinished"
      elif .exit_code == 0 and .status == null then "completed"
      else "unclassified" end' "$attempt") || fail 'deployment attempt identity unknown'
  fi
  if [[ $attempt_state == completed ]]; then
    if [[ $("$PODMAN_BIN" inspect "$PODMAN_TARGET" --format '{{.State.Health.Status}}') == healthy ]] &&
       "$PODMAN_BIN" exec "$PODMAN_TARGET" systemctl is-active --quiet t3code-server.service &&
       "$PODMAN_BIN" exec "$PODMAN_TARGET" curl -fsS --max-time 5 http://127.0.0.1:3773/ >/dev/null; then
      fail 'deployment appears healthy; use post'
    fi
    attempt_state=completed_unhealthy
  fi
  lock_managed_tools
  # An already-released retry has no active-window to explain the deferral.
  if (( already_released )); then no_pending_restart allow-deferred; else no_pending_restart; fi
  if is_container_running; then
    current=$(serving_identity allow-stopped-server) || fail 'current container or server identity unknown'
    read -r _ current_image _ <<< "$current"; current_image=${current_image#sha256:}
    status=0; matched_receipt=$(known_good_receipt "$current_image" "$desired") || status=$?
    [[ $status == 0 ]] || fail 'no exact receipt for the running candidate'
    hash=$(sha256sum < "$matched_receipt" | cut -d ' ' -f1)
    [[ $(serving_identity allow-stopped-server) == "$current" ]] || fail 'serving T3 changed during verification'
  else
    current="stopped sha256:$desired stopped"
    status=0; matched_receipt=$(receipt_for_image "$desired" "$desired") || status=$?
    [[ $status == 0 ]] || fail 'no exact receipt for the stopped candidate'
    hash=$(sha256sum < "$matched_receipt" | cut -d ' ' -f1)
  fi
  if (( recorded )); then
    # shellcheck disable=SC2016
    "$JQ_BIN" -e --arg id "$id" --arg desired "$desired" --arg applied "$applied" --arg serving "$current" --arg hash "$hash" --arg attempt "$attempt_state" '
      .state == "UNKNOWN" and .reason == "receipted_runtime_failure" and .window == $id and .desired == $desired and .applied == $applied and .receipt == "exact_candidate_pass" and .receipt_sha256 == $hash and .serving == $serving and .attempt_state == $attempt and .recovery_inhibit == "retained"' "$STATE_DIR/recovery-unknown.json" >/dev/null || fail 'recorded UNKNOWN differs from current evidence'
  else
    [[ ! -e $STATE_DIR/recovery-unknown.json && ! -L $STATE_DIR/recovery-unknown.json ]] || fail 'existing recovery UNKNOWN requires investigation'
    # shellcheck disable=SC2016
    "$JQ_BIN" -cn --arg id "$id" --arg desired "$desired" --arg applied "$applied" --arg serving "$current" --arg hash "$hash" --arg attempt "$attempt_state" --arg at "$(date -u +%FT%TZ)" \
      '{state:"UNKNOWN",reason:"receipted_runtime_failure",window:$id,desired:$desired,applied:$applied,receipt:"exact_candidate_pass",receipt_sha256:$hash,attempt_state:$attempt,serving:$serving,at:$at,recovery_inhibit:"retained",inhibit_reason:"runtime failure after a receipted restart",clear_command:"ghostship-t3code-release-window resolve-unknown"}' > "$STATE_DIR/recovery-unknown.json.tmp"
    chmod 0600 "$STATE_DIR/recovery-unknown.json.tmp"; sync -f "$STATE_DIR/recovery-unknown.json.tmp"
    mv "$STATE_DIR/recovery-unknown.json.tmp" "$STATE_DIR/recovery-unknown.json"; sync -f "$STATE_DIR"
  fi
  if (( ! already_released )); then
    if [[ $(unit_state "$WINDOW_UNIT") == active ]]; then "$SYSTEMCTL_BIN" stop "$WINDOW_UNIT.service"; fi
    [[ $(unit_state "$WINDOW_UNIT") == inactive ]] || fail 'holder stop outcome unknown'
    lock_candidate_pair
    rm "$WINDOW_ROOT/active-window"; sync -f "$WINDOW_ROOT"
  fi
  printf '%s\n' 'UNKNOWN: window released; exact candidate receipt exists, runtime failed or is unknown, and recovery inhibit is retained.'
  printf '%s\n' 'After investigation and healthy exact-receipt readback, run ghostship-t3code-release-window resolve-unknown.'
  exit 77
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
    lock_candidate_pair
    complete_locks_free
    case $(unit_state ghostship-t3code-deploy) in inactive|failed) ;; *) fail 'deploy service active or unknown' ;; esac
    case $(unit_state t3code-podman-candidate) in inactive|failed) ;; *) fail 'candidate service active or unknown' ;; esac
    serving_matches_start allow-deferred
    printf '%s\n' 'UNKNOWN: window already released; recovery inhibit retained. After investigation and an exact matching receipt, run ghostship-t3code-release-window resolve-unknown.'
    exit 77
  fi
  read_active
  [[ -f $HOLD_FILE ]] || fail 'recovery inhibit missing'
  case $(unit_state "$WINDOW_UNIT") in
    active) holder_ready || fail 'window holder state unknown' ;;
    inactive) expired_holder_locks ;;
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
      .state == "UNKNOWN" and (.reason == "route_unknown" or .reason == "route_unavailable" or .reason == "candidate_failed" or .reason == "switch_unknown" or .reason == "legacy_unknown" or .reason == "acceptance_unknown") and .window == $id and .desired == $desired and .applied == $applied and .receipt == "absent" and .serving == $serving and .failed_marker_sha256 == $failed and .recovery_inhibit == "retained"' "$STATE_DIR/recovery-unknown.json" >/dev/null || fail 'recorded UNKNOWN differs from current evidence'
  else
    attempt="$STATE_DIR/attempts/$desired.json"
    read -r _ start_ms_field _ < "$dir/window.start" || fail 'window start evidence unreadable'
    [[ $start_ms_field =~ ^start_ms=([0-9]+)$ ]] || fail 'window start time unknown'
    minimum_ms=${BASH_REMATCH[1]}
    if [[ -f $dir/legacy.adopted && ! -L $dir/legacy.adopted ]]; then
      read -r opened_field _ < "$dir/legacy.adopted" || fail 'legacy timing evidence unreadable'
      [[ $opened_field =~ ^opened=([0-9]+)$ ]] || fail 'legacy timing unknown'
      minimum_ms=$(( 10#${BASH_REMATCH[1]} * 1000 ))
    fi
    [[ ! -e $STATE_DIR/receipts/$desired.json && ! -L $STATE_DIR/receipts/$desired.json ]] || fail 'absent receipt not established'
    [[ ! -L $attempt ]] || fail 'attempt state unknown'
    complete_locks_free
    # shellcheck disable=SC2016
    if [[ -f $attempt ]] && "$JQ_BIN" -e --arg d "$desired" --argjson min "$minimum_ms" '.deployment_id == $d and .outcome == "route_unknown" and .exit_code == 77 and .status == null and (.started_at_ms | type == "number" and . >= $min)' "$attempt" >/dev/null; then
      reason=route_unknown
    elif [[ -f $attempt ]] && "$JQ_BIN" -e --arg d "$desired" --argjson min "$minimum_ms" '.deployment_id == $d and .outcome == "route_unavailable" and .exit_code == 76 and .status == null and (.started_at_ms | type == "number" and . >= $min)' "$attempt" >/dev/null; then
      reason=route_unavailable
    elif [[ -f $attempt ]] && "$JQ_BIN" -e --arg d "$desired" --argjson min "$minimum_ms" '.deployment_id == $d and .exit_code == 1 and .status == null and (.started_at_ms | type == "number" and . >= $min)' "$attempt" >/dev/null && [[ $failed_hash != absent ]] && [[ $(cat "$STATE_DIR/failed-candidate") =~ ^${desired}\ [0-9a-f]{64}$ ]]; then
      reason=candidate_failed
    elif [[ -f $attempt ]] && "$JQ_BIN" -e --arg d "$desired" --argjson min "$minimum_ms" '.deployment_id == $d and .outcome == "acceptance_unknown" and .exit_code == 77 and .status == null and (.started_at_ms | type == "number" and . >= $min)' "$attempt" >/dev/null; then
      # The switch ran and acceptance then failed as unknown: no receipt exists,
      # so this is an unreceipted UNKNOWN end with the inhibit retained.
      reason=acceptance_unknown
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
  lock_candidate_pair
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
  [[ $(unit_state "$WINDOW_UNIT") == inactive ]] || fail 'holder stop outcome unknown'
  lock_candidate_pair
  "$SYSTEMCTL_BIN" start t3code-recovery.service
  [[ $(unit_state t3code-recovery) == active ]] || fail 'recovery not active'
  rm "$HOLD_FILE"
  rm "$WINDOW_ROOT/active-window"; sync -f "$WINDOW_ROOT"
  ;;
 *) echo 'usage: release-window preflight [--adopt-inhibit]|start [--adopt-inhibit [--supersede-unknown REASON]] WINDOW_ID|cancel-start|switch -- COMMAND [ARG...]|post|end-post [WINDOW_ID]|rollback [WINDOW_ID]|end-receipted-failure|end-unknown|resolve-unknown|end-no-activation' >&2; exit 2 ;;
esac
