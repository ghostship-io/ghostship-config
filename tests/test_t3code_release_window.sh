#!/usr/bin/env bash
set -euo pipefail
repo=$(cd "$(dirname "$0")/.." && pwd)
tmp=$(mktemp -d); trap '[[ ! -f $tmp/holder-pid ]] || kill "$(cat "$tmp/holder-pid")" 2>/dev/null || true; rm -rf "$tmp"' EXIT
mkdir -p "$tmp/evidence" "$tmp/state" "$tmp/bin"
printf '%s\n' "$tmp/evidence" > "$tmp/config"
touch "$tmp/evidence/window.lock" "$tmp/state/deploy.lock" "$tmp/candidate.lock" "$tmp/hardening.lock"
printf 'old\n' > "$tmp/state/applied"; cp "$tmp/state/applied" "$tmp/state/desired"
ln -s system-1-link "$tmp/profile"
cat > "$tmp/bin/systemctl" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$FIXTURE/systemctl.events"
if [[ $1 == show ]]; then
  if [[ $2 == ghostship-t3code-deploy.service && $3 == -p && $4 == Result ]]; then echo success; exit; fi
  if [[ $2 == window.service && $3 == -p && $4 == MainPID ]]; then cat "$FIXTURE/holder-pid"; exit; fi
  case $2 in window.service) [[ -f $FIXTURE/holder-pid ]] && kill -0 "$(cat "$FIXTURE/holder-pid")" 2>/dev/null && echo active || echo inactive ;; t3code-recovery.service) [[ -e $FIXTURE/recovery-inactive ]] && echo inactive || echo active ;; ghostship-t3code-deploy.service) [[ ${FIXTURE_DEPLOY_FAILED:-0} == 1 ]] && echo failed || echo inactive ;; *) echo inactive ;; esac
elif [[ $1 == stop && $2 == t3code-recovery.service ]]; then touch "$FIXTURE/recovery-inactive"
elif [[ $1 == start && $2 == t3code-recovery.service ]]; then rm -f "$FIXTURE/recovery-inactive"
elif [[ $1 == stop && $2 == window.service ]]; then
  kill "$(cat "$FIXTURE/holder-pid")"; rm -f "$FIXTURE/holder-pid"
  [[ ${FIXTURE_STOP_LOST_ACK:-0} != 1 ]] || exit 1
else exit 1; fi
SH
cat > "$tmp/bin/podman" <<'SH'
#!/usr/bin/env bash
case "$*" in
  'exec fixture systemctl show t3code-server.service -p MainPID --value') echo "${SERVER_PID:-1234}"; exit ;;
  'exec fixture systemctl show t3code-server.service -p ActiveEnterTimestampMonotonic --value') echo 5678; exit ;;
esac
if [[ $1 == image && $2 == inspect ]]; then
  if [[ -f $FIXTURE/alias-image ]]; then cat "$FIXTURE/alias-image"; else printf 'sha256:%s\n' "${ALIAS_IMAGE:-$EXPECTED_IMAGE}"; fi
  exit
fi
if [[ $1 == tag ]]; then
  printf 'tag\n' >> "$FIXTURE/podman.events"
  [[ ${FIXTURE_TAG_NO_EFFECT:-0} != 1 ]] || exit 1
  printf '%s\n' "$2" > "$FIXTURE/alias-image"
  [[ ${FIXTURE_TAG_LOST_ACK:-0} != 1 ]] || exit 1
  exit
fi
case "$1 $3 ${4:-}" in
  'inspect --format {{.Id}} {{.Image}} {{.State.StartedAt}}') printf '%064d sha256:%s started\n' 1 "$EXPECTED_IMAGE" ;;
  'inspect --format {{.Image}}') printf 'sha256:%s\n' "$EXPECTED_IMAGE" ;;
  'inspect --format {{.State.Health.Status}}') printf 'healthy\n' ;;
  'exec readlink -f') printf '%s\n' "$EXPECTED_TOOLING_PATH" ;;
  'exec cat '*) printf '{"revision":"%s"}\n' "$EXPECTED_AGENT_REVISION" ;;
  'exec stat -Lc') stat -Lc '%i' "$PROVIDER_SECRETS_FILE" ;;
  'exec systemctl is-active'|'exec curl -fsS'|'exec sh -c') exit 0 ;;
  *) exit 1 ;;
