#!/usr/bin/env bash
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin" "$tmp/state/receipts" "$tmp/home" "$tmp/home/.local/share/t3code-tools" "$tmp/runtime"
export PATH="$tmp/bin:$PATH"

printf '%s\n' '{"config":{"Entrypoint":["/nix/store/test/lib/systemd/systemd"]},"rootfs":{"diff_ids":["fixture"]}}' > "$tmp/config.json"
printf '%s\n' '[{"Config":"config.json","RepoTags":["localhost/t3code:test"]}]' > "$tmp/manifest.json"
tar -cf "$tmp/image.tar" -C "$tmp" manifest.json config.json
printf 'provider=fixture\n' > "$tmp/provider.env"
mkdir -p "$tmp/tooling"
printf 'old\n' > "$tmp/state/applied"
printf 'agent=old secret_inode=old\n' > "$tmp/state/applied-inputs"
printf '%s\n' 'deployment-1' > "$tmp/state/desired"
printf 'agent=agent-rev secret_inode=%s\n' "$(stat -Lc '%i' "$tmp/provider.env")" > "$tmp/state/desired-inputs"
: > "$tmp/events"

cat > "$tmp/bin/python" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
exec "$@"
SH
cat > "$tmp/accept-candidate" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
if [[ ${CANDIDATE_PRECONDITION:-0} == 1 ]]; then
  printf '%s\n' candidate-precondition >> "$EVENTS"
  exit 75
fi
if [[ ${CANDIDATE_FAIL:-0} == 1 ]]; then
  printf '%s\n' candidate-failed >> "$EVENTS"
  exit 2
fi
printf '%s\n' candidate-accepted >> "$EVENTS"
if [[ -n ${SUPERSEDE_TO:-} ]]; then
  printf '%s\n' "$SUPERSEDE_TO" > "$STATE_DIR/desired"
  printf '%s\n' 'agent=new secret_inode=new' > "$STATE_DIR/desired-inputs"
fi
config=$(tar -xOf "$IMAGE_ARCHIVE" manifest.json | jq -er '.[0].Config')
image=$(tar -xOf "$IMAGE_ARCHIVE" "$config" | sha256sum | cut -d ' ' -f 1)
if [[ ${RECEIPT_MISSING:-0} == 1 ]]; then exit 0; fi
if [[ ${RECEIPT_IMAGE_MISMATCH:-0} == 1 ]]; then image=unreceipted-image; fi
jq -cn \
  --arg deployment "$DEPLOYMENT_ID" --arg image "$image" --arg agent "$AGENT_REVISION" \
  --arg tooling "$TOOLING_PATH" --arg secret_inode "$(stat -Lc '%i' "$PROVIDER_SECRETS_FILE")" \
  '{deployment_id:$deployment,image_id:$image,candidate_name:"t3code-candidate-fixture",
    agent_revision:$agent,agent_path:$tooling,provider_secret_inode:$secret_inode,
    live_before:{id:"production"},live_after:{id:"production"},
    checks:{app_ready:true,provider_turn:true,agent_cli:true,skills:true,desktop_transport:true}}' \
  > "$STATE_DIR/receipts/$DEPLOYMENT_ID.json"
SH
cat > "$tmp/bin/podman" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
if [[ $1 == inspect && $2 == t3code ]]; then
  case "$4" in
    '{{.State.Health.Status}}')
      now=$(cat "$HEALTH_CLOCK_FILE")
      if (( now >= HEALTHY_AFTER_SECONDS )); then printf 'healthy\n'; else printf 'starting\n'; fi
      ;;
    '{{.Image}}') printf '%s\n' "$RUNNING_IMAGE_ID" ;;
    '{{.State.Running}} {{.Image}}')
      [[ ${RUNNING_CONTAINER:-1} == 1 ]] || exit 1
      printf 'true %s\n' "$RUNNING_IMAGE_ID"
      ;;
    *)
      if [[ -r "$LIVE_IMAGE_FILE" ]]; then
        printf 'container-id %s started healthy\n' "$(cat "$LIVE_IMAGE_FILE")"
      else
        printf 'container-id sha256:%s started healthy\n' "$(tar -xOf "$IMAGE_ARCHIVE" manifest.json | jq -r '.[0].Config' | xargs -I{} tar -xOf "$IMAGE_ARCHIVE" {} | sha256sum | cut -d ' ' -f 1)"
      fi
      ;;
  esac
