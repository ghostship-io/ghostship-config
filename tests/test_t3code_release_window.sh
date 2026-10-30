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
if [[ $1 == show ]]; then
  if [[ $2 == ghostship-t3code-deploy.service && $3 == -p && $4 == Result ]]; then echo success; exit; fi
  if [[ $2 == window.service && $3 == -p && $4 == MainPID ]]; then cat "$FIXTURE/holder-pid"; exit; fi
  case $2 in window.service) [[ -f $FIXTURE/holder-pid ]] && kill -0 "$(cat "$FIXTURE/holder-pid")" 2>/dev/null && echo active || echo inactive ;; t3code-recovery.service) [[ -e $FIXTURE/recovery-inactive ]] && echo inactive || echo active ;; *) echo inactive ;; esac
elif [[ $1 == stop && $2 == t3code-recovery.service ]]; then touch "$FIXTURE/recovery-inactive"
elif [[ $1 == start && $2 == t3code-recovery.service ]]; then rm -f "$FIXTURE/recovery-inactive"
elif [[ $1 == stop && $2 == window.service ]]; then kill "$(cat "$FIXTURE/holder-pid")"; rm -f "$FIXTURE/holder-pid"
else exit 1; fi
SH
cat > "$tmp/bin/podman" <<'SH'
#!/usr/bin/env bash
case "$*" in
  'exec fixture systemctl show t3code-server.service -p MainPID --value') echo 1234; exit ;;
  'exec fixture systemctl show t3code-server.service -p ActiveEnterTimestampMonotonic --value') echo 5678; exit ;;
esac
case "$1 $3 ${4:-}" in
  'inspect --format {{.Id}} {{.Image}} {{.State.StartedAt}}') printf '%064d sha256:%s started\n' 1 "$EXPECTED_IMAGE" ;;
  'inspect --format {{.Image}}') printf 'sha256:%s\n' "$EXPECTED_IMAGE" ;;
  'inspect --format {{.State.Health.Status}}') printf 'healthy\n' ;;
  'exec readlink -f') printf '%s\n' "$EXPECTED_TOOLING_PATH" ;;
  'exec stat -Lc') stat -Lc '%i' "$PROVIDER_SECRETS_FILE" ;;
  'exec systemctl is-active'|'exec curl -fsS') exit 0 ;;
  *) exit 1 ;;
esac
SH
cat > "$tmp/bin/systemd-run" <<'SH'
#!/usr/bin/env bash
while [[ $1 != -- ]]; do shift; done
shift
if [[ ${FIXTURE_NO_HANDSHAKE:-0} == 1 ]]; then
  sleep 8 6<&- 7<&- 8<&- >/dev/null 2>&1 &
else
  "$@" 6<&- 7<&- 8<&- >/dev/null 2>&1 &
fi
printf "%s\n" "$!" > "$FIXTURE/holder-pid"
SH
chmod +x "$tmp/bin/"*
export WINDOW_BOOTSTRAP="$repo/packages/t3code/window-bootstrap.sh"
EXPECTED_IMAGE=$(printf '%064d' 2); EXPECTED_DEPLOYMENT=$(printf '%064d' 3); JQ_BIN=$(command -v jq)
export EXPECTED_IMAGE EXPECTED_DEPLOYMENT JQ_BIN
export EXPECTED_AGENT_REVISION=fixture EXPECTED_TOOLING_PATH="$tmp/tooling" PROVIDER_SECRETS_FILE="$tmp/secrets" CURRENT_SYSTEM="$tmp/current-system" EXPECTED_SYSTEM="$tmp/system" CANDIDATE_HOME_TARGET=/home/fixture
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
# An announced deploy, including one that crashes, must refuse end.
bash -c 'source "$WINDOW_INTENT_HELPER"; announce_intent deploy; exit 99' || [[ $? == 99 ]]
if "${cmd[@]}" end-no-activation; then echo 'accepted deploy intent' >&2; exit 1; fi
rm "$tmp/evidence/one/"effect-intent.*
touch "$tmp/evidence/one/complete.started"
if "${cmd[@]}" end-no-activation; then echo 'accepted switch intent' >&2; exit 1; fi
rm "$tmp/evidence/one/complete.started"
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
printf '{"deployment_id":"%s","exit_code":77,"outcome":"route_unknown"}\n' "$EXPECTED_DEPLOYMENT" > "$STATE_DIR/attempts/$EXPECTED_DEPLOYMENT.json"
if "${cmd[@]}" post; then echo 'accepted unknown attempt' >&2; exit 1; fi
printf '{"deployment_id":"%s","exit_code":0}\n' "$EXPECTED_DEPLOYMENT" > "$STATE_DIR/attempts/$EXPECTED_DEPLOYMENT.json"
"${cmd[@]}" post
echo 'Release window refusal and reopen fixture passed.'