esac
SH
cat > "$tmp/bin/systemd-run" <<'SH'
#!/usr/bin/env bash
while [[ $1 != -- ]]; do shift; done
shift
if [[ ${FIXTURE_NO_HANDSHAKE:-0} == 1 ]]; then
  sleep 8 3<&- 6<&- 7<&- 8<&- >/dev/null 2>&1 &
else
  "$@" 3<&- 6<&- 7<&- 8<&- >/dev/null 2>&1 &
fi
printf "%s\n" "$!" > "$FIXTURE/holder-pid"
SH
chmod +x "$tmp/bin/"*
export WINDOW_BOOTSTRAP="$repo/packages/t3code/window-bootstrap.sh"
EXPECTED_IMAGE=$(printf '%064d' 2); EXPECTED_DEPLOYMENT=$(printf '%064d' 3); JQ_BIN=$(command -v jq)
export EXPECTED_IMAGE EXPECTED_DEPLOYMENT JQ_BIN
export HOME_DIR="$tmp/home" ACCEPTED_IMAGE_REF=fixture:accepted
export EXPECTED_AGENT_REVISION=fixture EXPECTED_TOOLING_PATH="$tmp/tooling" PROVIDER_SECRETS_FILE="$tmp/secrets" CURRENT_SYSTEM="$tmp/current-system" EXPECTED_SYSTEM="$tmp/system" CANDIDATE_HOME_TARGET=/home/fixture
mkdir -p "$HOME_DIR/.local/state/t3code-tool-update" "$HOME_DIR/.local/state/t3code-shared-agents" "$HOME_DIR/.local/share/t3code-tools/t3"
touch "$HOME_DIR/.local/state/t3code-tool-update/tool-update.lock" "$HOME_DIR/.local/state/t3code-shared-agents/refresh.lock" "$HOME_DIR/.local/share/t3code-tools/t3/update.lock"
mkdir -p "$tmp/system" "$tmp/tooling"; printf 'fixture\n' > "$PROVIDER_SECRETS_FILE"; ln -s "$tmp/system" "$CURRENT_SYSTEM"
export FIXTURE="$tmp" WINDOW_CONFIG="$tmp/config" WINDOW_INTENT_HELPER="$repo/packages/t3code/window-intent.sh" STATE_DIR="$tmp/state" SYSTEMCTL_BIN="$tmp/bin/systemctl" PODMAN_BIN="$tmp/bin/podman" PODMAN_TARGET=fixture WINDOW_UNIT=window HOLD_FILE="$tmp/hold" LOCK_CANDIDATE="$tmp/candidate.lock" LOCK_HARDENING="$tmp/hardening.lock" PROFILE="$tmp/profile" SYSTEMD_RUN_BIN="$tmp/bin/systemd-run" WINDOW_SECONDS=100
cmd=(bash "$repo/packages/t3code/release-window.sh")
# Preflight reads the actual lock files and ignores unrelated fixture locks.
mkdir -p "$tmp/evidence/old"
: > "$tmp/evidence/old/complete.lock"
for lock in "$tmp/candidate.lock" "$tmp/hardening.lock" "$tmp/state/deploy.lock" "$tmp/evidence/window.lock" "$tmp/evidence/old/complete.lock"; do
  exec 6>"$lock"; flock -x 6
  if "${cmd[@]}" preflight; then echo "accepted held $lock" >&2; exit 1; fi
  flock -u 6; exec 6>&-