elif [[ $1 == load ]]; then
  printf '%s\n' image-load >> "$EVENTS"
elif [[ $1 == tag ]]; then
  printf '%s\n' image-tag >> "$EVENTS"
  printf '%s\n' "${2#sha256:}" > "$ACCEPTED_POINTER_FILE"
elif [[ $1 == image && $2 == inspect ]]; then
  if [[ -r "$ACCEPTED_POINTER_FILE" ]]; then
    printf 'sha256:%s\n' "$(cat "$ACCEPTED_POINTER_FILE")"
  else
    exit 1
  fi
elif [[ $1 == exec && $2 == t3code && $3 == readlink ]]; then
  printf '%s\n' "$TOOLING_PATH"
elif [[ $1 == exec && $2 == t3code && $3 == stat ]]; then
  stat -Lc '%i' "$PROVIDER_SECRETS_FILE"
elif [[ $1 == exec && $2 == t3code && $3 == sha256sum ]]; then
  # The running container's provider secret: stale unless a case says otherwise.
  sha256sum "$LIVE_SECRET_FILE"
fi
SH
cat > "$tmp/bin/systemctl" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
if [[ $1 == restart && $2 == podman-t3code.service ]]; then
  printf '%s\n' restart >> "$EVENTS"
  rm -f "$LIVE_IMAGE_FILE"
elif [[ $1 == is-active ]]; then
  exit 0
fi
SH
cat > "$tmp/bin/systemd-cat" <<'SH'
#!/usr/bin/env bash
cat >> "$ALARM_LOG"
SH
cat > "$tmp/bin/receipt-self-check" <<SH
#!/usr/bin/env bash
exec bash "$root/packages/t3code/receipt-self-check.sh"
SH
cat > "$tmp/bin/hostname" <<'SH'
#!/usr/bin/env bash
printf 'test-host\n'
SH
cat > "$tmp/bin/health-clock" <<'SH'
#!/usr/bin/env bash
cat "$HEALTH_CLOCK_FILE"
SH
cat > "$tmp/bin/health-sleep" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
now=$(cat "$HEALTH_CLOCK_FILE")
printf '%s\n' "$((now + $1))" > "$HEALTH_CLOCK_FILE"
SH
chmod +x "$tmp/bin/python" "$tmp/accept-candidate" "$tmp/bin/podman" "$tmp/bin/systemctl" "$tmp/bin/systemd-cat" "$tmp/bin/receipt-self-check" "$tmp/bin/hostname" "$tmp/bin/health-clock" "$tmp/bin/health-sleep"

export STATE_DIR="$tmp/state" IMAGE_ARCHIVE="$tmp/image.tar" DEPLOYMENT_ID=deployment-1
export ACCEPTED_POINTER_FILE="$tmp/state/accepted-image"
export RUNNING_IMAGE_ID="sha256:$(printf 'legacy-running-image' | sha256sum | cut -d ' ' -f 1)"
export RECEIPT_SELF_CHECK="$tmp/bin/receipt-self-check" ALARM_LOG="$tmp/alarms.log"
export HOME_DIR="$tmp/home" CANDIDATE_ACCEPTANCE="$tmp/accept-candidate" PODMAN_BIN="$tmp/bin/podman"
export SYSTEMCTL_BIN="$tmp/bin/systemctl" ACCEPTED_IMAGE_REF=localhost/ghostship-t3code:accepted
export CANDIDATE_SOCKET="$tmp/candidate.sock" CANDIDATE_UID=62041
export CANDIDATE_RUNTIME_DIR="$tmp/runtime" CANDIDATE_HOME_TARGET=/candidate-home
export PROVIDER_SECRETS_FILE="$tmp/provider.env" TOOLING_PATH="$tmp/tooling" AGENT_REVISION=agent-rev
export PYTHON_BIN="$tmp/bin/python" JQ_BIN=jq RESTART_LEDGER="$tmp/ledger.jsonl"
export AUDIT_LOG="$tmp/home/restart-audit.log" EVENTS="$tmp/events"
export HEALTH_WAIT_BUDGET_SECONDS=390 HEALTH_WAIT_CLOCK_BIN="$tmp/bin/health-clock"
export HEALTH_WAIT_SLEEP_BIN="$tmp/bin/health-sleep" HEALTH_CLOCK_FILE="$tmp/health-clock"
export HEALTHY_AFTER_SECONDS=0
printf '0\n' > "$HEALTH_CLOCK_FILE"
export LIVE_IMAGE_FILE="$tmp/live-image" LIVE_SECRET_FILE="$tmp/live-secret"
printf 'provider=stale\n' > "$LIVE_SECRET_FILE"

