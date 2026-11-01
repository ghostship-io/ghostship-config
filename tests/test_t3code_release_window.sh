#!/usr/bin/env bash
set -euo pipefail
repo=$(cd "$(dirname "$0")/.." && pwd)
tmp=$(mktemp -d); trap '[[ ! -f $tmp/holder-pid ]] || kill "$(cat "$tmp/holder-pid")" 2>/dev/null || true; [[ ! -f $tmp/competitor-pid ]] || kill "$(cat "$tmp/competitor-pid")" 2>/dev/null || true; rm -rf "$tmp"' EXIT
mkdir -p "$tmp/evidence" "$tmp/state" "$tmp/bin"
printf '%s\n' "$tmp/evidence" > "$tmp/config"
touch "$tmp/evidence/window.lock" "$tmp/state/deploy.lock" "$tmp/candidate.lock" "$tmp/hardening.lock"
printf 'old\n' > "$tmp/state/applied"; cp "$tmp/state/applied" "$tmp/state/desired"
ln -s "$tmp/system" "$tmp/profile"
cat > "$tmp/bin/systemctl" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$FIXTURE/systemctl.events"
if [[ $1 == --failed ]]; then cat "$FIXTURE/failed-units" 2>/dev/null; exit 0; fi
if [[ $1 == show ]]; then
  if [[ $2 == ghostship-t3code-deploy.service && $3 == -p && $4 == Result ]]; then echo "${FIXTURE_DEPLOY_RESULT:-success}"; exit; fi
  if [[ $2 == window.service && $3 == -p && $4 == MainPID ]]; then cat "$FIXTURE/holder-pid"; exit; fi
  case $2 in window.service) [[ -f $FIXTURE/holder-pid ]] && kill -0 "$(cat "$FIXTURE/holder-pid")" 2>/dev/null && echo active || echo inactive ;; t3code-recovery.service) [[ -e $FIXTURE/recovery-inactive ]] && echo inactive || echo active ;; ghostship-t3code-deploy.service) [[ ${FIXTURE_DEPLOY_FAILED:-0} == 1 ]] && echo failed || echo inactive ;; podman-t3code.service) [[ -e $FIXTURE/container-stopped ]] && echo inactive || echo active ;; *) echo inactive ;; esac
elif [[ $1 == stop && $2 == t3code-recovery.service ]]; then touch "$FIXTURE/recovery-inactive"
elif [[ $1 == start && $2 == t3code-recovery.service ]]; then rm -f "$FIXTURE/recovery-inactive"
elif [[ $1 == start && $2 == podman-t3code.service ]]; then rm -f "$FIXTURE/container-stopped"
elif [[ $1 == stop && $2 == podman-t3code.service ]]; then touch "$FIXTURE/container-stopped"
elif [[ $1 == stop && $2 == window.service ]]; then
  kill "$(cat "$FIXTURE/holder-pid")"; rm -f "$FIXTURE/holder-pid"
  if [[ ${FIXTURE_COMPETE_AFTER_STOP:-0} == 1 ]]; then
    setsid bash -c 'exec 6<"$1"; flock -x 6; touch "$2"; exec sleep 30' _ "$LOCK_CANDIDATE" "$FIXTURE/competitor-ready" 3<&- 4<&- 5<&- 6<&- 7<&- 8<&- 9<&- 10<&- 11<&- >/dev/null 2>&1 &
    printf '%s\n' "$!" > "$FIXTURE/competitor-pid"
    for _ in {1..100}; do [[ -f $FIXTURE/competitor-ready ]] && break; sleep .02; done
    [[ -f $FIXTURE/competitor-ready ]] || exit 1
  fi
  [[ ${FIXTURE_STOP_LOST_ACK:-0} != 1 ]] || exit 1
else exit 1; fi
SH
cat > "$tmp/bin/podman" <<'SH'
#!/usr/bin/env bash
if [[ -e $FIXTURE/container-stopped ]]; then
  if [[ $1 == inspect && $3 == '{{.State.Running}}' ]]; then echo false; exit; fi
  if [[ $1 == inspect && $3 == '{{.State.Health.Status}}' ]]; then echo unhealthy; exit; fi
  if [[ $1 == inspect && $3 == '{{.Id}} {{.Image}} {{.State.StartedAt}}' ]]; then exit 1; fi
  if [[ $1 == exec ]]; then echo 'container is not running' >&2; exit 1; fi
fi
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
# Container marker check: the tool runs `sh -c 'for f in $1; ...' _ MARKERS`
# inside the container. Interpret the markers against a fixture directory so the
# container half of the deferral tolerance is actually exercised.
if [[ $1 == exec && $3 == sh && ${4:-} == -c && ${6:-} == _ ]]; then
  for f in ${7:-}; do
    rel=${f#/run/t3code-tool-update/}
    [[ ! -e $FIXTURE/container-run/$rel ]] || exit 1
  done
  exit 0
fi
case "$1 $3 ${4:-}" in
  'inspect --format {{.State.Running}}') echo true ;;
  'inspect --format {{.Id}} {{.Image}} {{.State.StartedAt}}') [[ ${FIXTURE_SERVING_BROKEN:-0} != 1 ]] || { printf 'broken\n'; exit 0; }; printf '%064d sha256:%s started\n' 1 "$EXPECTED_IMAGE" ;;
  'inspect --format {{.Image}}') printf 'sha256:%s\n' "$EXPECTED_IMAGE" ;;
  'inspect --format {{.Id}}') printf '%064d\n' 1 ;;
  'inspect --format {{.State.Health.Status}}') printf 'healthy\n' ;;
  'exec readlink -f') printf '%s\n' "$EXPECTED_TOOLING_PATH" ;;
  'exec cat '*) printf '{"revision":"%s"}\n' "${FIXTURE_RELEASE_REVISION:-$EXPECTED_AGENT_REVISION}" ;;
  'exec stat -Lc') if [[ -n ${FIXTURE_CONTAINER_INODE:-} ]]; then printf '%s\n' "$FIXTURE_CONTAINER_INODE"; else stat -Lc '%i' "$PROVIDER_SECRETS_FILE"; fi ;;
  'exec sha256sum '*) if [[ ${FIXTURE_SECRET_MISMATCH:-0} == 1 ]]; then printf '%064d  /run/secrets/t3code.env\n' 0; else sha256sum "$PROVIDER_SECRETS_FILE"; fi ;;
  'exec systemctl is-active'|'exec curl -fsS'|'exec sh -c') exit 0 ;;
  *) exit 1 ;;
esac
SH
cat > "$tmp/bin/su-exec" <<'SH'
#!/usr/bin/env bash
shift
exec "$@"
SH
cat > "$tmp/bin/systemd-run" <<'SH'
#!/usr/bin/env bash
while [[ $1 != -- ]]; do shift; done
shift
if [[ ${FIXTURE_NO_HANDSHAKE:-0} == 1 ]]; then
  sleep 8 3<&- 6<&- 7<&- 8<&- >/dev/null 2>&1 &
else
  # Reproduce the systemd manager's environment: no inherited PATH. A command
  # that relies on PATH lookup fails here exactly as it did on the host.
  /usr/bin/env -i PATH=/nonexistent "$@" 3<&- 6<&- 7<&- 8<&- >/dev/null 2>&1 &
fi
printf "%s\n" "$!" > "$FIXTURE/holder-pid"
SH
cat > "$tmp/bin/journalctl" <<'SH'
#!/usr/bin/env bash
case " $* " in
  *" -o json "*) cat "$FIXTURE/journal-activation.jsonl" 2>/dev/null; exit 0 ;;