done
: > "$tmp/other.lock"; exec 6>"$tmp/other.lock"; flock -x 6
"${cmd[@]}" preflight
flock -u 6; exec 6>&-
# A failed oneshot is not a running writer; its failure remains recorded.
export FIXTURE_DEPLOY_FAILED=1
"${cmd[@]}" preflight
unset FIXTURE_DEPLOY_FAILED
# ActiveState without a lock-holding handshake must not stop recovery.
export FIXTURE_NO_HANDSHAKE=1
if "${cmd[@]}" start failed-holder; then echo 'accepted holder without handshake' >&2; exit 1; fi
[[ ! -e $tmp/recovery-inactive && ! -e $tmp/hold ]]
kill "$(cat "$tmp/holder-pid")"; rm -f "$tmp/holder-pid" "$tmp/evidence/active-window"
unset FIXTURE_NO_HANDSHAKE
# A candidate closure can preflight before first installation without touching
# the missing evidence root. Start creates it only after the checks pass.
mv "$tmp/evidence" "$tmp/old-evidence"
exec 6>"$tmp/candidate.lock"; flock -x 6
if "${cmd[@]}" start refused; then echo 'accepted existing candidate writer' >&2; exit 1; fi
[[ ! -e $tmp/evidence && ! -e $tmp/hold ]]
flock -u 6; exec 6>&-
touch "$tmp/hold"
if "${cmd[@]}" preflight; then echo 'accepted existing recovery hold' >&2; exit 1; fi
rm "$tmp/hold"
[[ ! -e $tmp/evidence ]]
"${cmd[@]}" preflight
[[ ! -e $tmp/evidence ]]
"${cmd[@]}" start one
[[ $(head -1 "$tmp/evidence/one/window.start") == *acquired_by=* ]]
[[ $(sed -n '2p' "$tmp/evidence/one/window.start") == holder_pid=* ]]
# A live shared writer causes an immediate refusal, never a forced clear.
exec 4<"$tmp/evidence/window.lock"; flock -s 4
if "${cmd[@]}" end-no-activation 4<&-; then echo 'accepted a concurrent window writer' >&2; exit 1; fi
[[ -e $tmp/hold && -e $tmp/evidence/active-window ]]
flock -u 4; exec 4<&-
# An announced deploy, including one that crashes, must refuse end.
bash -c 'source "$WINDOW_INTENT_HELPER"; announce_intent deploy; exit 99' || [[ $? == 99 ]]
if "${cmd[@]}" end-no-activation; then echo 'accepted deploy intent' >&2; exit 1; fi
rm "$tmp/evidence/one/"effect-intent.*
touch "$tmp/evidence/one/complete.started"
if "${cmd[@]}" end-no-activation; then echo 'accepted switch intent' >&2; exit 1; fi
rm "$tmp/evidence/one/complete.started"
export FIXTURE_DEPLOY_FAILED=1
if "${cmd[@]}" end-no-activation; then echo 'accepted a failed deployment' >&2; exit 1; fi
unset FIXTURE_DEPLOY_FAILED
mv "$tmp/evidence/one/window.start" "$tmp/saved"
if "${cmd[@]}" end-no-activation; then echo 'accepted missing record' >&2; exit 1; fi
mv "$tmp/saved" "$tmp/evidence/one/window.start"
printf 'changed\n' > "$tmp/state/desired"
if "${cmd[@]}" end-no-activation; then echo 'accepted changed state' >&2; exit 1; fi
printf 'old\n' > "$tmp/state/desired"
"${cmd[@]}" end-no-activation
"${cmd[@]}" start two
"${cmd[@]}" switch -- true
if "${cmd[@]}" end-no-activation; then echo 'accepted announced switch' >&2; exit 1; fi
[[ -f "$tmp/evidence/two/complete.started" ]]
compgen -G "$tmp/evidence/two/effect-intent.switch.*" >/dev/null
# Post refuses an absent receipt and an unknown attempt, and only passes after
# exact receipt, deployed state, live image, tooling and secret all agree.
ln -sfn "$tmp/system" "$tmp/profile"
printf '%s\n' "$EXPECTED_DEPLOYMENT" > "$STATE_DIR/desired"
printf '%s\n' "$EXPECTED_DEPLOYMENT" > "$STATE_DIR/applied"
mkdir -p "$STATE_DIR/receipts" "$STATE_DIR/attempts"
if "${cmd[@]}" post; then echo 'accepted missing receipt' >&2; exit 1; fi
inode=$(stat -Lc %i "$PROVIDER_SECRETS_FILE")
jq -n --arg d "$EXPECTED_DEPLOYMENT" --arg i "$EXPECTED_IMAGE" --arg a "$EXPECTED_AGENT_REVISION" --arg p "$EXPECTED_TOOLING_PATH" --arg s "$inode" '{deployment_id:$d,image_id:$i,candidate_name:"t3code-candidate-fixture",agent_revision:$a,agent_path:$p,provider_secret_inode:$s,live_before:{id:"fixture"},live_after:{id:"fixture"},checks:{app_ready:true,provider_turn:true,agent_cli:true,skills:true,desktop_transport:true}}' > "$STATE_DIR/receipts/$EXPECTED_DEPLOYMENT.json"
printf '{"deployment_id":"%s","exit_code":77,"outcome":"route_unknown","started_at_ms":%s}\n' "$EXPECTED_DEPLOYMENT" "$(date +%s%3N)" > "$STATE_DIR/attempts/$EXPECTED_DEPLOYMENT.json"
if "${cmd[@]}" post; then echo 'accepted unknown attempt' >&2; exit 1; fi
printf '{"deployment_id":"%s","exit_code":0,"started_at_ms":1}\n' "$EXPECTED_DEPLOYMENT" > "$STATE_DIR/attempts/$EXPECTED_DEPLOYMENT.json"
if "${cmd[@]}" post; then echo 'accepted stale attempt' >&2; exit 1; fi
printf '{"deployment_id":"%s","exit_code":0,"started_at_ms":%s}\n' "$EXPECTED_DEPLOYMENT" "$(date +%s%3N)" > "$STATE_DIR/attempts/$EXPECTED_DEPLOYMENT.json"
# A receipted activation may restart the server; post validates the resulting
# image and inputs rather than claiming that the old PID survived.
export SERVER_PID=5678
"${cmd[@]}" post
export FIXTURE_STOP_LOST_ACK=1
if "${cmd[@]}" end-post two; then echo 'unexpected post stop acknowledgement' >&2; exit 1; fi
[[ -f $tmp/evidence/two/post.verified && -f $tmp/evidence/active-window && -f $tmp/hold ]]
unset FIXTURE_STOP_LOST_ACK
"${cmd[@]}" end-post two
"${cmd[@]}" end-post two
unset SERVER_PID
[[ ! -e $tmp/hold && ! -e $tmp/evidence/active-window ]]
cp "$STATE_DIR/receipts/$EXPECTED_DEPLOYMENT.json" "$tmp/known-good.json"
# A switch can exit nonzero after changing the system. A stale attempt is not
# a post proof; a later completed attempt and existing exact receipt are.
"${cmd[@]}" start late
sleep 0.02
# shellcheck disable=SC2016
if "${cmd[@]}" switch -- bash -c 'touch "$1"; exit 4' _ "$tmp/switch-effect"; then echo 'accepted failed switch' >&2; exit 1; fi
[[ -e $tmp/switch-effect ]]
if "${cmd[@]}" post; then echo 'accepted attempt from before switch' >&2; exit 1; fi
printf '{"deployment_id":"%s","exit_code":0,"started_at_ms":%s}\n' "$EXPECTED_DEPLOYMENT" "$(date +%s%3N)" > "$STATE_DIR/attempts/$EXPECTED_DEPLOYMENT.json"
"${cmd[@]}" post
"${cmd[@]}" end-post late
# Existing exact receipt permits a no-restart known-good return despite split state.
"${cmd[@]}" start three
"${cmd[@]}" switch -- true
new_desired=$(printf '%064d' 4)
printf '%s\n' "$new_desired" > "$STATE_DIR/desired"
printf '{"deployment_id":"%s","exit_code":77,"outcome":"route_unknown"}\n' "$new_desired" > "$STATE_DIR/attempts/$new_desired.json"
if "${cmd[@]}" end-unknown; then echo 'accepted UNKNOWN with a matching receipt' >&2; exit 1; fi
ALIAS_IMAGE=$(printf '%064d' 9); export ALIAS_IMAGE
mv "$STATE_DIR/receipts/$EXPECTED_DEPLOYMENT.json" "$tmp/receipt-held"
if "${cmd[@]}" rollback; then echo 'restored alias without a receipt' >&2; exit 1; fi
[[ ! -e $tmp/podman.events ]]
mv "$tmp/receipt-held" "$STATE_DIR/receipts/$EXPECTED_DEPLOYMENT.json"
export FIXTURE_TAG_NO_EFFECT=1
if "${cmd[@]}" rollback three; then echo 'accepted unknown alias restore' >&2; exit 1; fi
[[ -f $tmp/evidence/three/alias-restore.started && -e $tmp/hold ]]
unset FIXTURE_TAG_NO_EFFECT
export FIXTURE_TAG_LOST_ACK=1
export FIXTURE_STOP_LOST_ACK=1
if "${cmd[@]}" rollback three; then echo 'unexpected rollback stop acknowledgement' >&2; exit 1; fi
[[ -f $tmp/evidence/three/known-good.json && -f $tmp/evidence/active-window && -f $tmp/hold ]]
[[ $(cat "$tmp/alias-image") == "sha256:$EXPECTED_IMAGE" && $(wc -l < "$tmp/podman.events") == 2 ]]
unset FIXTURE_TAG_LOST_ACK FIXTURE_STOP_LOST_ACK ALIAS_IMAGE
"${cmd[@]}" rollback three
"${cmd[@]}" rollback three
[[ $(wc -l < "$tmp/podman.events") == 2 ]]
[[ ! -e $tmp/hold && ! -e $tmp/evidence/active-window ]]
jq -e --arg d "$new_desired" --arg a "$EXPECTED_DEPLOYMENT" '.state == "KNOWN_GOOD_SERVING" and .desired == $d and .applied == $a' "$tmp/evidence/three/known-good.json" >/dev/null
# Without a receipt, a changed server or a queued restart must refuse release.
"${cmd[@]}" start four
rm "$STATE_DIR/receipts/$EXPECTED_DEPLOYMENT.json"
for lock in "$HOME_DIR/.local/state/t3code-tool-update/tool-update.lock" "$HOME_DIR/.local/state/t3code-shared-agents/refresh.lock" "$HOME_DIR/.local/share/t3code-tools/t3/update.lock"; do
  exec 4>"$lock"; flock -x 4
  if "${cmd[@]}" end-unknown 4>&-; then echo 'accepted a managed writer' >&2; exit 1; fi
  [[ -e $tmp/hold && -e $tmp/evidence/active-window && ! -e $STATE_DIR/recovery-unknown.json ]]
  flock -u 4; exec 4>&-