# Model the currently running image from the host before this guard existed.
# This keeps the regular candidate-flow proof separate from the no-receipt
# bootstrap proof below.
printf '%s\n' "${RUNNING_IMAGE_ID#sha256:}" > "$ACCEPTED_POINTER_FILE"
jq -cn --arg image "${RUNNING_IMAGE_ID#sha256:}" \
  '{deployment_id:"legacy",image_id:$image,candidate_name:"t3code-candidate-legacy",
    live_before:{id:"production"},live_after:{id:"production"},
    checks:{app_ready:true,provider_turn:true,agent_cli:true,skills:true,desktop_transport:true}}' \
  > "$STATE_DIR/receipts/legacy.json"

bash "$root/packages/t3code/deploy-image.sh" > "$tmp/success.log"
grep -q '^Candidate acceptance PASS .* receipt=' "$tmp/success.log"
grep -q '^Restarting podman-t3code.service immediately after exact-image candidate acceptance$' "$tmp/success.log"
[[ $(sed -n '1p' "$EVENTS") == candidate-accepted ]]
[[ $(sed -n '2p' "$EVENTS") == image-load ]]
[[ $(sed -n '3p' "$EVENTS") == image-tag ]]
[[ $(sed -n '4p' "$EVENTS") == restart ]]
[[ $(cat "$tmp/state/applied") == "$DEPLOYMENT_ID" ]]
[[ $(jq -r '.mode' "$tmp/ledger.jsonl") == candidate-accepted ]]

# A restart that remains starting for more than 120 simulated seconds must
# still reach the existing post-restart checks and applied marker.
saved_events=$EVENTS
EVENTS="$tmp/health-events"
: > "$EVENTS"
export DEPLOYMENT_ID=deployment-slow-healthy HEALTHY_AFTER_SECONDS=130
printf '%s\n' "$DEPLOYMENT_ID" > "$STATE_DIR/desired"
printf 'agent=agent-rev secret_inode=%s\n' "$(stat -Lc '%i' "$PROVIDER_SECRETS_FILE")" > "$STATE_DIR/desired-inputs"
printf '0\n' > "$HEALTH_CLOCK_FILE"
bash "$root/packages/t3code/deploy-image.sh" > "$tmp/slow-healthy.log"
[[ $(cat "$STATE_DIR/applied") == "$DEPLOYMENT_ID" ]]
[[ $(cat "$HEALTH_CLOCK_FILE") -ge 130 ]]
[[ $(wc -l < "$tmp/ledger.jsonl") == 2 ]]

# A real timeout stays non-zero and cannot advance either applied marker.
export DEPLOYMENT_ID=deployment-never-healthy HEALTHY_AFTER_SECONDS=999
export HEALTH_WAIT_BUDGET_SECONDS=20
printf '%s\n' "$DEPLOYMENT_ID" > "$STATE_DIR/desired"
printf 'agent=agent-rev secret_inode=%s\n' "$(stat -Lc '%i' "$PROVIDER_SECRETS_FILE")" > "$STATE_DIR/desired-inputs"
applied_before=$(cat "$STATE_DIR/applied")
applied_inputs_before=$(cat "$STATE_DIR/applied-inputs")
printf '0\n' > "$HEALTH_CLOCK_FILE"
set +e
bash "$root/packages/t3code/deploy-image.sh" > "$tmp/never-healthy.log" 2>&1
never_healthy_status=$?
set -e
[[ $never_healthy_status != 0 ]]
grep -q 'did not become healthy after the accepted image restart' "$tmp/never-healthy.log"
[[ $(cat "$STATE_DIR/applied") == "$applied_before" ]]
[[ $(cat "$STATE_DIR/applied-inputs") == "$applied_inputs_before" ]]
EVENTS=$saved_events