esac
unit=
args=("$@")
for ((i = 0; i < ${#args[@]}; i++)); do
  [[ ${args[i]} == -u ]] && unit=${args[i + 1]}
done
[[ -n $unit ]] || exit 0
while IFS=$'\t' read -r u first last; do
  [[ $u == "$unit" ]] || continue
  [[ -n $first ]] && printf '%s host %s: Failed with result '"'"'exit-code'"'"'.\n' "$first" "$unit"
  if [[ -n $last && $last != "$first" ]]; then printf '%s host %s: Failed with result '"'"'exit-code'"'"'.\n' "$last" "$unit"; fi
done < "$FIXTURE/journal-first"
exit 0
SH
chmod +x "$tmp/bin/"*
export SUEXEC_BIN="$tmp/bin/su-exec"
export WINDOW_BOOTSTRAP="$repo/packages/t3code/window-bootstrap.sh"
EXPECTED_IMAGE=$(printf '%064d' 2); EXPECTED_DEPLOYMENT=$(printf '%064d' 3); JQ_BIN=$(command -v jq)
export EXPECTED_IMAGE EXPECTED_DEPLOYMENT JQ_BIN
export HOME_DIR="$tmp/home" ACCEPTED_IMAGE_REF=fixture:accepted
export COREUTILS_BIN="$(dirname "$(command -v mv)")" UTIL_LINUX_BIN="$(dirname "$(command -v flock)")" BASH_BIN="$(command -v bash)"
# Drive the real holder body the way the packaged wrapper does: absolute
# interpreter plus the PATH its runtimeInputs supply. Neither a `/usr/bin/env`
# shebang nor a bare `flock` survives the no-PATH environment it runs in.
cat > "$tmp/window-holder.sh" <<HOLDER
#!$BASH_BIN
export PATH="$COREUTILS_BIN:$UTIL_LINUX_BIN"
exec "$BASH_BIN" "$repo/packages/t3code/window-holder.sh" "\$@"
HOLDER
chmod +x "$tmp/window-holder.sh"
export WINDOW_HOLDER_BIN="$tmp/window-holder.sh"
export EXPECTED_AGENT_REVISION=fixture EXPECTED_TOOLING_PATH="$tmp/tooling" PROVIDER_SECRETS_FILE="$tmp/secrets" CURRENT_SYSTEM="$tmp/current-system" EXPECTED_SYSTEM="$tmp/system" CANDIDATE_HOME_TARGET=/home/fixture
mkdir -p "$HOME_DIR/.local/state/t3code-tool-update" "$HOME_DIR/.local/state/t3code-shared-agents" "$HOME_DIR/.local/share/t3code-tools/t3"
touch "$HOME_DIR/.local/state/t3code-tool-update/tool-update.lock" "$HOME_DIR/.local/state/t3code-shared-agents/refresh.lock" "$HOME_DIR/.local/share/t3code-tools/t3/update.lock"
mkdir -p "$tmp/system" "$tmp/tooling"; printf 'fixture\n' > "$PROVIDER_SECRETS_FILE"; ln -s "$tmp/system" "$CURRENT_SYSTEM"
# The active generation's deploy unit is where a switch binds the identity it
# installed; recovery reads it from the window, never from the caller.
# Model the real generation: the unit path is a symlink into the units
# directory, not a regular file.
mkdir -p "$tmp/system/etc/systemd/system" "$tmp/units"
printf 'Environment="AGENT_REVISION=fixture" "TOOLING_PATH=%s"\n' "$tmp/tooling" > "$tmp/units/ghostship-t3code-deploy.service"
ln -s "$tmp/units/ghostship-t3code-deploy.service" "$tmp/system/etc/systemd/system/ghostship-t3code-deploy.service"
# A second generation with a different identity: an overridden PROFILE must not
# be able to point binding at it.
mkdir -p "$tmp/other-generation/etc/systemd/system" "$tmp/other-units"
printf 'Environment="AGENT_REVISION=other" "TOOLING_PATH=/other/tooling"\n' > "$tmp/other-units/deploy.service"
ln -s "$tmp/other-units/deploy.service" "$tmp/other-generation/etc/systemd/system/ghostship-t3code-deploy.service"
export FIXTURE="$tmp" WINDOW_CONFIG="$tmp/config" WINDOW_INTENT_HELPER="$repo/packages/t3code/window-intent.sh" STATE_DIR="$tmp/state" SYSTEMCTL_BIN="$tmp/bin/systemctl" PODMAN_BIN="$tmp/bin/podman" PODMAN_TARGET=fixture WINDOW_UNIT=window HOLD_FILE="$tmp/hold" LOCK_CANDIDATE="$tmp/candidate.lock" LOCK_HARDENING="$tmp/hardening.lock" PROFILE="$tmp/profile" SYSTEMD_RUN_BIN="$tmp/bin/systemd-run" WINDOW_SECONDS=100
fixture_window="$tmp/fixture-window-command"
cp "$repo/packages/t3code/release-window.sh" "$fixture_window"
cp "$repo/packages/t3code/receipt-checks.sh" "$tmp/receipt-checks.sh"
cmd=(bash "$fixture_window")
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
kill "$(cat "$tmp/holder-pid")"; rm -f "$tmp/holder-pid"
unset FIXTURE_NO_HANDSHAKE
# Holding a window makes the container defer tool updates, so this marker is
# present in exactly the state cancel-start has to close. A real pending restart
# still refuses; the expected deferral must not deadlock the only exit.
deferred="$HOME_DIR/.local/state/t3code-tool-update/update-deferred.pending"
: > "$deferred"
: > "$HOME_DIR/.local/state/t3code-tool-update/restart.pending"
if "${cmd[@]}" cancel-start; then echo 'cancel-start accepted a queued restart' >&2; exit 1; fi
[[ -e $tmp/evidence/active-window ]]
rm -f "$HOME_DIR/.local/state/t3code-tool-update/restart.pending"
# The live failure was the container's own deferral marker, so prove that half
# too: a container restart.pending still refuses, the deferral does not.
mkdir -p "$tmp/container-run"
: > "$tmp/container-run/update-deferred.pending"
: > "$tmp/container-run/restart.pending"
if "${cmd[@]}" cancel-start; then echo 'cancel-start accepted a container restart' >&2; exit 1; fi
[[ -e $tmp/evidence/active-window ]]
rm -f "$tmp/container-run/restart.pending"
"${cmd[@]}" cancel-start
rm -rf "$tmp/container-run"
[[ ! -e $tmp/evidence/active-window && ! -e $tmp/hold ]]
rm -f "$deferred"
# A holder that recorded a bare '$' instead of a PID, exactly as the generator
# did, still belongs to this window's unit: cancel-start must close it rather
# than wait for RuntimeMaxSec.
rm -f "$tmp/hold"
export FIXTURE_NO_HANDSHAKE=1
if "${cmd[@]}" start malformed-holder; then echo 'accepted holder without handshake' >&2; exit 1; fi
unset FIXTURE_NO_HANDSHAKE
printf '%s\n' '$' > "$tmp/evidence/malformed-holder/holder.ready"
"${cmd[@]}" cancel-start
[[ ! -e $tmp/evidence/active-window ]]
rm -f "$tmp/hold"
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
# CURRENT_SYSTEM is caller-supplied for post; binding must not read it.
export CURRENT_SYSTEM=/nonexistent-generation
"${cmd[@]}" start two
PROFILE="$tmp/other-generation" "${cmd[@]}" switch -- true
export CURRENT_SYSTEM="$tmp/current-system"
# The switch bound the installed identity from the now-active generation.
[[ -f "$tmp/evidence/two/declared-target" ]] || { echo 'switch did not bind the installed identity' >&2; exit 1; }
[[ $(cat "$tmp/evidence/two/declared-target") == "fixture $tmp/tooling" ]] || { echo 'switch bound an overridden generation' >&2; exit 1; }
[[ ! -e "$tmp/evidence/two/declared-target.absent" ]] || { echo 'switch bound nothing' >&2; exit 1; }
if "${cmd[@]}" end-no-activation; then echo 'accepted announced switch' >&2; exit 1; fi
[[ -f "$tmp/evidence/two/complete.started" ]]
shopt -s nullglob
intents=("$tmp/evidence/two"/effect-intent.switch.*)
(( ${#intents[@]} > 0 ))
# Post refuses an absent receipt and an unknown attempt, and only passes after
# exact receipt, deployed state, live image, tooling and secret all agree.
ln -sfn "$tmp/system" "$tmp/profile"
printf '%s\n' "$EXPECTED_DEPLOYMENT" > "$STATE_DIR/desired"
printf '%s\n' "$EXPECTED_DEPLOYMENT" > "$STATE_DIR/applied"
mkdir -p "$STATE_DIR/receipts" "$STATE_DIR/attempts"
if "${cmd[@]}" post; then echo 'accepted missing receipt' >&2; exit 1; fi
secret=$(sha256sum < "$PROVIDER_SECRETS_FILE" | cut -d ' ' -f1)
jq -n --arg d "$EXPECTED_DEPLOYMENT" --arg i "$EXPECTED_IMAGE" --arg a "$EXPECTED_AGENT_REVISION" --arg p "$EXPECTED_TOOLING_PATH" --arg s "$secret" '{deployment_id:$d,image_id:$i,candidate_name:"t3code-candidate-fixture",agent_revision:$a,agent_path:$p,provider_secret_sha256:$s,live_before:{id:"fixture"},live_after:{id:"fixture"},checks:{app_ready:true,provider_turn:true,agent_cli:true,skills:true,desktop_cli:true,desktop_transport:true}}' > "$STATE_DIR/receipts/$EXPECTED_DEPLOYMENT.json"
printf '{"deployment_id":"%s","exit_code":77,"outcome":"route_unknown","started_at_ms":%s}\n' "$EXPECTED_DEPLOYMENT" "$(date +%s%3N)" > "$STATE_DIR/attempts/$EXPECTED_DEPLOYMENT.json"
if "${cmd[@]}" post; then echo 'accepted unknown attempt' >&2; exit 1; fi
printf '{"deployment_id":"%s","exit_code":0,"started_at_ms":1}\n' "$EXPECTED_DEPLOYMENT" > "$STATE_DIR/attempts/$EXPECTED_DEPLOYMENT.json"
if "${cmd[@]}" post; then echo 'accepted stale attempt' >&2; exit 1; fi
printf '{"deployment_id":"%s","exit_code":0,"started_at_ms":%s}\n' "$EXPECTED_DEPLOYMENT" "$(date +%s%3N)" > "$STATE_DIR/attempts/$EXPECTED_DEPLOYMENT.json"
# The gen-590 host may not yet have a standalone updater lock. Bootstrap its
# existing path only after holding tool/refresh locks, without replacing it.
rm "$HOME_DIR/.local/share/t3code-tools/t3/update.lock"
export SERVER_PID=5678
export FIXTURE_SECRET_MISMATCH=1
if "${cmd[@]}" post; then echo 'accepted mismatched live secret content' >&2; exit 1; fi
unset FIXTURE_SECRET_MISMATCH
# A failed production turn must refuse the post, leave the window open and the
# known-good rollback path available; a later passing turn releases it.
export PRODUCTION_TURN_COMMAND='exit 1'
if "${cmd[@]}" post 2>"$tmp/production-fail.log"; then echo 'post accepted a failed production turn' >&2; exit 1; fi
grep -q 'production turn failed' "$tmp/production-fail.log" || { echo 'P1: unexpected refusal' >&2; cat "$tmp/production-fail.log" >&2; exit 1; }
[[ ! -e $tmp/evidence/two/post.verified && -e $tmp/hold && -e $tmp/evidence/active-window ]]
jq -e '.claim == "production_turn" and .outcome == "failed"' "$tmp/evidence/two/production-turn.json" >/dev/null
export PRODUCTION_TURN_COMMAND='echo PROBE_PASS'
"${cmd[@]}" post
[[ -f $HOME_DIR/.local/share/t3code-tools/t3/update.lock ]]
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
# A holder that expires after the switch does not make a verified post depend
# on another expiry: recheck the receipt while excluding candidate writers.
kill "$(cat "$tmp/holder-pid")"; rm "$tmp/holder-pid"
for _ in {1..100}; do flock -n "$LOCK_CANDIDATE" true && flock -n "$LOCK_HARDENING" true && break; sleep .05; done
"${cmd[@]}" post
"${cmd[@]}" end-post late
# Existing exact receipt permits a no-restart known-good return despite split state.
"${cmd[@]}" start three
"${cmd[@]}" switch -- true
new_desired=$(printf '%064d' 4)
printf '%s\n' "$new_desired" > "$STATE_DIR/desired"
printf '{"deployment_id":"%s","exit_code":77,"outcome":"route_unknown","started_at_ms":%s}\n' "$new_desired" "$(date +%s%3N)" > "$STATE_DIR/attempts/$new_desired.json"
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
cp "$tmp/known-good.json" "$STATE_DIR/receipts/$EXPECTED_DEPLOYMENT.json"
# Without a receipt, a changed server or a queued restart must refuse release.
"${cmd[@]}" start four
rm "$STATE_DIR/receipts/$EXPECTED_DEPLOYMENT.json"
printf '{"deployment_id":"%s","exit_code":77,"outcome":"route_unknown","started_at_ms":1}\n' "$new_desired" > "$STATE_DIR/attempts/$new_desired.json"
if "${cmd[@]}" end-unknown; then echo 'accepted a stale route result' >&2; exit 1; fi
[[ ! -e $STATE_DIR/recovery-unknown.json ]]
printf '{"deployment_id":"%s","exit_code":77,"outcome":"route_unknown","started_at_ms":%s}\n' "$new_desired" "$(date +%s%3N)" > "$STATE_DIR/attempts/$new_desired.json"
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
# The container half, which is the live shape: holding a window makes the
# container defer tool updates, so that marker must not block an ending, while a
# queued container restart still must.
mkdir -p "$tmp/container-run"
: > "$tmp/container-run/restart.pending"
if "${cmd[@]}" end-unknown; then echo 'accepted a container queued restart' >&2; exit 1; fi
rm -f "$tmp/container-run/restart.pending"
rm -rf "$tmp/container-run"
# The holder may stop while its acknowledgement is lost. The durable UNKNOWN
# record lets a retry finish releasing the window without inventing success.
export FIXTURE_STOP_LOST_ACK=1
export FIXTURE_COMPETE_AFTER_STOP=1
if "${cmd[@]}" end-unknown; then echo 'unexpected stop acknowledgement' >&2; exit 1; fi
[[ -f $STATE_DIR/recovery-unknown.json && -e $tmp/evidence/active-window && -e $tmp/hold ]]
unset FIXTURE_STOP_LOST_ACK FIXTURE_COMPETE_AFTER_STOP
if "${cmd[@]}" end-unknown; then echo 'accepted a concurrent candidate writer' >&2; exit 1; fi
[[ -e $tmp/evidence/active-window && -e $tmp/hold ]]
kill "$(cat "$tmp/competitor-pid")"; rm "$tmp/competitor-pid"
for _ in {1..100}; do flock -n "$LOCK_CANDIDATE" true && break; sleep .05; done
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
printf '{"deployment_id":"%s","exit_code":1,"started_at_ms":%s}\n' "$failed_desired" "$(date +%s%3N)" > "$STATE_DIR/attempts/$failed_desired.json"
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
printf '{"deployment_id":"%s","exit_code":76,"outcome":"route_unavailable","started_at_ms":%s}\n' "$unavailable_desired" "$(date +%s%3N)" > "$STATE_DIR/attempts/$unavailable_desired.json"
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
kill "$(cat "$tmp/holder-pid")"; rm "$tmp/holder-pid"
for _ in {1..100}; do flock -n "$LOCK_CANDIDATE" true && flock -n "$LOCK_HARDENING" true && break; sleep .05; done
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
# A failed adoption start can be canceled without removing the older inhibit.
export FIXTURE_NO_HANDSHAKE=1
if "${cmd[@]}" start --adopt-inhibit legacy-incomplete; then echo 'accepted incomplete legacy holder' >&2; exit 1; fi
kill "$(cat "$tmp/holder-pid")"; rm -f "$tmp/holder-pid"
unset FIXTURE_NO_HANDSHAKE
"${cmd[@]}" cancel-start
[[ $(stat -c %i "$tmp/hold") == "$hold_inode" && ! -e $tmp/evidence/active-window ]]
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
# If a receipt-gated restart already happened but deployment later failed,
# report the actual receipted runtime without claiming that it is healthy.
"${cmd[@]}" start eight
"${cmd[@]}" switch -- true
receipted_desired=$(printf '%064d' 9)
printf '%s\n' "$receipted_desired" > "$STATE_DIR/desired"
printf '{"deployment_id":"%s","exit_code":1,"started_at_ms":%s}\n' "$receipted_desired" "$(date +%s%3N)" > "$STATE_DIR/attempts/$receipted_desired.json"
export SERVER_PID=8888
if "${cmd[@]}" end-receipted-failure; then echo 'accepted failure without desired receipt' >&2; exit 1; fi
[[ -e $tmp/hold && -e $tmp/evidence/active-window ]]
jq --arg d "$receipted_desired" '.deployment_id=$d' "$tmp/known-good.json" > "$STATE_DIR/receipts/$receipted_desired.json"
export FIXTURE_STOP_LOST_ACK=1
if "${cmd[@]}" end-receipted-failure; then echo 'unexpected receipted stop acknowledgement' >&2; exit 1; fi
[[ -e $tmp/hold && -e $tmp/evidence/active-window && -f $STATE_DIR/recovery-unknown.json ]]
unset FIXTURE_STOP_LOST_ACK
set +e
"${cmd[@]}" end-receipted-failure
receipted_rc=$?
set -e
[[ $receipted_rc == 77 && -e $tmp/hold && ! -e $tmp/evidence/active-window ]]
jq -e --arg d "$receipted_desired" '.state == "UNKNOWN" and .reason == "receipted_runtime_failure" and .desired == $d and .receipt == "exact_candidate_pass" and .recovery_inhibit == "retained"' "$STATE_DIR/recovery-unknown.json" >/dev/null
set +e
"${cmd[@]}" end-receipted-failure
receipted_replay_rc=$?
set -e
[[ $receipted_replay_rc == 77 ]]
"${cmd[@]}" resolve-unknown
unset SERVER_PID
[[ ! -e $tmp/hold && ! -e $STATE_DIR/recovery-unknown.json ]]
# A stopped server inside a still-running, receipted container is recorded as
# UNKNOWN. After simulated investigation restores it, exact live inputs are
# checked again and both identities are retained in the audit.
"${cmd[@]}" start nine
"${cmd[@]}" switch -- true
stopped_desired=$(printf '%064d' 10)
printf '%s\n' "$stopped_desired" > "$STATE_DIR/desired"
printf '{"deployment_id":"%s","exit_code":1,"started_at_ms":%s}\n' "$stopped_desired" "$(date +%s%3N)" > "$STATE_DIR/attempts/$stopped_desired.json"
jq --arg d "$stopped_desired" '.deployment_id=$d' "$tmp/known-good.json" > "$STATE_DIR/receipts/$stopped_desired.json"
export SERVER_PID=0
set +e
"${cmd[@]}" end-receipted-failure
stopped_rc=$?
set -e
[[ $stopped_rc == 77 && -e $tmp/hold && ! -e $tmp/evidence/active-window ]]
if "${cmd[@]}" resolve-unknown; then echo 'cleared inhibit for a stopped server' >&2; exit 1; fi
export SERVER_PID=7777
"${cmd[@]}" resolve-unknown
unset SERVER_PID
jq -e '.serving_before != .serving_after and .state == "KNOWN_GOOD_SERVING"' "$tmp/evidence/nine/unknown-resolved.json" >/dev/null
# A fully stopped container refuses rollback without a receipt. Once an exact
# known-good receipt exists, rollback starts podman-t3code.service and releases.
"${cmd[@]}" start ten
"${cmd[@]}" switch -- true
stopped_ten_desired=$(printf '%064d' 11)
printf '%s\n' "$stopped_ten_desired" > "$STATE_DIR/desired"
printf '{"deployment_id":"%s","exit_code":1,"started_at_ms":%s}\n' "$stopped_ten_desired" "$(date +%s%3N)" > "$STATE_DIR/attempts/$stopped_ten_desired.json"
touch "$tmp/container-stopped"
rm -f "$STATE_DIR"/receipts/*.json
if "${cmd[@]}" rollback ten; then echo 'recovered stopped container without receipt' >&2; exit 1; fi
[[ -e $tmp/container-stopped && -e $tmp/hold ]]
cp "$tmp/known-good.json" "$STATE_DIR/receipts/$EXPECTED_DEPLOYMENT.json"
# Rollback must take the managed writer locks before it mutates. In the
# stopped-container path the alias restore and the container start used to run
# before verification acquired those locks, so an app activation could land in
# between and the rollback would record a known-good serving identity that no
# longer described the app tree. While a managed writer holds a lock, the
# rollback refuses and neither restores the alias nor starts the container.
for lock in "$HOME_DIR/.local/state/t3code-tool-update/tool-update.lock" \
  "$HOME_DIR/.local/share/t3code-tools/t3/update.lock"; do
  exec 4>"$lock"; flock -x 4
  if "${cmd[@]}" rollback ten 4>&-; then echo 'stopped rollback accepted a managed writer' >&2; exit 1; fi
  [[ -e $tmp/container-stopped ]]
  [[ -e $tmp/hold && -e $tmp/evidence/active-window ]]
  flock -u 4; exec 4>&-
done
"${cmd[@]}" rollback ten
[[ ! -e $tmp/container-stopped && ! -e $tmp/hold && ! -e $tmp/evidence/active-window ]]
jq -e --arg d "$stopped_ten_desired" --arg a "$EXPECTED_DEPLOYMENT" '.state == "KNOWN_GOOD_SERVING" and .desired == $d and .applied == $a' "$tmp/evidence/ten/known-good.json" >/dev/null

# A fully stopped container in resolve-unknown is brought back up with the exact receipt.
"${cmd[@]}" start eleven
"${cmd[@]}" switch -- true
stopped_eleven_desired=$(printf '%064d' 12)
printf '%s\n' "$stopped_eleven_desired" > "$STATE_DIR/desired"
printf '{"deployment_id":"%s","exit_code":1,"started_at_ms":%s}\n' "$stopped_eleven_desired" "$(date +%s%3N)" > "$STATE_DIR/attempts/$stopped_eleven_desired.json"
jq --arg d "$stopped_eleven_desired" '.deployment_id=$d' "$tmp/known-good.json" > "$STATE_DIR/receipts/$stopped_eleven_desired.json"
export SERVER_PID=0
set +e
"${cmd[@]}" end-receipted-failure
set -e
touch "$tmp/container-stopped"
"${cmd[@]}" resolve-unknown
[[ ! -e $tmp/container-stopped && ! -e $tmp/hold && ! -e $STATE_DIR/recovery-unknown.json ]]
unset SERVER_PID

if grep -q '^restart ' "$tmp/systemctl.events"; then echo 'unexpected restart' >&2; exit 1; fi
# A released window's UNKNOWN record can be superseded by an adopt start, as a
# recorded operator action. The record is archived, never deleted.
old_unknown=old-acceptance
mkdir -p "$tmp/evidence/$old_unknown"
printf 'started=2026-10-31T04:02:32Z start_ms=1 acquired_by=1\n' > "$tmp/evidence/$old_unknown/window.start"
printf 'holder_pid=2 held_at=2026-10-31T04:02:32Z\n' >> "$tmp/evidence/$old_unknown/window.start"
printf '%064d sha256:%064d started\n' 1 2 > "$tmp/evidence/$old_unknown/serving.before"
printf '1234 5678\n' >> "$tmp/evidence/$old_unknown/serving.before"
printf '2026-10-31T04:02:40Z 1\n' > "$tmp/evidence/$old_unknown/complete.started"
: > "$tmp/evidence/$old_unknown/complete.lock"
: > "$tmp/hold"
jq -n --arg w "$old_unknown" --arg at "$(date -u -d '-60 seconds' +%FT%TZ)" \
  '{state:"UNKNOWN",reason:"acceptance_unknown",window:$w,desired:"desired",applied:"applied",receipt:"absent",failed_marker_sha256:"absent",serving:"serving",at:$at,recovery_inhibit:"retained",inhibit_reason:"runtime failure after a receipted restart",clear_command:"ghostship-t3code-release-window resolve-unknown"}' > "$STATE_DIR/recovery-unknown.json"

# Without the flag the existing refusal is kept.
if "${cmd[@]}" start --adopt-inhibit legacy-next 2>"$tmp/sup-noflag.log"; then echo 'superseded without --supersede-unknown' >&2; exit 1; fi
grep -q 'recorded UNKNOWN requires investigation' "$tmp/sup-noflag.log" || { echo 'A: unexpected refusal:' >&2; cat "$tmp/sup-noflag.log" >&2; exit 1; }

# Without the inhibit there is nothing being superseded.
mv "$tmp/hold" "$tmp/hold.away"
if "${cmd[@]}" start --adopt-inhibit --supersede-unknown "test" legacy-next 2>"$tmp/sup-nohold.log"; then echo 'superseded without the inhibit' >&2; exit 1; fi
grep -q 'supersede requires the retained recovery inhibit' "$tmp/sup-nohold.log" || { echo 'B: unexpected refusal:' >&2; cat "$tmp/sup-nohold.log" >&2; exit 1; }
mv "$tmp/hold.away" "$tmp/hold"

# A record for the window being started is not an older record.
cp "$STATE_DIR/recovery-unknown.json" "$tmp/record.orig"
jq --arg w legacy-next '.window=$w' "$tmp/record.orig" > "$STATE_DIR/recovery-unknown.json.tmp"
mv "$STATE_DIR/recovery-unknown.json.tmp" "$STATE_DIR/recovery-unknown.json"
if "${cmd[@]}" start --adopt-inhibit --supersede-unknown "test" legacy-next 2>"$tmp/sup-same.log"; then echo 'superseded its own window' >&2; exit 1; fi
grep -q 'cannot supersede a record for the window being started' "$tmp/sup-same.log" || { echo 'C: unexpected refusal:' >&2; cat "$tmp/sup-same.log" >&2; exit 1; }
cp "$tmp/record.orig" "$STATE_DIR/recovery-unknown.json"

# A start that fails a preflight guard leaves the record untouched: the
# supersede only runs after preflight and under the window lock.
exec 3>"$LOCK_CANDIDATE"; flock -x 3
if "${cmd[@]}" start --adopt-inhibit --supersede-unknown "test" legacy-order 2>"$tmp/sup-order.log"; then echo 'started with a held candidate lock' >&2; exit 1; fi
flock -u 3; exec 3>&-
grep -q 'candidate lock held' "$tmp/sup-order.log" || { echo 'H: unexpected refusal:' >&2; cat "$tmp/sup-order.log" >&2; exit 1; }
[[ -f $STATE_DIR/recovery-unknown.json ]] || { echo 'H: superseded before preflight passed' >&2; exit 1; }
[[ ! -e $tmp/evidence/$old_unknown/archive/supersede.json ]] || { echo 'H: audit written before preflight passed' >&2; exit 1; }

# The record moves only while the window lock is held. With another writer
# holding it, a start must not archive or remove the record.
exec 5<"$tmp/evidence/window.lock"; flock -x 5
if "${cmd[@]}" start --adopt-inhibit --supersede-unknown "test" legacy-locked 2>"$tmp/sup-locked.log"; then echo 'started while another window writer held the lock' >&2; exit 1; fi
flock -u 5; exec 5<&-
grep -q 'window lock held' "$tmp/sup-locked.log" || { echo 'I: unexpected refusal:' >&2; cat "$tmp/sup-locked.log" >&2; exit 1; }
[[ -f $STATE_DIR/recovery-unknown.json ]] || { echo 'I: superseded without the window lock' >&2; exit 1; }
[[ ! -e $tmp/evidence/$old_unknown/archive/supersede.json ]] || { echo 'I: audit written without the window lock' >&2; exit 1; }
[[ ! -e $tmp/evidence/$old_unknown/archive ]] || { echo 'I: record archived without the window lock' >&2; exit 1; }
# A start that fails after the guard checks leaves the record in place: the
# mutation sits after the candidate locks, snapshot, serving identity and window
# creation, so no failure there can retire the only recovery evidence.
export FIXTURE_SERVING_BROKEN=1
if "${cmd[@]}" start --adopt-inhibit --supersede-unknown "test" legacy-broken 2>"$tmp/sup-late.log"; then echo 'started without a serving identity' >&2; exit 1; fi
unset FIXTURE_SERVING_BROKEN
grep -q 'serving identity unknown' "$tmp/sup-late.log" || { echo 'J: unexpected refusal:' >&2; cat "$tmp/sup-late.log" >&2; exit 1; }
[[ -f $STATE_DIR/recovery-unknown.json ]] || { echo 'J: superseded before the window was formed' >&2; exit 1; }
[[ ! -e $tmp/evidence/$old_unknown/archive/supersede.json ]] || { echo 'J: audit written before the window was formed' >&2; exit 1; }

# The recorded shape: acceptance_unknown, released, inhibit retained.
record_digest=$(sha256sum < "$STATE_DIR/recovery-unknown.json" | cut -d' ' -f1)
"${cmd[@]}" start --adopt-inhibit --supersede-unknown "assembly superseded the released acceptance_unknown record" legacy-supersede
[[ ! -e $STATE_DIR/recovery-unknown.json ]]
[[ -f $tmp/evidence/$old_unknown/archive/recovery-unknown.json ]]
[[ $(sha256sum < "$tmp/evidence/$old_unknown/archive/recovery-unknown.json") == "$record_digest "* ]]
jq -e --arg w "$old_unknown" --arg h "$record_digest" '.state == "SUPERSEDED" and .window == $w and .superseded_by == "legacy-supersede" and .record_sha256 == $h and (.reason | length) > 0' "$tmp/evidence/$old_unknown/archive/supersede.json" >/dev/null
[[ $(cat "$tmp/evidence/active-window") == legacy-supersede ]]

# With a window open the record's window is not released.
cp "$tmp/evidence/$old_unknown/archive/recovery-unknown.json" "$STATE_DIR/recovery-unknown.json"
if "${cmd[@]}" start --adopt-inhibit --supersede-unknown "test" legacy-second 2>"$tmp/sup-active.log"; then echo 'superseded with an active window' >&2; exit 1; fi
grep -q 'supersede requires a released window' "$tmp/sup-active.log" || { echo 'E: unexpected refusal:' >&2; cat "$tmp/sup-active.log" >&2; exit 1; }

# end-post will not close a window while a live recovery record remains.
if "${cmd[@]}" end-post 2>"$tmp/post-record.log"; then echo 'closed a window with a live UNKNOWN record' >&2; exit 1; fi
grep -q 'recorded UNKNOWN remains' "$tmp/post-record.log" || { echo 'F: unexpected refusal:' >&2; cat "$tmp/post-record.log" >&2; exit 1; }
rm "$STATE_DIR/recovery-unknown.json"

# --- closed-unaccepted: the real spent-window state -------------------------
# Reproduce #8.2: the switch succeeded, the holder expired, the deployment was
# attempted and failed 77, no receipt names it, and the serving identity has
# no exact accepted receipt (a same-image receipt exists with different
# agent/tooling/inode and must not be reused).
if [[ -f $tmp/holder-pid ]]; then "$SYSTEMCTL_BIN" stop window.service >/dev/null 2>&1 || true; fi
rm -f "$tmp/hold" "$tmp/recovery-inactive"
if [[ -e "$tmp/evidence/active-window" ]]; then rm "$tmp/evidence/active-window"; fi
export STATE_DIR="$tmp/state-unaccepted"; rm -rf "$STATE_DIR"
mkdir -p "$STATE_DIR/receipts" "$STATE_DIR/attempts"; : > "$STATE_DIR/deploy.lock"
printf '%s\n' "$EXPECTED_DEPLOYMENT" > "$STATE_DIR/desired"
printf '%s\n' "$EXPECTED_DEPLOYMENT" > "$STATE_DIR/applied"
"${cmd[@]}" start spent
printf 'exit_code=0\n' > "$tmp/evidence/spent/switch.result"
printf '%s %s\n' "$(date -u +%FT%TZ)" "$(date +%s%3N)" > "$tmp/evidence/spent/complete.started"
: > "$tmp/evidence/spent/complete.lock"
printf '{"deployment_id":"%s","started_at_ms":%s,"exit_code":77,"outcome":"route_unknown","status":null}\n' \
  "$EXPECTED_DEPLOYMENT" "$(date +%s%3N)" > "$STATE_DIR/attempts/$EXPECTED_DEPLOYMENT.json"
# The same-image receipt with a different identity is what b5e4523f is here.
jq -n --arg i "$EXPECTED_IMAGE" '{deployment_id:"b5e4523f00000000000000000000000000000000000000000000000000000000",
  image_id:$i,candidate_name:"t3code-candidate-fixture",agent_revision:"oldagent",
  agent_path:"/nix/store/old-tooling",provider_secret_sha256:"1",
  live_before:{id:"fixture"},live_after:{id:"fixture"},
  checks:{app_ready:true,provider_turn:true,agent_cli:true,skills:true,desktop_cli:true,desktop_transport:true}}' \
  > "$STATE_DIR/receipts/b5e4523f00000000000000000000000000000000000000000000000000000000.json"
# Model the expired holder.
kill "$(cat "$tmp/holder-pid")"; rm -f "$tmp/holder-pid"
# Every refusal leaves the window open.
printf 'exit_code=1\n' > "$tmp/evidence/spent/switch.result"
if "${cmd[@]}" closed-unaccepted 2>"$tmp/closed-switch.log"; then echo 'closed after a failed switch' >&2; exit 1; fi
grep -q 'switch did not succeed' "$tmp/closed-switch.log" || { echo 'C1: unexpected refusal' >&2; cat "$tmp/closed-switch.log" >&2; exit 1; }
printf 'exit_code=0\n' > "$tmp/evidence/spent/switch.result"
printf '{"deployment_id":"%s","started_at_ms":%s,"exit_code":0,"outcome":null,"status":null}\n' "$EXPECTED_DEPLOYMENT" "$(date +%s%3N)" > "$STATE_DIR/attempts/$EXPECTED_DEPLOYMENT.json"
if "${cmd[@]}" closed-unaccepted 2>"$tmp/closed-attempt.log"; then echo 'closed after a successful attempt' >&2; exit 1; fi
grep -q 'attempt is not a terminal failed acceptance' "$tmp/closed-attempt.log" || { echo 'C2: unexpected refusal' >&2; cat "$tmp/closed-attempt.log" >&2; exit 1; }
printf '{"deployment_id":"%s","started_at_ms":%s,"exit_code":77,"outcome":"route_unknown","status":null}\n' "$EXPECTED_DEPLOYMENT" "$(date +%s%3N)" > "$STATE_DIR/attempts/$EXPECTED_DEPLOYMENT.json"
export FIXTURE_SERVING_BROKEN=1
if "${cmd[@]}" closed-unaccepted 2>"$tmp/closed-serving.log"; then echo 'closed with an unknown serving identity' >&2; exit 1; fi
unset FIXTURE_SERVING_BROKEN
[[ ! -e $tmp/evidence/spent/closed-unaccepted.json && -e $tmp/hold && -e $tmp/evidence/active-window ]] || { echo 'C4: refusal mutated the window' >&2; exit 1; }
# The truthful close records the live inode only and names the unreused receipt.
"${cmd[@]}" closed-unaccepted
record="$tmp/evidence/spent/closed-unaccepted.json"
[[ -f $record ]]
jq -e --arg d "$EXPECTED_DEPLOYMENT" --arg i "$EXPECTED_IMAGE" --arg secret "$(sha256sum < "$PROVIDER_SECRETS_FILE" | cut -d ' ' -f1)" --arg nr "$STATE_DIR/receipts/b5e4523f00000000000000000000000000000000000000000000000000000000.json" '
  .state == "closed_unaccepted" and .deployment_id == $d and .applied == $d and
  .attempt.exit_code == 77 and .attempt.outcome == "route_unknown" and
  .serving.image == $i and .serving.provider_secret_sha256 == $secret and
  .serving_receipt == "absent" and .receipt_not_reused.deployment_id == "b5e4523f00000000000000000000000000000000000000000000000000000000" and
  .receipt_not_reused.agent_revision == "oldagent" and .receipt_not_reused.agent_path == "/nix/store/old-tooling" and
  .receipt_not_reused.provider_secret_sha256 == "1" and .switch_result == "exit_code=0"' "$record" >/dev/null || { echo 'record is not truthful' >&2; cat "$record" >&2; exit 1; }
[[ ! -e $tmp/hold && ! -e $tmp/evidence/active-window ]]
[[ ! -e $tmp/evidence/spent/post.verified ]]
# A closed-unaccepted record can never satisfy accepted-deployment gates.
printf '%s\n' spent > "$tmp/evidence/active-window"; : > "$tmp/hold"
if "${cmd[@]}" post 2>"$tmp/closed-post.log"; then echo 'post accepted a closed-unaccepted window' >&2; exit 1; fi
grep -q 'receipt or attempt missing' "$tmp/closed-post.log" || { echo 'C5: post refusal was not the receipt gate' >&2; cat "$tmp/closed-post.log" >&2; exit 1; }
[[ ! -e $tmp/evidence/spent/post.verified ]]
if "${cmd[@]}" closed-unaccepted 2>"$tmp/closed-again.log"; then echo 'closed an already closed window' >&2; exit 1; fi
grep -q 'window already closed unaccepted' "$tmp/closed-again.log" || { echo 'C6: unexpected second refusal' >&2; cat "$tmp/closed-again.log" >&2; exit 1; }
rm -f "$tmp/evidence/active-window" "$tmp/hold"
[[ $(ls "$STATE_DIR/receipts" | wc -l) == 1 ]]

# --- closed-unaccepted on the ACTUAL #8.2 state (switch exit_code=4) --------
# Values copied from the host: switch ended failed (status 4); attempt 77
# route_unknown; serving a60e80ca/e89d0abd/kqxwm9pd; container inode 72922092
# and a different host inode; four failed units with their first failures.
if [[ -f $tmp/holder-pid ]]; then "$SYSTEMCTL_BIN" stop window.service >/dev/null 2>&1 || true; fi
rm -f "$tmp/hold" "$tmp/recovery-inactive" "$tmp/evidence/active-window"
export STATE_DIR="$tmp/state-actual"; rm -rf "$STATE_DIR"
mkdir -p "$STATE_DIR/receipts" "$STATE_DIR/attempts"; : > "$STATE_DIR/deploy.lock"
printf '%s\n' "$EXPECTED_DEPLOYMENT" > "$STATE_DIR/desired"
printf '%s\n' "$EXPECTED_DEPLOYMENT" > "$STATE_DIR/applied"
"${cmd[@]}" start actual
now=$(date +%s); start=$((now - 600)); end=$((now - 300))
printf '%s %s\n' "$(date -u -d "@$start" +%FT%TZ)" "$((start * 1000))" > "$tmp/evidence/actual/complete.started"
printf 'exit_code=4\n' > "$tmp/evidence/actual/switch.result"
touch -d "@$end" "$tmp/evidence/actual/switch.result"
: > "$tmp/evidence/actual/complete.lock"
printf '{"deployment_id":"%s","started_at_ms":%s,"exit_code":77,"outcome":"route_unknown","status":null}\n' \
  "$EXPECTED_DEPLOYMENT" "$((start * 1000 + 1000))" > "$STATE_DIR/attempts/$EXPECTED_DEPLOYMENT.json"
jq -n --arg i "$EXPECTED_IMAGE" '{deployment_id:"b5e4523f00000000000000000000000000000000000000000000000000000000",
  image_id:$i,candidate_name:"t3code-candidate-fixture",agent_revision:"17abf6d7fixture",
  agent_path:"/nix/store/g1bhm0sbfixture",provider_secret_sha256:"72477600",
  live_before:{id:"fixture"},live_after:{id:"fixture"},
  checks:{app_ready:true,provider_turn:true,agent_cli:true,skills:true,desktop_cli:true,desktop_transport:true}}' \
  > "$STATE_DIR/receipts/b5e4523f00000000000000000000000000000000000000000000000000000000.json"
cc52=cc52fa842626570da34c889ef2f0b62ddd625559c31340512327013eb9ab3253-68fc61b280239393.service
cat > "$tmp/failed-units" <<EOF
$cc52 loaded failed failed
ghostship-ai-usage-command-code.service loaded failed failed
github-runner-ghostship-agent-2.service loaded failed failed
ghostship-t3code-deploy.service loaded failed failed
EOF
printf '%s\t%s\t%s\n' "$cc52" "$(date -u -d "@$((start - 3000))" +%FT%TZ)" "$(date -u -d "@$((now - 10))" +%FT%TZ)" \
  ghostship-ai-usage-command-code.service "$(date -u -d "@$((start - 1800))" +%FT%TZ)" "$(date -u -d "@$((now - 20))" +%FT%TZ)" \
  github-runner-ghostship-agent-2.service "$(date -u -d "@$((end + 5))" +%FT%TZ)" "$(date -u -d "@$((end + 5))" +%FT%TZ)" \
  ghostship-t3code-deploy.service "$(date -u -d "@$((start + 60))" +%FT%TZ)" "$(date -u -d "@$((end + 20))" +%FT%TZ)" > "$tmp/journal-first"
printf '%s\n' '{"MESSAGE":"Failed to start Refresh the private Command Code usage page through the owner'"'"'s browser.","UNIT":"ghostship-ai-usage-command-code.service"}' > "$tmp/journal-activation.jsonl"
export JOURNALCTL_BIN="$tmp/bin/journalctl" FIXTURE_CONTAINER_INODE=72922092
# A unit whose FIRST failure is inside the activation window refuses.
printf '%s\n' 'switch-caused.service loaded failed failed' >> "$tmp/failed-units"
printf '%s\t%s\t%s\n' switch-caused.service "$(date -u -d "@$((start + 120))" +%FT%TZ)" "$(date -u -d "@$((start + 120))" +%FT%TZ)" >> "$tmp/journal-first"
if "${cmd[@]}" closed-unaccepted 2>"$tmp/actual-switch-caused.log"; then echo 'closed with a switch-caused failure' >&2; exit 1; fi
grep -q 'unclassified failed unit: switch-caused.service' "$tmp/actual-switch-caused.log" || { echo 'A1: unexpected refusal' >&2; cat "$tmp/actual-switch-caused.log" >&2; exit 1; }
[[ ! -e $tmp/evidence/actual/closed-unaccepted.json && -e $tmp/hold ]]
sed -i '$d' "$tmp/failed-units"; sed -i '$d' "$tmp/journal-first"
# A failed unit with no journal first-failure stays unclassified and refuses.
printf '%s\n' 'no-journal.service loaded failed failed' >> "$tmp/failed-units"
if "${cmd[@]}" closed-unaccepted 2>"$tmp/actual-unclassified.log"; then echo 'closed with an unclassified failure' >&2; exit 1; fi
grep -q 'unclassified failed unit: no-journal.service' "$tmp/actual-unclassified.log" || { echo 'A2: unexpected refusal' >&2; cat "$tmp/actual-unclassified.log" >&2; exit 1; }
sed -i '$d' "$tmp/failed-units"
# The real classification passes and records both inodes and every class.
"${cmd[@]}" closed-unaccepted
record="$tmp/evidence/actual/closed-unaccepted.json"
jq -e --arg d "$EXPECTED_DEPLOYMENT" --arg i "$EXPECTED_IMAGE" --arg host "$(sha256sum < "$PROVIDER_SECRETS_FILE" | cut -d ' ' -f1)" --argjson start "$start" --argjson end "$end" '
  .state == "closed_unaccepted" and .deployment_id == $d and .applied == $d and
  .switch_result == "exit_code=4" and .attempt.exit_code == 77 and .attempt.outcome == "route_unknown" and
  .serving.image == $i and .serving.provider_secret_sha256 == $host and
  .provider_secret_sha256_host == $host and .provider_secret_sha256_match == true and
  .activation.start == $start and .activation.end == $end and
  (.failed_units | length) == 4 and
  ([.failed_units[] | select(.class == "pre_existing")] | length) == 2 and
  ([.failed_units[] | select(.class == "later")] | length) == 1 and
  ([.failed_units[] | select(.class == "expected_deploy")] | length) == 1 and
  .serving_receipt == "absent" and .receipt_not_reused.deployment_id == "b5e4523f00000000000000000000000000000000000000000000000000000000"' "$record" >/dev/null || { echo 'actual-state record is not truthful' >&2; cat "$record" >&2; exit 1; }
[[ ! -e $tmp/hold && ! -e $tmp/evidence/active-window ]]
[[ ! -e $tmp/evidence/actual/post.verified ]]
[[ $(ls "$STATE_DIR/receipts" | wc -l) == 1 ]]
# Accepted-deployment gates still refuse afterwards.
printf '%s\n' actual > "$tmp/evidence/active-window"; : > "$tmp/hold"
if "${cmd[@]}" post 2>"$tmp/actual-post.log"; then echo 'post accepted the unaccepted closeout' >&2; exit 1; fi
[[ ! -e $tmp/evidence/actual/post.verified ]]
rm -f "$tmp/evidence/active-window" "$tmp/hold"
unset FIXTURE_CONTAINER_INODE JOURNALCTL_BIN

# A receipt can exist while the deploy refused to apply it. closed-unaccepted
# records it by sha256 with receipt_applied:false, never as accepted proof.
if [[ -f $tmp/holder-pid ]]; then "$SYSTEMCTL_BIN" stop window.service >/dev/null 2>&1 || true; fi
rm -f "$tmp/hold" "$tmp/recovery-inactive" "$tmp/evidence/active-window"
export STATE_DIR="$tmp/state-receipted"; rm -rf "$STATE_DIR"
mkdir -p "$STATE_DIR/receipts" "$STATE_DIR/attempts"; : > "$STATE_DIR/deploy.lock"
printf '%s\n' "$EXPECTED_DEPLOYMENT" > "$STATE_DIR/desired"
printf '%s\n' "$EXPECTED_DEPLOYMENT" > "$STATE_DIR/applied"
"${cmd[@]}" start receipted
now2=$(date +%s); start2=$((now2 - 600)); end2=$((now2 - 300))
printf '%s %s\n' "$(date -u -d "@$start2" +%FT%TZ)" "$((start2 * 1000))" > "$tmp/evidence/receipted/complete.started"
printf 'exit_code=0\n' > "$tmp/evidence/receipted/switch.result"
touch -d "@$end2" "$tmp/evidence/receipted/switch.result"
: > "$tmp/evidence/receipted/complete.lock"
printf '{"deployment_id":"%s","started_at_ms":%s,"exit_code":77,"outcome":"acceptance_unknown","status":null}\n' \
  "$EXPECTED_DEPLOYMENT" "$((start2 * 1000 + 1000))" > "$STATE_DIR/attempts/$EXPECTED_DEPLOYMENT.json"
jq -n --arg i "$EXPECTED_IMAGE" '{deployment_id:"unapplied",image_id:$i,candidate_name:"t3code-candidate-fixture",
  agent_revision:"fixture",agent_path:"/nix/store/old-tooling",provider_secret_sha256:"1",
  live_before:{id:"fixture"},live_after:{id:"fixture"}}' > "$STATE_DIR/receipts/$EXPECTED_DEPLOYMENT.json"
cat > "$tmp/failed-units" <<EOF
ghostship-ai-usage-command-code.service loaded failed failed
ghostship-t3code-deploy.service loaded failed failed
EOF
printf '%s\t%s\t%s\n' ghostship-ai-usage-command-code.service "$(date -u -d "@$((start2 - 600))" +%FT%TZ)" "$(date -u -d "@$((now2 - 20))" +%FT%TZ)" \
  ghostship-t3code-deploy.service "$(date -u -d "@$((start2 + 60))" +%FT%TZ)" "$(date -u -d "@$((end2 + 20))" +%FT%TZ)" > "$tmp/journal-first"
printf '%s\n' '{"MESSAGE":"Failed to start Refresh the private Command Code usage page through the owner'"'"'s browser.","UNIT":"ghostship-ai-usage-command-code.service"}' > "$tmp/journal-activation.jsonl"
export JOURNALCTL_BIN="$tmp/bin/journalctl" FIXTURE_CONTAINER_INODE=72922092
receipt_hash=$(sha256sum < "$STATE_DIR/receipts/$EXPECTED_DEPLOYMENT.json" | cut -d' ' -f1)
"${cmd[@]}" closed-unaccepted
[[ $(sha256sum < "$STATE_DIR/receipts/$EXPECTED_DEPLOYMENT.json" | cut -d' ' -f1) == "$receipt_hash" ]]
record="$tmp/evidence/receipted/closed-unaccepted.json"
jq -e --arg d "$EXPECTED_DEPLOYMENT" --arg sha "$receipt_hash" '
  .state == "closed_unaccepted" and .receipt_applied == false and
  .expected_receipt.deployment_id == $d and .expected_receipt.sha256 == $sha' "$record" >/dev/null \
  || { echo 'receipted-unapplied record is not truthful' >&2; cat "$record" >&2; exit 1; }
# An applied attempt is not closable this way: post is the supported path.
rm -f "$tmp/hold" "$tmp/evidence/active-window" "$tmp/recovery-inactive"
"${cmd[@]}" start applied
printf 'exit_code=0\n' > "$tmp/evidence/applied/switch.result"
: > "$tmp/evidence/applied/complete.lock"
printf '%s %s\n' "$(date -u -d "@$start2" +%FT%TZ)" "$((start2 * 1000))" > "$tmp/evidence/applied/complete.started"
printf '{"deployment_id":"%s","started_at_ms":%s,"exit_code":0,"status":null}\n' \
  "$EXPECTED_DEPLOYMENT" "$((start2 * 1000 + 1000))" > "$STATE_DIR/attempts/$EXPECTED_DEPLOYMENT.json"
mkdir -p "$STATE_DIR/receipts"; cp "$tmp/evidence/receipted/closed-unaccepted.json" /dev/null 2>/dev/null || true
jq -n --arg i "$EXPECTED_IMAGE" '{deployment_id:"applied",image_id:$i,candidate_name:"t3code-candidate-fixture",
  agent_revision:"fixture",agent_path:"/nix/store/old-tooling",provider_secret_sha256:"1",
  live_before:{id:"fixture"},live_after:{id:"fixture"}}' > "$STATE_DIR/receipts/$EXPECTED_DEPLOYMENT.json"
if "${cmd[@]}" closed-unaccepted 2>"$tmp/applied.log"; then echo 'closed with an applied attempt' >&2; exit 1; fi
grep -q 'attempt is not a terminal failed acceptance' "$tmp/applied.log" || { echo 'P3: unexpected refusal' >&2; cat "$tmp/applied.log" >&2; exit 1; }
rm -f "$tmp/hold" "$tmp/evidence/active-window"
unset FIXTURE_CONTAINER_INODE JOURNALCTL_BIN

# Applied and healthy, but the PASS attestation failed (a deploy bug): close
# truthfully with no restart, recording the receipt and the failed attempt.
if [[ -f $tmp/holder-pid ]]; then "$SYSTEMCTL_BIN" stop window.service >/dev/null 2>&1 || true; fi
rm -f "$tmp/hold" "$tmp/recovery-inactive" "$tmp/evidence/active-window"
export STATE_DIR="$tmp/state-unattested"; rm -rf "$STATE_DIR"
mkdir -p "$STATE_DIR/receipts" "$STATE_DIR/attempts"; : > "$STATE_DIR/deploy.lock"
printf '%s\n' "$EXPECTED_DEPLOYMENT" > "$STATE_DIR/desired"
printf '%s\n' "$EXPECTED_DEPLOYMENT" > "$STATE_DIR/applied"
"${cmd[@]}" start unattested
now3=$(date +%s); start3=$((now3 - 600)); end3=$((now3 - 300))
printf '%s %s\n' "$(date -u -d "@$start3" +%FT%TZ)" "$((start3 * 1000))" > "$tmp/evidence/unattested/complete.started"
printf 'exit_code=0\n' > "$tmp/evidence/unattested/switch.result"
touch -d "@$end3" "$tmp/evidence/unattested/switch.result"
: > "$tmp/evidence/unattested/complete.lock"
jq -n --arg i "$EXPECTED_IMAGE" '{deployment_id:"attested",image_id:$i,candidate_name:"t3code-candidate-fixture",
  agent_revision:"fixture",agent_path:"/nix/store/old-tooling",provider_secret_sha256:"1",
  live_before:{id:"fixture"},live_after:{id:"fixture"},
  checks:{app_ready:true,fixture_turn:true,agent_cli:true,skills:true,desktop_cli:true}}' > "$STATE_DIR/receipts/$EXPECTED_DEPLOYMENT.json"
receipt_hash2=$(sha256sum < "$STATE_DIR/receipts/$EXPECTED_DEPLOYMENT.json" | cut -d' ' -f1)
printf '{"deployment_id":"%s","started_at_ms":%s,"exit_code":1,"outcome":null,"status":null}\n' \
  "$EXPECTED_DEPLOYMENT" "$((start3 * 1000 + 1000))" > "$STATE_DIR/attempts/$EXPECTED_DEPLOYMENT.json"
cat > "$tmp/failed-units" <<EOF
ghostship-ai-usage-command-code.service loaded failed failed
ghostship-t3code-deploy.service loaded failed failed
EOF
printf '%s\t%s\t%s\n' ghostship-ai-usage-command-code.service "$(date -u -d "@$((start3 - 600))" +%FT%TZ)" "$(date -u -d "@$((now3 - 20))" +%FT%TZ)" \
  ghostship-t3code-deploy.service "$(date -u -d "@$((start3 + 60))" +%FT%TZ)" "$(date -u -d "@$((end3 + 20))" +%FT%TZ)" > "$tmp/journal-first"
printf '%s\n' '{"MESSAGE":"Failed to start Refresh the private Command Code usage page through the owner'"'"'s browser.","UNIT":"ghostship-ai-usage-command-code.service"}' > "$tmp/journal-activation.jsonl"
export JOURNALCTL_BIN="$tmp/bin/journalctl" FIXTURE_DEPLOY_RESULT=exit-code
events_before=$(grep -c "^restart" "$tmp/systemctl.events" 2>/dev/null || true)
# An applied attempt (exit 0) is post's path, not this closeout.
printf '{"deployment_id":"%s","started_at_ms":%s,"exit_code":0,"status":null}\n' "$EXPECTED_DEPLOYMENT" "$((start3 * 1000 + 1000))" > "$STATE_DIR/attempts/$EXPECTED_DEPLOYMENT.json"
if "${cmd[@]}" closed-unattested 2>"$tmp/unattested-applied.log"; then echo 'closed an applied deployment' >&2; exit 1; fi
grep -q 'attempt is not a terminal failed deployment' "$tmp/unattested-applied.log" || { echo 'U1: unexpected refusal' >&2; cat "$tmp/unattested-applied.log" >&2; exit 1; }
printf '{"deployment_id":"%s","started_at_ms":%s,"exit_code":1,"outcome":null,"status":null}\n' \
  "$EXPECTED_DEPLOYMENT" "$((start3 * 1000 + 1000))" > "$STATE_DIR/attempts/$EXPECTED_DEPLOYMENT.json"
# A successful deploy Result is post's path too.
if FIXTURE_DEPLOY_RESULT=success "${cmd[@]}" closed-unattested 2>"$tmp/unattested-result.log"; then echo 'closed with a successful deploy result' >&2; exit 1; fi
grep -q 'deploy succeeded; use post' "$tmp/unattested-result.log" || { echo 'U2: unexpected refusal' >&2; cat "$tmp/unattested-result.log" >&2; exit 1; }
"${cmd[@]}" closed-unattested
[[ $(sha256sum < "$STATE_DIR/receipts/$EXPECTED_DEPLOYMENT.json" | cut -d' ' -f1) == "$receipt_hash2" ]]
[[ $(grep -c "^restart" "$tmp/systemctl.events" 2>/dev/null || true) == "$events_before" ]]
[[ ! -e $tmp/hold && ! -e $tmp/evidence/active-window ]]
record="$tmp/evidence/unattested/closed-unattested.json"
jq -e --arg d "$EXPECTED_DEPLOYMENT" --arg i "$EXPECTED_IMAGE" --arg sha "$receipt_hash2" '
  .state == "closed_unattested" and .deployment_id == $d and .applied == true and
  .receipt.image_id == $i and .receipt.sha256 == $sha and
  .serving.image == $i and .serving.health == "healthy" and
  .attempt.exit_code == 1 and .attestation == "failed" and .production_turn == "not_run"' "$record" >/dev/null \
  || { echo 'unattested record is not truthful' >&2; cat "$record" >&2; exit 1; }
unset FIXTURE_DEPLOY_RESULT JOURNALCTL_BIN

# The known-good receipt is bound to the applied deployment, not to the
# mutable release.json revision written by other tooling.
export STATE_DIR="$tmp/state-receipt"; rm -rf "$STATE_DIR"
mkdir -p "$STATE_DIR/receipts" "$STATE_DIR/attempts"; : > "$STATE_DIR/deploy.lock"
printf '%s\n' "$EXPECTED_DEPLOYMENT" > "$STATE_DIR/desired"
printf '%s\n' "$EXPECTED_DEPLOYMENT" > "$STATE_DIR/applied"
secret=$(sha256sum < "$PROVIDER_SECRETS_FILE" | cut -d ' ' -f1)
jq -n --arg d "$EXPECTED_DEPLOYMENT" --arg i "$EXPECTED_IMAGE" --arg p "$EXPECTED_TOOLING_PATH" --arg s "$secret" \
  '{deployment_id:$d,image_id:$i,candidate_name:"t3code-candidate-fixture",agent_revision:"fixture",agent_path:$p,provider_secret_sha256:$s,live_before:{id:"fixture"},live_after:{id:"fixture"},checks:{app_ready:true,fixture_turn:true,agent_cli:true,skills:true,desktop_cli:true,desktop_transport:true}}' \
  > "$STATE_DIR/receipts/$EXPECTED_DEPLOYMENT.json"
export FIXTURE_RELEASE_REVISION=0000000000000000000000000000000000000000
"${cmd[@]}" start receiptmeta
"${cmd[@]}" switch -- true
printf '%064d\n' 5 > "$STATE_DIR/desired"
"${cmd[@]}" rollback receiptmeta
[[ -f $tmp/evidence/receiptmeta/known-good.json ]]
unset FIXTURE_RELEASE_REVISION
# A legacy receipt carries only the inode. Recovery accepts it when the live
# content matches and records the weaker evidence without inventing a digest.
jq 'del(.provider_secret_sha256) | .provider_secret_inode="1"' "$STATE_DIR/receipts/$EXPECTED_DEPLOYMENT.json" > "$STATE_DIR/receipts/legacy.tmp"
mv "$STATE_DIR/receipts/legacy.tmp" "$STATE_DIR/receipts/$EXPECTED_DEPLOYMENT.json"
"${cmd[@]}" start legacyknown
"${cmd[@]}" switch -- true
printf '%064d\n' 7 > "$STATE_DIR/desired"
"${cmd[@]}" rollback legacyknown
jq -e '.state == "KNOWN_GOOD_SERVING" and .provider_secret_sha256 == null and .secret_evidence == "legacy-content-consistent"' "$tmp/evidence/legacyknown/known-good.json" >/dev/null
# A different applied deployment id must not borrow that receipt.
printf '%064d\n' 6 > "$STATE_DIR/applied"
"${cmd[@]}" start wrongapplied
"${cmd[@]}" switch -- true
if "${cmd[@]}" rollback wrongapplied 2>"$tmp/wrong-applied.log"; then
  echo 'restored without the applied receipt' >&2; exit 1
fi
grep -q 'no exact known-good receipt' "$tmp/wrong-applied.log" || {
  echo 'wrong-applied refusal is not the receipt guard' >&2; cat "$tmp/wrong-applied.log" >&2; exit 1; }
printf '%s\n' "$EXPECTED_DEPLOYMENT" > "$STATE_DIR/applied"

echo 'Release window refusal and reopen fixture passed.'