done
export SERVER_PID=999
if "${cmd[@]}" end-unknown; then echo 'accepted changed serving identity' >&2; exit 1; fi
unset SERVER_PID
mkdir -p "$HOME_DIR/.local/state/t3code-tool-update"
touch "$HOME_DIR/.local/state/t3code-tool-update/restart.pending"
if "${cmd[@]}" end-unknown; then echo 'accepted pending restart' >&2; exit 1; fi
rm "$HOME_DIR/.local/state/t3code-tool-update/restart.pending"
# The holder may stop while its acknowledgement is lost. The durable UNKNOWN
# record lets a retry finish releasing the window without inventing success.
export FIXTURE_STOP_LOST_ACK=1
if "${cmd[@]}" end-unknown; then echo 'unexpected stop acknowledgement' >&2; exit 1; fi
[[ -f $STATE_DIR/recovery-unknown.json && -e $tmp/evidence/active-window && -e $tmp/hold ]]
unset FIXTURE_STOP_LOST_ACK
set +e
"${cmd[@]}" end-unknown
unknown_rc=$?
set -e
[[ $unknown_rc == 77 && -e $tmp/hold && ! -e $tmp/evidence/active-window ]]
jq -e --arg d "$new_desired" --arg a "$EXPECTED_DEPLOYMENT" '.state == "UNKNOWN" and .reason == "route_unknown" and .desired == $d and .applied == $a and .receipt == "absent" and .recovery_inhibit == "retained" and .clear_command == "ghostship-t3code-release-window resolve-unknown"' "$STATE_DIR/recovery-unknown.json" >/dev/null
set +e
"${cmd[@]}" end-unknown
replay_rc=$?
set -e
[[ $replay_rc == 77 ]]
if "${cmd[@]}" resolve-unknown; then echo 'cleared inhibit without receipt' >&2; exit 1; fi
cp "$tmp/known-good.json" "$STATE_DIR/receipts/$EXPECTED_DEPLOYMENT.json"
"${cmd[@]}" resolve-unknown
[[ ! -e $tmp/hold && ! -e $STATE_DIR/recovery-unknown.json ]]
# A definitive candidate failure also exits UNKNOWN when the serving inputs
# have no receipt, but its failed marker survives release and investigation.
"${cmd[@]}" start five
"${cmd[@]}" switch -- true
failed_desired=$(printf '%064d' 5)
failed_key="$failed_desired $(printf '%064d' 6)"
printf '%s\n' "$failed_desired" > "$STATE_DIR/desired"
printf '{"deployment_id":"%s","exit_code":1}\n' "$failed_desired" > "$STATE_DIR/attempts/$failed_desired.json"
printf '%s\n' "$failed_key" > "$STATE_DIR/failed-candidate"
rm "$STATE_DIR/receipts/$EXPECTED_DEPLOYMENT.json"
set +e
"${cmd[@]}" end-unknown
failure_rc=$?
set -e
[[ $failure_rc == 77 && -e $tmp/hold && ! -e $tmp/evidence/active-window ]]
[[ $(cat "$STATE_DIR/failed-candidate") == "$failed_key" ]]
jq -e --arg d "$failed_desired" '.state == "UNKNOWN" and .reason == "candidate_failed" and .desired == $d and .receipt == "absent" and .recovery_inhibit == "retained"' "$STATE_DIR/recovery-unknown.json" >/dev/null
# Automatic writers must not change desired state or restart while UNKNOWN is
# unresolved. Use copies and the same fixture-only state and stubs.
cp "$repo/packages/t3code/activate-deployment.sh" "$tmp/fixture-activate-writer"
cp "$repo/packages/t3code/deploy-image.sh" "$tmp/fixture-image-writer"
export DEPLOYMENT_ID="$EXPECTED_DEPLOYMENT" AGENT_REVISION="$EXPECTED_AGENT_REVISION" TOOLING_PATH="$EXPECTED_TOOLING_PATH"
for writer in "$tmp/fixture-activate-writer" "$tmp/fixture-image-writer"; do
  set +e
  bash "$writer" > "$tmp/writer.out" 2>&1
  writer_rc=$?
  set -e
  [[ $writer_rc == 77 && $(cat "$STATE_DIR/desired") == "$failed_desired" ]]