# A failed acceptance raises the systemd failure path once and is never queued
# or retried by a later activation of the same image.
export DEPLOYMENT_ID=deployment-2 CANDIDATE_FAIL=1
printf '%s\n' "$DEPLOYMENT_ID" > "$tmp/state/desired"
set +e
bash "$root/packages/t3code/deploy-image.sh" > "$tmp/failure.log" 2>&1
first_status=$?
set -e
[[ $first_status != 0 ]]
grep -q 'Candidate acceptance FAILED' "$tmp/failure.log"
[[ $(cut -d ' ' -f 1 "$tmp/state/failed-candidate") == "$DEPLOYMENT_ID" ]]
[[ $(jq -r '.deployment_id + ":" + (.exit_code | tostring)' "$tmp/state/attempts/$DEPLOYMENT_ID.json") == "$DEPLOYMENT_ID:1" ]]
[[ $(jq -r '.started_at_ms | numbers' "$tmp/state/attempts/$DEPLOYMENT_ID.json") =~ ^[0-9]+$ ]]
[[ $(wc -l < "$EVENTS") == 5 ]]
set +e
bash "$root/packages/t3code/deploy-image.sh" > "$tmp/replay.log" 2>&1
replay_status=$?
set -e
[[ $replay_status == 0 ]]
grep -q 'already failed .* image remains blocked' "$tmp/replay.log"
[[ $(wc -l < "$EVENTS") == 5 ]]
[[ $(wc -l < "$tmp/ledger.jsonl") == 2 ]]

# A changed acceptance check re-runs acceptance for the same image instead of
# replaying the old failure; the new run still decides. Its events stay out of
# the counts asserted below.
saved_events=$EVENTS
EVENTS="$tmp/rerun-events"
cp "$CANDIDATE_ACCEPTANCE" "$tmp/accept-candidate.orig"
printf '\n# acceptance fix\n' >> "$CANDIDATE_ACCEPTANCE"
set +e
bash "$root/packages/t3code/deploy-image.sh" > "$tmp/rerun.log" 2>&1
rerun_status=$?
set -e
[[ $rerun_status != 0 ]]
grep -q 'Candidate acceptance FAILED' "$tmp/rerun.log"
! grep -q 'already failed' "$tmp/rerun.log"
cp "$tmp/accept-candidate.orig" "$CANDIDATE_ACCEPTANCE"
mark_failed_key="deployment-2 $(sha256sum "$CANDIDATE_ACCEPTANCE" | cut -d ' ' -f 1)"
printf '%s\n' "$mark_failed_key" > "$tmp/state/failed-candidate"
EVENTS=$saved_events

# A host precondition that fails before the candidate runs (exit 75, e.g. a
# routing snapshot with a failed source) never blocks the image. The deployer
# exits 75 so systemd retries it (RestartForceExitStatus=75), a bounded number
# of times; the last attempt exits 1, stops the retries and leaves the image
# retryable, and a later run starts the count again. Its events stay out of the
# counts asserted below.
saved_events=$EVENTS
EVENTS="$tmp/precondition-events"
export DEPLOYMENT_ID=deployment-precondition CANDIDATE_PRECONDITION=1 CANDIDATE_FAIL=0 PRECONDITION_ATTEMPTS=3
printf '%s\n' "$DEPLOYMENT_ID" > "$tmp/state/desired"
precondition_run() {
  set +e
  bash "$root/packages/t3code/deploy-image.sh" > "$tmp/precondition-$1.log" 2>&1
  precondition_status=$?
  set -e
  ! grep -q 'already failed' "$tmp/precondition-$1.log"
  [[ $(cat "$tmp/state/failed-candidate") == "$mark_failed_key" ]]
}
for attempt in 1 2; do
  precondition_run "$attempt"
  [[ $precondition_status == 75 ]]
  grep -q "precondition not met for deployment-precondition (attempt $attempt of 3); image stays retryable and is retried" "$tmp/precondition-$attempt.log"
  [[ $(cut -d ' ' -f 3 "$tmp/state/precondition-attempts") == "$attempt" ]]
done
precondition_run 3
[[ $precondition_status == 1 ]]
grep -q 'precondition not met for deployment-precondition after 3 attempts; image stays retryable' "$tmp/precondition-3.log"
[[ ! -e "$tmp/state/precondition-attempts" ]]
precondition_run 4
[[ $precondition_status == 75 ]]
grep -q '(attempt 1 of 3)' "$tmp/precondition-4.log"
[[ $(grep -c candidate-precondition "$EVENTS") == 4 ]]
# A candidate failure after a precondition miss is not retried: it blocks the
# image and clears the count.
export CANDIDATE_PRECONDITION=0 CANDIDATE_FAIL=1
set +e
bash "$root/packages/t3code/deploy-image.sh" > "$tmp/precondition-then-fail.log" 2>&1
precondition_status=$?
set -e
[[ $precondition_status == 1 ]]
grep -q 'Candidate acceptance FAILED for deployment-precondition' "$tmp/precondition-then-fail.log"
[[ ! -e "$tmp/state/precondition-attempts" ]]
[[ $(cut -d ' ' -f 1 "$tmp/state/failed-candidate") == deployment-precondition ]]
printf '%s\n' "$mark_failed_key" > "$tmp/state/failed-candidate"
export CANDIDATE_FAIL=0
unset PRECONDITION_ATTEMPTS
EVENTS=$saved_events

# An absent receipt is rejected before the accepted alias can move. This is the
# restart-path invariant: no receipt, no tag, no restart.
export DEPLOYMENT_ID=deployment-absent CANDIDATE_FAIL=0 RECEIPT_MISSING=1 RECEIPT_IMAGE_MISMATCH=0
printf '%s\n' "$DEPLOYMENT_ID" > "$tmp/state/desired"
printf 'agent=agent-rev secret_inode=%s\n' "$(stat -Lc '%i' "$tmp/provider.env")" > "$tmp/state/desired-inputs"
set +e
bash "$root/packages/t3code/deploy-image.sh" > "$tmp/absent.log" 2>&1
absent_status=$?
set -e
[[ $absent_status != 0 ]]
grep -q 'receipt did not approve this exact image' "$tmp/absent.log"
[[ $(wc -l < "$EVENTS") == 6 ]]

# A mismatched receipt is also rejected before the accepted alias can move.
export DEPLOYMENT_ID=deployment-mismatch RECEIPT_MISSING=0 RECEIPT_IMAGE_MISMATCH=1
printf '%s\n' "$DEPLOYMENT_ID" > "$tmp/state/desired"
printf 'agent=agent-rev secret_inode=%s\n' "$(stat -Lc '%i' "$tmp/provider.env")" > "$tmp/state/desired-inputs"
set +e
bash "$root/packages/t3code/deploy-image.sh" > "$tmp/mismatch.log" 2>&1
mismatch_status=$?
set -e
[[ $mismatch_status != 0 ]]
grep -q 'receipt did not approve this exact image' "$tmp/mismatch.log"
[[ $(wc -l < "$EVENTS") == 7 ]]

# A target changed while acceptance ran must not be restarted with the old
# image's receipt. Activation normally serializes this mutation on deploy.lock;
# this guard also fails safely if an out-of-band writer changes desired.
export DEPLOYMENT_ID=deployment-3 SUPERSEDE_TO=deployment-4 CANDIDATE_FAIL=0 RECEIPT_IMAGE_MISMATCH=0
printf '%s\n' "$DEPLOYMENT_ID" > "$tmp/state/desired"
printf 'agent=agent-rev secret_inode=%s\n' "$(stat -Lc '%i' "$tmp/provider.env")" > "$tmp/state/desired-inputs"
set +e
bash "$root/packages/t3code/deploy-image.sh" > "$tmp/superseded.log" 2>&1
superseded_status=$?
set -e
[[ $superseded_status == 0 ]]
grep -q 'superseded before restart; refusing stale image' "$tmp/superseded.log"
[[ $(wc -l < "$EVENTS") == 8 ]]
[[ $(cat "$tmp/state/applied") == deployment-slow-healthy ]]
[[ $(wc -l < "$tmp/ledger.jsonl") == 2 ]]