done
cp "$tmp/known-good.json" "$STATE_DIR/receipts/$EXPECTED_DEPLOYMENT.json"
"${cmd[@]}" resolve-unknown
[[ $(cat "$STATE_DIR/failed-candidate") == "$failed_key" ]]
# Route-unavailable is also an unreceipted outcome, not an implicit PASS.
"${cmd[@]}" start six
unavailable_desired=$(printf '%064d' 7)
printf '%s\n' "$unavailable_desired" > "$STATE_DIR/desired"
printf '{"deployment_id":"%s","exit_code":76,"outcome":"route_unavailable"}\n' "$unavailable_desired" > "$STATE_DIR/attempts/$unavailable_desired.json"
rm "$STATE_DIR/receipts/$EXPECTED_DEPLOYMENT.json"
set +e
"${cmd[@]}" end-unknown
unavailable_rc=$?
set -e
[[ $unavailable_rc == 77 && $(cat "$STATE_DIR/failed-candidate") == "$failed_key" ]]
jq -e '.state == "UNKNOWN" and .reason == "route_unavailable" and .recovery_inhibit == "retained"' "$STATE_DIR/recovery-unknown.json" >/dev/null
cp "$tmp/known-good.json" "$STATE_DIR/receipts/$EXPECTED_DEPLOYMENT.json"
"${cmd[@]}" resolve-unknown
[[ $(cat "$STATE_DIR/failed-candidate") == "$failed_key" ]]
# A failed-forward deployment unit is not a concurrent writer. If a switch
# exits after an effect and no candidate attempt or receipt can be established,
# release with explicit UNKNOWN and preserve the previous failed marker.
export FIXTURE_DEPLOY_FAILED=1
"${cmd[@]}" start seven
unknown_desired=$(printf '%064d' 8)
printf '%s\n' "$unknown_desired" > "$STATE_DIR/desired"
rm "$STATE_DIR/receipts/$EXPECTED_DEPLOYMENT.json"
# shellcheck disable=SC2016
if "${cmd[@]}" switch -- bash -c 'touch "$1"; exit 4' _ "$tmp/unknown-effect"; then echo 'accepted failed switch' >&2; exit 1; fi
[[ -f $tmp/unknown-effect && $(cat "$tmp/evidence/seven/switch.result") == exit_code=4 ]]
set +e
"${cmd[@]}" end-unknown
switch_unknown_rc=$?
set -e
[[ $switch_unknown_rc == 77 && -e $tmp/hold && ! -e $tmp/evidence/active-window ]]
jq -e --arg d "$unknown_desired" '.state == "UNKNOWN" and .reason == "switch_unknown" and .desired == $d and .recovery_inhibit == "retained"' "$STATE_DIR/recovery-unknown.json" >/dev/null
cp "$tmp/known-good.json" "$STATE_DIR/receipts/$EXPECTED_DEPLOYMENT.json"
"${cmd[@]}" resolve-unknown
unset FIXTURE_DEPLOY_FAILED
[[ $(cat "$STATE_DIR/failed-candidate") == "$failed_key" ]]
# An expired legacy holder can hand its existing inhibit to a new window. The
# handoff does not assert that the old window had no effects.
export LEGACY_DIR="$tmp/legacy" LEGACY_UNIT=legacy
mkdir -p "$LEGACY_DIR"
printf '%s\n' "$(( $(date +%s) - 100 ))" > "$LEGACY_DIR/window.opened"
printf '%s\n' "$(( $(date +%s) - 1 ))" > "$LEGACY_DIR/window.until"
touch "$LEGACY_DIR/complete.lock" "$LEGACY_DIR/complete.started" "$tmp/hold"
hold_inode=$(stat -c %i "$tmp/hold")
rm "$STATE_DIR/receipts/$EXPECTED_DEPLOYMENT.json"
exec 3>"$LEGACY_DIR/complete.lock"; flock -x 3
if "${cmd[@]}" preflight --adopt-inhibit 3>&-; then echo 'accepted concurrent legacy writer' >&2; exit 1; fi
flock -u 3; exec 3>&-
"${cmd[@]}" preflight --adopt-inhibit
"${cmd[@]}" start --adopt-inhibit legacy-adopted
[[ $(stat -c %i "$tmp/hold") == "$hold_inode" ]]
grep -q 'complete_started=present' "$tmp/evidence/legacy-adopted/legacy.adopted"
if "${cmd[@]}" end-no-activation; then echo 'claimed no effects in legacy window' >&2; exit 1; fi
set +e
"${cmd[@]}" end-unknown
legacy_unknown_rc=$?
set -e
[[ $legacy_unknown_rc == 77 && -e $tmp/hold && ! -e $tmp/evidence/active-window ]]
jq -e '.state == "UNKNOWN" and .reason == "legacy_unknown" and .recovery_inhibit == "retained"' "$STATE_DIR/recovery-unknown.json" >/dev/null
cp "$tmp/known-good.json" "$STATE_DIR/receipts/$EXPECTED_DEPLOYMENT.json"
"${cmd[@]}" resolve-unknown
if grep -q '^restart ' "$tmp/systemctl.events"; then echo 'unexpected restart' >&2; exit 1; fi
echo 'Release window refusal and reopen fixture passed.'