# A same-applied upgrade from the old unit may have a valid receipt but no new
# accepted alias. Restore the alias from that receipt without rerunning checks
# or restarting the existing service.
export DEPLOYMENT_ID=deployment-repair
printf '%s\n' "$DEPLOYMENT_ID" > "$tmp/state/desired"
printf 'agent=agent-rev secret_inode=%s\n' "$(stat -Lc '%i' "$tmp/provider.env")" > "$tmp/state/desired-inputs"
cp "$tmp/state/desired-inputs" "$tmp/state/applied-inputs"
printf '%s\n' "$DEPLOYMENT_ID" > "$tmp/state/applied"
config=$(tar -xOf "$IMAGE_ARCHIVE" manifest.json | jq -er '.[0].Config')
repair_image=$(tar -xOf "$IMAGE_ARCHIVE" "$config" | sha256sum | cut -d ' ' -f 1)
jq -cn --arg deployment "$DEPLOYMENT_ID" --arg image "$repair_image" \
  --arg agent "$AGENT_REVISION" --arg tooling "$TOOLING_PATH" \
  --arg secret_inode "$(stat -Lc '%i' "$PROVIDER_SECRETS_FILE")" \
  '{deployment_id:$deployment,image_id:$image,candidate_name:"t3code-candidate-existing",
    agent_revision:$agent,agent_path:$tooling,provider_secret_inode:$secret_inode,
    live_before:{id:"production"},live_after:{id:"production"},
    checks:{app_ready:true,provider_turn:true,agent_cli:true,skills:true,desktop_transport:true}}' \
  > "$tmp/state/receipts/$DEPLOYMENT_ID.json"
rm -f "$ACCEPTED_POINTER_FILE"
bash "$root/packages/t3code/deploy-image.sh" > "$tmp/repair.log"
grep -q '^Initialized accepted image alias from the existing PASS receipt:' "$tmp/repair.log"
[[ $(sed -n '9p' "$EVENTS") == image-load ]]
[[ $(sed -n '10p' "$EVENTS") == image-tag ]]
[[ $(wc -l < "$EVENTS") == 10 ]]
[[ $(cat "$ACCEPTED_POINTER_FILE") == "$repair_image" ]]

# With no receipt for the currently running image and no accepted alias, the
# bootstrap tags only that live image, records the alarm, and does not load a
# candidate image or restart T3.
bootstrap_state="$tmp/bootstrap-state"
mkdir -p "$bootstrap_state/receipts"
export STATE_DIR="$bootstrap_state" DEPLOYMENT_ID=deployment-bootstrap
export ACCEPTED_POINTER_FILE="$bootstrap_state/accepted-image"
export RUNNING_IMAGE_ID="sha256:$(printf 'unreceipted-running-image' | sha256sum | cut -d ' ' -f 1)"
export RUNNING_CONTAINER=1 ALARM_LOG="$tmp/bootstrap-alarms.log" EVENTS="$tmp/bootstrap-events"
: > "$EVENTS"
printf '%s\n' "$DEPLOYMENT_ID" > "$STATE_DIR/desired"
printf 'agent=agent-rev secret_inode=%s\n' "$(stat -Lc '%i' "$PROVIDER_SECRETS_FILE")" > "$STATE_DIR/desired-inputs"
set +e
bash "$root/packages/t3code/deploy-image.sh" > "$tmp/bootstrap.log" 2>&1
bootstrap_status=$?
set -e
[[ $bootstrap_status == 0 ]]
grep -q '^BOOTSTRAP: no PASS receipt matches running image ' "$tmp/bootstrap.log"
grep -q 'without a matching PASS candidate-acceptance receipt' "$ALARM_LOG"
[[ $(cat "$ACCEPTED_POINTER_FILE") == "${RUNNING_IMAGE_ID#sha256:}" ]]
[[ $(cat "$EVENTS") == image-tag ]]
[[ ! -e "$STATE_DIR/applied" ]]

# With no live container, bootstrap fails clearly and leaves the alias absent.
empty_state="$tmp/empty-state"
mkdir -p "$empty_state/receipts"
export STATE_DIR="$empty_state" DEPLOYMENT_ID=deployment-no-running
export ACCEPTED_POINTER_FILE="$empty_state/accepted-image" RUNNING_CONTAINER=0
export ALARM_LOG="$tmp/empty-alarms.log" EVENTS="$tmp/empty-events"
: > "$EVENTS"
printf '%s\n' "$DEPLOYMENT_ID" > "$STATE_DIR/desired"
printf 'agent=agent-rev secret_inode=%s\n' "$(stat -Lc '%i' "$PROVIDER_SECRETS_FILE")" > "$STATE_DIR/desired-inputs"
set +e
bash "$root/packages/t3code/deploy-image.sh" > "$tmp/no-running.log" 2>&1
no_running_status=$?
set -e
[[ $no_running_status != 0 ]]
grep -q 'no T3 container is running and no accepted alias exists' "$tmp/no-running.log"
[[ ! -e "$ACCEPTED_POINTER_FILE" ]]
[[ ! -s "$EVENTS" ]]

# A re-run of acceptance for the image T3 already runs, with the same agent
# and provider secret content (only the secret's inode is new after a switch),
# records the PASS and does not restart T3. A changed image, or changed secret
# content, still restarts once after PASS (#667).
export STATE_DIR="$tmp/state" ACCEPTED_POINTER_FILE="$tmp/state/accepted-image" RUNNING_CONTAINER=1
export ALARM_LOG="$tmp/alarms.log" EVENTS="$tmp/unchanged-events" HEALTH_WAIT_BUDGET_SECONDS=390 HEALTHY_AFTER_SECONDS=0
export CANDIDATE_FAIL=0 CANDIDATE_PRECONDITION=0 RECEIPT_MISSING=0 RECEIPT_IMAGE_MISMATCH=0
unset SUPERSEDE_TO
rm -f "$tmp/state/failed-candidate"
ledger_before=$(wc -l < "$tmp/ledger.jsonl")
unchanged_run() {
  : > "$EVENTS"
  export DEPLOYMENT_ID=$1
  printf '%s\n' "$DEPLOYMENT_ID" > "$STATE_DIR/desired"
  printf 'agent=agent-rev secret_inode=%s\n' "$(stat -Lc '%i' "$PROVIDER_SECRETS_FILE")" > "$STATE_DIR/desired-inputs"
  printf '0\n' > "$HEALTH_CLOCK_FILE"
  bash "$root/packages/t3code/deploy-image.sh" > "$tmp/$1.log" 2>&1
  [[ $(cat "$STATE_DIR/applied") == "$1" ]]
  grep -q candidate-accepted "$EVENTS"
}
cp "$PROVIDER_SECRETS_FILE" "$LIVE_SECRET_FILE"
unchanged_run deployment-unchanged
grep -q 'PASS recorded, no restart' "$tmp/deployment-unchanged.log"
! grep -q restart "$EVENTS"
[[ $(wc -l < "$tmp/ledger.jsonl") == "$ledger_before" ]]
[[ $(jq -r .deployment_id "$STATE_DIR/deployed-inputs.json") == deployment-unchanged ]]
printf 'sha256:%s\n' "$(printf 'older-image' | sha256sum | cut -d ' ' -f 1)" > "$LIVE_IMAGE_FILE"
unchanged_run deployment-new-image
[[ $(grep -c '^restart$' "$EVENTS") == 1 ]]
! grep -q 'no restart' "$tmp/deployment-new-image.log"
[[ $(wc -l < "$tmp/ledger.jsonl") == $((ledger_before + 1)) ]]
printf 'provider=rotated\n' > "$LIVE_SECRET_FILE"
unchanged_run deployment-new-secret
[[ $(grep -c '^restart$' "$EVENTS") == 1 ]]
[[ $(wc -l < "$tmp/ledger.jsonl") == $((ledger_before + 2)) ]]

echo 'V1 shell proof: candidate acceptance PASS precedes the immediate restart.'
echo 'Unchanged-image proof: a re-run of acceptance for the running image and inputs records the PASS without restarting T3.'
echo 'Receipt guard demonstration: absent and mismatched receipts refuse tag movement and restart.'
echo 'Upgrade proof: an existing matching PASS receipt initializes a missing accepted alias without rerunning checks or restarting.'
echo 'No-receipt bootstrap proof: retained the running image, logged an alarm, and skipped candidate load/restart.'
echo 'No-running-container proof: refused bootstrap and left the accepted alias absent.'
echo 'V3 shell proof: failed acceptance is marked once and never starts or queues the image.'
echo 'V2 shell proof: a superseded exact-image receipt cannot restart the newer target.'
