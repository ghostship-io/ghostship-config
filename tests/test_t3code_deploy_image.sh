#!/usr/bin/env bash
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
# Avoid matching any production process-name guard; all state and stubs are isolated.
fixture_writer="$tmp/fixture-image-writer"
cp "$root/packages/t3code/deploy-image.sh" "$fixture_writer"
cp "$root/packages/t3code/receipt-checks.sh" "$tmp/receipt-checks.sh"
printf '%s\n' "$tmp/window" > "$tmp/window-config"
mkdir -p "$tmp/window"
touch "$tmp/window/window.lock"
export WINDOW_CONFIG="$tmp/window-config" WINDOW_INTENT_HELPER="$root/packages/t3code/window-intent.sh"
mkdir -p "$tmp/bin" "$tmp/state/receipts" "$tmp/home" "$tmp/home/.local/share/t3code-tools" "$tmp/runtime"
mkdir -p "$tmp/home/.local/state/t3code-shared-agents/bin"
mkdir -p "$tmp/home/.local/state/t3code-tool-update"
mkdir -p "$tmp/home/.local/share/t3code-tools/t3"
: > "$tmp/home/.local/state/t3code-tool-update/tool-update.lock"
: > "$tmp/home/.local/state/t3code-shared-agents/refresh.lock"
: > "$tmp/home/.local/share/t3code-tools/t3/update.lock"
for tool in agent ghostship ghostship-bladebro; do
  printf '#!/bin/sh\nexec /nix/store/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-agent/bin/%s "$@"\n' "$tool" > "$tmp/home/.local/state/t3code-shared-agents/bin/$tool"
  chmod 0755 "$tmp/home/.local/state/t3code-shared-agents/bin/$tool"
done
printf 'fixture\n' > "$tmp/hardening-probe.py"
printf 'fixture\n' > "$tmp/provider-turn-probe.py"
printf '[]\n' > "$tmp/runtime-caps.json"
printf '{"schema":"ghostship.route-policy/v2"}\n' > "$tmp/route-policy.json"
printf '{"schema":"ghostship.approved-free-workers/v1"}\n' > "$tmp/approved-free.json"
export ROUTE_POLICY_FILE="$tmp/route-policy.json" APPROVED_FREE_FILE="$tmp/approved-free.json"
cp "$root/packages/t3code/acceptance-launcher-key.py" "$tmp/acceptance-launcher-key.py"
export PATH="$tmp/bin:$PATH"

printf '%s\n' '{"config":{"Entrypoint":["/nix/store/test/lib/systemd/systemd"]},"rootfs":{"diff_ids":["fixture"]}}' > "$tmp/config.json"
printf '%s\n' '[{"Config":"config.json","RepoTags":["localhost/t3code:test"]}]' > "$tmp/manifest.json"
tar -cf "$tmp/image.tar" -C "$tmp" manifest.json config.json
printf 'provider=fixture\n' > "$tmp/provider.env"
mkdir -p "$tmp/tooling"
printf 'old\n' > "$tmp/state/applied"
printf 'agent=old secret_sha256=old\n' > "$tmp/state/applied-inputs"
printf '%s\n' 'deployment-1' > "$tmp/state/desired"
printf 'agent=agent-rev secret_sha256=%s\n' "$(sha256sum "$tmp/provider.env" | cut -d ' ' -f1)" > "$tmp/state/desired-inputs"
: > "$tmp/events"

cat > "$tmp/bin/python" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
if [[ $1 == */acceptance-launcher-key.py ]]; then exec python3 "$@"; fi
exec "$@"
SH
cat > "$tmp/accept-candidate" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
if flock -n "$HOME_DIR/.local/state/t3code-tool-update/tool-update.lock" true || flock -n "$HOME_DIR/.local/state/t3code-shared-agents/refresh.lock" true || flock -n "$HOME_DIR/.local/share/t3code-tools/t3/update.lock" true; then
  echo 'candidate ran without managed locks' >&2
  exit 3
fi
# When an in-container T3 app tree exists, the candidate must hold its updater
# lock too, so an app promotion cannot interleave with acceptance.
if [[ -d "$HOME_DIR/.local/share/t3code-tools/t3" ]]; then
  if flock -n "$HOME_DIR/.local/share/t3code-tools/t3/update.lock" true; then
    echo 'candidate ran without the T3 app update lock' >&2
    exit 3
  fi
fi
if [[ ${CANDIDATE_ROUTE_UNAVAILABLE:-0} == 1 ]]; then
  jq '. + {outcome:"route_unavailable",provider_turn:{routes:"fixture-exhausted"}}' "$STATE_DIR/attempts/$DEPLOYMENT_ID.json" > "$STATE_DIR/attempts/route.tmp"
  mv "$STATE_DIR/attempts/route.tmp" "$STATE_DIR/attempts/$DEPLOYMENT_ID.json"
  exit 76
fi
if [[ ${CANDIDATE_UNKNOWN:-0} == 1 ]]; then exit 2; fi
if [[ ${MUTATE_AGENT:-0} == 1 ]]; then
  printf '#!/bin/sh\nexec /nix/store/cccccccccccccccccccccccccccccccc-agent/bin/agent "$@"\n' > "$HOME_DIR/.local/state/t3code-shared-agents/bin/agent"
fi
if [[ ${CANDIDATE_PRECONDITION:-0} == 1 ]]; then
  printf '%s\n' candidate-precondition >> "$EVENTS"
  exit 75
fi
if [[ ${CANDIDATE_FAIL:-0} == 1 ]]; then
  printf '%s\n' candidate-failed >> "$EVENTS"
  exit 78
fi
printf '%s\n' candidate-accepted >> "$EVENTS"
if [[ -n ${SUPERSEDE_TO:-} ]]; then
  printf '%s\n' "$SUPERSEDE_TO" > "$STATE_DIR/desired"
  printf '%s\n' 'agent=new secret_sha256=new' > "$STATE_DIR/desired-inputs"
fi
config=$(tar -xOf "$IMAGE_ARCHIVE" manifest.json | jq -er '.[0].Config')
image=$(tar -xOf "$IMAGE_ARCHIVE" "$config" | sha256sum | cut -d ' ' -f 1)
if [[ ${RECEIPT_MISSING:-0} == 1 ]]; then exit 0; fi
if [[ ${RECEIPT_IMAGE_MISMATCH:-0} == 1 ]]; then image=unreceipted-image; fi
jq -cn \
  --arg deployment "$DEPLOYMENT_ID" --arg image "$image" --arg agent "$AGENT_REVISION" \
  --arg tooling "$TOOLING_PATH" --arg secret_sha256 "$(sha256sum "$PROVIDER_SECRETS_FILE" | cut -d ' ' -f1)" \
  '{deployment_id:$deployment,image_id:$image,candidate_name:"t3code-candidate-fixture",
    agent_revision:$agent,agent_path:$tooling,provider_secret_sha256:$secret_sha256,
    live_before:{id:"production"},live_after:{id:"production"},
    checks:{app_ready:true,provider_turn:true,agent_cli:true,skills:true,desktop_cli:true,desktop_transport:true}}' \
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
    '{{.RestartCount}}')
      if [[ ${RESTART_COUNT_UNREADABLE:-0} == 1 ]]; then exit 1; fi
      if [[ ${RESTART_COUNT_MODE:-constant} == rising ]]; then
        n=0; [[ -r ${RESTART_COUNT_CALLS:-} ]] && n=$(cat "$RESTART_COUNT_CALLS")
        n=$((n + 1)); printf '%s\n' "$n" > "$RESTART_COUNT_CALLS"
        if (( n == 1 )); then printf '0\n'; else printf '1\n'; fi
      else
        printf '%s\n' "${RESTART_COUNT_VALUE:-0}"
      fi
      ;;
    '{{.State.Running}} {{.Image}}')
      [[ ${RUNNING_CONTAINER:-1} == 1 ]] || exit 1
      printf 'true %s\n' "$RUNNING_IMAGE_ID"
      ;;
    *)
      started_field=started
      if [[ ${FIXTURE_SPACED_STARTED:-0} == 1 ]]; then
        started_field='2026-10-31 21:01:02.676622736 +0000 UTC'
      fi
      if [[ -r "$LIVE_IMAGE_FILE" ]]; then
        printf '%064d %s %s healthy\n' 1 "$(cat "$LIVE_IMAGE_FILE")" "$started_field"
      else
        printf '%064d sha256:%s %s healthy\n' 1 "$(tar -xOf "$IMAGE_ARCHIVE" manifest.json | jq -r '.[0].Config' | xargs -I{} tar -xOf "$IMAGE_ARCHIVE" {} | sha256sum | cut -d ' ' -f 1)" "$started_field"
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
  if flock -n "$HOME_DIR/.local/share/t3code-tools/t3/update.lock" true; then
    echo 'restart ran without the T3 update lock' >&2
    exit 1
  fi
  printf '%s\n' restart >> "$EVENTS"
  rm -f "$LIVE_IMAGE_FILE"
  cp "$PROVIDER_SECRETS_FILE" "$LIVE_SECRET_FILE"
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
export LIVE_IMAGE_FILE="$tmp/live-image" LIVE_SECRET_FILE="$tmp/live-secret" RESTART_COUNT_CALLS="$tmp/restart-count-calls"
printf 'provider=stale\n' > "$LIVE_SECRET_FILE"

# Model the currently running image from the host before this guard existed.
# This keeps the regular candidate-flow proof separate from the no-receipt
# bootstrap proof below.
printf '%s\n' "${RUNNING_IMAGE_ID#sha256:}" > "$ACCEPTED_POINTER_FILE"
jq -cn --arg image "${RUNNING_IMAGE_ID#sha256:}" \
  '{deployment_id:"legacy",image_id:$image,candidate_name:"t3code-candidate-legacy",
    live_before:{id:"production"},live_after:{id:"production"},
    checks:{app_ready:true,provider_turn:true,agent_cli:true,skills:true,desktop_cli:true,desktop_transport:true}}' \
  > "$STATE_DIR/receipts/legacy.json"

# An in-container T3 app tree means a competing updater can promote an app
# under us. The candidate must refuse a symlinked lock, and must hold the real
# lock through acceptance when the tree is a normal directory.
mkdir -p "$tmp/home/.local/share/t3code-tools/t3"
rm -f "$tmp/home/.local/share/t3code-tools/t3/update.lock"
ln -s "$tmp/t3-lock-target" "$tmp/home/.local/share/t3code-tools/t3/update.lock"
: > "$tmp/t3-lock-target"
if bash "$fixture_writer" > "$tmp/t3-symlink-lock.log" 2>&1; then
  echo 'symlinked T3 update lock unexpectedly allowed deployment' >&2; exit 1
fi
grep -q 'T3 update lock is not a regular file' "$tmp/t3-symlink-lock.log" || { echo 'expected the symlinked-lock refusal; got:' >&2; cat "$tmp/t3-symlink-lock.log" >&2; exit 1; }
[[ ! -s "$EVENTS" ]]
rm "$tmp/home/.local/share/t3code-tools/t3/update.lock"
bash "$fixture_writer" > "$tmp/success.log"
grep -q '^Candidate acceptance PASS .* receipt=' "$tmp/success.log"
grep -q '^Restarting podman-t3code.service immediately after exact-image candidate acceptance$' "$tmp/success.log"
[[ $(sed -n '1p' "$EVENTS") == candidate-accepted ]]
[[ $(sed -n '2p' "$EVENTS") == image-load ]]
[[ $(sed -n '3p' "$EVENTS") == image-tag ]]
[[ $(sed -n '4p' "$EVENTS") == restart ]]
[[ $(cat "$tmp/state/applied") == "$DEPLOYMENT_ID" ]]
[[ $(jq -r '.mode' "$tmp/ledger.jsonl") == candidate-accepted ]]
attestation="$STATE_DIR/attestations/current.json"
jq -e --arg image "$(tar -xOf "$IMAGE_ARCHIVE" config.json | sha256sum | cut -d ' ' -f 1)" \
  --arg receipt "$DEPLOYMENT_ID" --arg sha "$(sha256sum "$STATE_DIR/receipts/$DEPLOYMENT_ID.json" | cut -d ' ' -f 1)" \
  '.state == "pass" and .image_id == $image and .receipt_id == $receipt and .receipt_sha256 == $sha and .failed_candidate == false and (.container_id | length == 64)' \
  "$attestation" >/dev/null
[[ $(stat -c %a "$attestation") == 444 ]]
# StartedAt contains spaces in production. The health status must come from the
# final field, so a healthy container still publishes the PASS attestation.
export FIXTURE_SPACED_STARTED=1
rm -rf "$STATE_DIR/attestations"
bash "$fixture_writer" > "$tmp/spaced-started.log"
grep -q 'already applied' "$tmp/spaced-started.log" || { echo 'spaced StartedAt did not take the already-applied path' >&2; cat "$tmp/spaced-started.log" >&2; exit 1; }
jq -e '.state == "pass"' "$STATE_DIR/attestations/current.json" >/dev/null || { echo 'spaced StartedAt did not publish a PASS attestation' >&2; cat "$STATE_DIR/attestations/current.json" >&2; exit 1; }
jq -e '.container_id | length == 64' "$STATE_DIR/attestations/current.json" >/dev/null || { echo 'attestation lost the container identity' >&2; exit 1; }
unset FIXTURE_SPACED_STARTED


# A restart that remains starting for more than 120 simulated seconds must
# still reach the existing post-restart checks and applied marker.
saved_events=$EVENTS
EVENTS="$tmp/health-events"
: > "$EVENTS"
export DEPLOYMENT_ID=deployment-slow-healthy HEALTHY_AFTER_SECONDS=130
printf 'sha256:%s\n' "$(printf 'health-older-image' | sha256sum | cut -d ' ' -f 1)" > "$LIVE_IMAGE_FILE"
printf '%s\n' "$DEPLOYMENT_ID" > "$STATE_DIR/desired"
printf 'agent=agent-rev secret_sha256=%s\n' "$(sha256sum "$PROVIDER_SECRETS_FILE" | cut -d ' ' -f1)" > "$STATE_DIR/desired-inputs"
printf '0\n' > "$HEALTH_CLOCK_FILE"
bash "$fixture_writer" > "$tmp/slow-healthy.log"
[[ $(cat "$STATE_DIR/applied") == "$DEPLOYMENT_ID" ]]
[[ $(cat "$HEALTH_CLOCK_FILE") -ge 130 ]]
[[ $(wc -l < "$tmp/ledger.jsonl") == 2 ]]

# A real timeout stays non-zero and cannot advance either applied marker.
export DEPLOYMENT_ID=deployment-never-healthy HEALTHY_AFTER_SECONDS=999
export HEALTH_WAIT_BUDGET_SECONDS=20
printf 'sha256:%s\n' "$(printf 'never-healthy-image' | sha256sum | cut -d ' ' -f 1)" > "$LIVE_IMAGE_FILE"
printf '%s\n' "$DEPLOYMENT_ID" > "$STATE_DIR/desired"
printf 'agent=agent-rev secret_sha256=%s\n' "$(sha256sum "$PROVIDER_SECRETS_FILE" | cut -d ' ' -f1)" > "$STATE_DIR/desired-inputs"
applied_before=$(cat "$STATE_DIR/applied")
applied_inputs_before=$(cat "$STATE_DIR/applied-inputs")
printf '0\n' > "$HEALTH_CLOCK_FILE"
set +e
bash "$fixture_writer" > "$tmp/never-healthy.log" 2>&1
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
bash "$fixture_writer" > "$tmp/failure.log" 2>&1
first_status=$?
set -e
[[ $first_status != 0 ]]
grep -q 'Candidate acceptance FAILED' "$tmp/failure.log"
[[ $(cut -d ' ' -f 1 "$tmp/state/failed-candidate") == "$DEPLOYMENT_ID" ]]
jq -e '.state == "unknown" and .failed_candidate == true' "$attestation" >/dev/null
[[ $(jq -r '.deployment_id + ":" + (.exit_code | tostring)' "$tmp/state/attempts/$DEPLOYMENT_ID.json") == "$DEPLOYMENT_ID:1" ]]
[[ $(jq -r '.started_at_ms | numbers' "$tmp/state/attempts/$DEPLOYMENT_ID.json") =~ ^[0-9]+$ ]]
[[ $(wc -l < "$EVENTS") == 5 ]]
set +e
bash "$fixture_writer" > "$tmp/replay.log" 2>&1
replay_status=$?
set -e
[[ $replay_status == 0 ]]
grep -q 'already failed .* image remains blocked' "$tmp/replay.log"
[[ $(wc -l < "$EVENTS") == 5 ]]
[[ $(wc -l < "$tmp/ledger.jsonl") == 2 ]]

# An unrelated file cannot release a failed candidate, but a changed module
# that acceptance runs must trigger a new acceptance for the same image.
mark_failed_key=$(cat "$tmp/state/failed-candidate")
printf 'unrelated\n' > "$tmp/unrelated.txt"
bash "$fixture_writer" > "$tmp/unrelated.log" 2>&1
grep -q 'already failed .* image remains blocked' "$tmp/unrelated.log"
saved_events=$EVENTS
EVENTS="$tmp/probe-rerun-events"
for input in provider-turn-probe.py hardening-probe.py runtime-caps.json route-policy.json approved-free.json; do
  cp "$tmp/$input" "$tmp/input-original"
  printf '# acceptance input fix\n' >> "$tmp/$input"
  set +e
  bash "$fixture_writer" > "$tmp/probe-rerun.log" 2>&1
  probe_status=$?
  set -e
  [[ $probe_status != 0 ]]
  grep -q 'Candidate acceptance FAILED' "$tmp/probe-rerun.log"
  if grep -q 'already failed' "$tmp/probe-rerun.log"; then echo 'changed acceptance input was blocked' >&2; exit 1; fi
  cp "$tmp/input-original" "$tmp/$input"
  printf '%s\n' "$mark_failed_key" > "$tmp/state/failed-candidate"
done
cp "$tmp/home/.local/state/t3code-shared-agents/bin/agent" "$tmp/agent-original"
printf '#!/bin/sh\nexec /nix/store/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb-agent/bin/agent "$@"\n' > "$tmp/home/.local/state/t3code-shared-agents/bin/agent"
set +e
bash "$fixture_writer" > "$tmp/agent-rerun.log" 2>&1
agent_status=$?
set -e
[[ $agent_status != 0 ]]
grep -q 'Candidate acceptance FAILED' "$tmp/agent-rerun.log"
cp "$tmp/agent-original" "$tmp/home/.local/state/t3code-shared-agents/bin/agent"
printf '%s\n' "$mark_failed_key" > "$tmp/state/failed-candidate"

export DEPLOYMENT_ID=deployment-route-unavailable CANDIDATE_ROUTE_UNAVAILABLE=1 CANDIDATE_FAIL=0
printf '%s\n' "$DEPLOYMENT_ID" > "$tmp/state/desired"
set +e
bash "$fixture_writer" > "$tmp/route-unavailable.log" 2>&1
route_status=$?
set -e
[[ $route_status == 76 && $(cat "$tmp/state/failed-candidate") == "$mark_failed_key" ]]
jq -e '.outcome == "route_unavailable" and .provider_turn.routes == "fixture-exhausted"' "$tmp/state/attempts/$DEPLOYMENT_ID.json" >/dev/null
unset CANDIDATE_ROUTE_UNAVAILABLE
export DEPLOYMENT_ID=deployment-acceptance-unknown CANDIDATE_UNKNOWN=1
printf '%s\n' "$DEPLOYMENT_ID" > "$tmp/state/desired"
set +e
bash "$fixture_writer" > "$tmp/acceptance-unknown.log" 2>&1
unknown_status=$?
set -e
[[ $unknown_status == 77 && $(cat "$tmp/state/failed-candidate") == "$mark_failed_key" ]]
jq -e '.outcome == "acceptance_unknown"' "$tmp/state/attempts/$DEPLOYMENT_ID.json" >/dev/null
unset CANDIDATE_UNKNOWN
export DEPLOYMENT_ID=deployment-2 CANDIDATE_FAIL=1
printf '%s\n' "$DEPLOYMENT_ID" > "$tmp/state/desired"
# If a writer ignores the locks and changes a launcher during the candidate,
# the observed failure is not attributed to either code identity.
printf '# probe fix\n' >> "$tmp/provider-turn-probe.py"
export MUTATE_AGENT=1 CANDIDATE_FAIL=0
set +e
bash "$fixture_writer" > "$tmp/changed-during.log" 2>&1
changed_status=$?
set -e
unset MUTATE_AGENT
[[ $changed_status == 75 && $(cat "$tmp/state/failed-candidate") == "$mark_failed_key" ]]
[[ ! -e "$tmp/state/receipts/$DEPLOYMENT_ID.json" ]]
grep -q 'Managed launcher changed during acceptance' "$tmp/changed-during.log"
export CANDIDATE_FAIL=1
cp "$tmp/agent-original" "$tmp/home/.local/state/t3code-shared-agents/bin/agent"
printf 'fixture\n' > "$tmp/provider-turn-probe.py"
rm -f "$tmp/state/precondition-attempts"
cp "$tmp/image.tar" "$tmp/image-original.tar"
cp "$tmp/config.json" "$tmp/config-original.json"
printf '%s\n' '{"config":{"Entrypoint":["/nix/store/test/lib/systemd/systemd"]},"rootfs":{"diff_ids":["different-candidate"]}}' > "$tmp/config.json"
tar -cf "$tmp/image.tar" -C "$tmp" manifest.json config.json
set +e
bash "$fixture_writer" > "$tmp/new-image.log" 2>&1
new_image_status=$?
set -e
[[ $new_image_status != 0 ]]
grep -q 'Candidate acceptance FAILED' "$tmp/new-image.log"
cp "$tmp/image-original.tar" "$tmp/image.tar"
cp "$tmp/config-original.json" "$tmp/config.json"
printf '%s\n' "$mark_failed_key" > "$tmp/state/failed-candidate"
mv "$tmp/hardening-probe.py" "$tmp/hardening-probe.saved"
set +e
bash "$fixture_writer" > "$tmp/missing-input.log" 2>&1
missing_status=$?
set -e
[[ $missing_status != 0 && $(cat "$tmp/state/failed-candidate") == "$mark_failed_key" ]]
mv "$tmp/hardening-probe.saved" "$tmp/hardening-probe.py"
EVENTS=$saved_events

# Operators can explicitly invalidate only with a durable recorded reason;
# this does not itself run acceptance or move the accepted image.
set +e
bash "$fixture_writer" --invalidate-failure '' > "$tmp/invalidate-empty.log" 2>&1
empty_status=$?
set -e
[[ $empty_status != 0 && -e "$tmp/state/failed-candidate" ]]
set +e
JQ_BIN=/bin/false bash "$fixture_writer" --invalidate-failure 'audit unavailable' > "$tmp/invalidate-error.log" 2>&1
audit_error=$?
set -e
[[ $audit_error != 0 && $(cat "$tmp/state/failed-candidate") == "$mark_failed_key" ]]
before_events=$(wc -l < "$EVENTS")
bash "$fixture_writer" --invalidate-failure 'probe repaired' > "$tmp/invalidate.log"
[[ ! -e "$tmp/state/failed-candidate" ]]
[[ $(wc -l < "$EVENTS") == "$before_events" ]]
jq -e --arg marker "$mark_failed_key" '.event == "invalidation_requested" and .reason == "probe repaired" and .failed_key == $marker and (.at | type == "string")' "$tmp/state/failure-invalidations.jsonl" > /dev/null
printf '%s\n' "$mark_failed_key" > "$tmp/state/failed-candidate"

# A changed acceptance check re-runs acceptance for the same image instead of
# replaying the old failure; the new run still decides. Its events stay out of
# the counts asserted below.
saved_events=$EVENTS
EVENTS="$tmp/rerun-events"
cp "$CANDIDATE_ACCEPTANCE" "$tmp/accept-candidate.orig"
printf '\n# acceptance fix\n' >> "$CANDIDATE_ACCEPTANCE"
set +e
bash "$fixture_writer" > "$tmp/rerun.log" 2>&1
rerun_status=$?
set -e
[[ $rerun_status != 0 ]]
grep -q 'Candidate acceptance FAILED' "$tmp/rerun.log"
! grep -q 'already failed' "$tmp/rerun.log"
cp "$tmp/accept-candidate.orig" "$CANDIDATE_ACCEPTANCE"
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
  bash "$fixture_writer" > "$tmp/precondition-$1.log" 2>&1
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
bash "$fixture_writer" > "$tmp/precondition-then-fail.log" 2>&1
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
printf 'agent=agent-rev secret_sha256=%s\n' "$(sha256sum "$tmp/provider.env" | cut -d ' ' -f1)" > "$tmp/state/desired-inputs"
set +e
bash "$fixture_writer" > "$tmp/absent.log" 2>&1
absent_status=$?
set -e
[[ $absent_status != 0 ]]
grep -q 'receipt did not approve this exact image' "$tmp/absent.log"
[[ $(cat "$tmp/state/failed-candidate") == "$mark_failed_key" ]]
jq -e '.outcome == "acceptance_unknown"' "$tmp/state/attempts/$DEPLOYMENT_ID.json" >/dev/null
[[ $(wc -l < "$EVENTS") == 6 ]]

# A closed-unaccepted window record is not a receipt: with the deployment
# marked applied and identical inputs it must not take the already-applied
# fast path, and the run must still fail on the receipt gate.
export DEPLOYMENT_ID=deployment-closed RECEIPT_MISSING=1 RECEIPT_IMAGE_MISMATCH=0
saved_closed_events=$EVENTS; EVENTS="$tmp/closed-events"; : > "$EVENTS"
saved_applied=$(cat "$tmp/state/applied"); saved_applied_inputs=$(cat "$tmp/state/applied-inputs")
printf '%s\n' "$DEPLOYMENT_ID" > "$tmp/state/desired"
printf 'agent=agent-rev secret_sha256=%s\n' "$(sha256sum "$tmp/provider.env" | cut -d ' ' -f1)" > "$tmp/state/desired-inputs"
printf '%s\n' "$DEPLOYMENT_ID" > "$tmp/state/applied"
cp "$tmp/state/desired-inputs" "$tmp/state/applied-inputs"
printf '{"state":"closed_unaccepted","deployment_id":"%s"}\n' "$DEPLOYMENT_ID" > "$tmp/state/closed-unaccepted.json"
set +e
bash "$fixture_writer" > "$tmp/closed-fast.log" 2>&1
closed_status=$?
set -e
[[ $closed_status != 0 ]]
! grep -q 'already applied' "$tmp/closed-fast.log" || { echo 'closed-unaccepted took the already-applied fast path' >&2; cat "$tmp/closed-fast.log" >&2; exit 1; }
grep -q 'receipt did not approve this exact image' "$tmp/closed-fast.log"
rm -f "$tmp/state/closed-unaccepted.json"
printf '%s\n' "$saved_applied" > "$tmp/state/applied"
printf '%s\n' "$saved_applied_inputs" > "$tmp/state/applied-inputs"
EVENTS=$saved_closed_events

# A mismatched receipt is also rejected before the accepted alias can move.
export DEPLOYMENT_ID=deployment-mismatch RECEIPT_MISSING=0 RECEIPT_IMAGE_MISMATCH=1
printf '%s\n' "$DEPLOYMENT_ID" > "$tmp/state/desired"
printf 'agent=agent-rev secret_sha256=%s\n' "$(sha256sum "$tmp/provider.env" | cut -d ' ' -f1)" > "$tmp/state/desired-inputs"
set +e
bash "$fixture_writer" > "$tmp/mismatch.log" 2>&1
mismatch_status=$?
set -e
[[ $mismatch_status != 0 ]]
grep -q 'receipt did not approve this exact image' "$tmp/mismatch.log"
[[ $(cat "$tmp/state/failed-candidate") == "$mark_failed_key" ]]
[[ $(wc -l < "$EVENTS") == 7 ]]

# A target changed while acceptance ran must not be restarted with the old
# image's receipt. Activation normally serializes this mutation on deploy.lock;
# this guard also fails safely if an out-of-band writer changes desired.
export DEPLOYMENT_ID=deployment-3 SUPERSEDE_TO=deployment-4 CANDIDATE_FAIL=0 RECEIPT_IMAGE_MISMATCH=0
printf '%s\n' "$DEPLOYMENT_ID" > "$tmp/state/desired"
printf 'agent=agent-rev secret_sha256=%s\n' "$(sha256sum "$tmp/provider.env" | cut -d ' ' -f1)" > "$tmp/state/desired-inputs"
set +e
bash "$fixture_writer" > "$tmp/superseded.log" 2>&1
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
printf 'agent=agent-rev secret_sha256=%s\n' "$(sha256sum "$tmp/provider.env" | cut -d ' ' -f1)" > "$tmp/state/desired-inputs"
cp "$tmp/state/desired-inputs" "$tmp/state/applied-inputs"
printf '%s\n' "$DEPLOYMENT_ID" > "$tmp/state/applied"
config=$(tar -xOf "$IMAGE_ARCHIVE" manifest.json | jq -er '.[0].Config')
repair_image=$(tar -xOf "$IMAGE_ARCHIVE" "$config" | sha256sum | cut -d ' ' -f 1)
jq -cn --arg deployment "$DEPLOYMENT_ID" --arg image "$repair_image" \
  --arg agent "$AGENT_REVISION" --arg tooling "$TOOLING_PATH" \
  --arg secret_sha256 "$(sha256sum "$PROVIDER_SECRETS_FILE" | cut -d ' ' -f1)" \
  '{deployment_id:$deployment,image_id:$image,candidate_name:"t3code-candidate-existing",
    agent_revision:$agent,agent_path:$tooling,provider_secret_sha256:$secret_sha256,
    live_before:{id:"production"},live_after:{id:"production"},
    checks:{app_ready:true,provider_turn:true,agent_cli:true,skills:true,desktop_cli:true,desktop_transport:true}}' \
  > "$tmp/state/receipts/$DEPLOYMENT_ID.json"
rm -f "$ACCEPTED_POINTER_FILE"
bash "$fixture_writer" > "$tmp/repair.log"
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
printf 'agent=agent-rev secret_sha256=%s\n' "$(sha256sum "$PROVIDER_SECRETS_FILE" | cut -d ' ' -f1)" > "$STATE_DIR/desired-inputs"
set +e
bash "$fixture_writer" > "$tmp/bootstrap.log" 2>&1
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
printf 'agent=agent-rev secret_sha256=%s\n' "$(sha256sum "$PROVIDER_SECRETS_FILE" | cut -d ' ' -f1)" > "$STATE_DIR/desired-inputs"
set +e
bash "$fixture_writer" > "$tmp/no-running.log" 2>&1
no_running_status=$?
set -e
[[ $no_running_status != 0 ]]
grep -q 'no T3 container is running and no accepted alias exists' "$tmp/no-running.log"
[[ ! -e "$ACCEPTED_POINTER_FILE" ]]
[[ ! -s "$EVENTS" ]]

# A re-run of acceptance for the image T3 already runs, with the same agent
# and provider secret content (only the secret's inode is new after a switch, while its digest stays the same),
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
  printf 'agent=agent-rev secret_sha256=%s\n' "$(sha256sum "$PROVIDER_SECRETS_FILE" | cut -d ' ' -f1)" > "$STATE_DIR/desired-inputs"
  printf '0\n' > "$HEALTH_CLOCK_FILE"
  bash "$fixture_writer" > "$tmp/$1.log" 2>&1
  [[ $(cat "$STATE_DIR/applied") == "$1" ]]
  grep -q candidate-accepted "$EVENTS"
}
cp "$PROVIDER_SECRETS_FILE" "$LIVE_SECRET_FILE"
unchanged_run deployment-unchanged
grep -q 'PASS recorded, no restart' "$tmp/deployment-unchanged.log"
! grep -q restart "$EVENTS"
[[ $(wc -l < "$tmp/ledger.jsonl") == "$ledger_before" ]]
[[ $(jq -r .deployment_id "$STATE_DIR/deployed-inputs.json") == deployment-unchanged ]]
# Legacy applied inputs and a legacy receipt still take the applied fast path
# and are upgraded to the digest form without a restart.
cp "$PROVIDER_SECRETS_FILE" "$LIVE_SECRET_FILE"
export DEPLOYMENT_ID=deployment-legacy
legacy_image=$(tar -xOf "$IMAGE_ARCHIVE" manifest.json | jq -er '.[0].Config' | xargs -I{} tar -xOf "$IMAGE_ARCHIVE" {} | sha256sum | cut -d ' ' -f 1)
printf '%s\n' "$DEPLOYMENT_ID" > "$STATE_DIR/applied"
printf '%s\n' "$DEPLOYMENT_ID" > "$STATE_DIR/desired"
printf 'agent=agent-rev secret_inode=%s tooling=%s\n' "$(stat -Lc '%i' "$PROVIDER_SECRETS_FILE")" "$TOOLING_PATH" > "$STATE_DIR/applied-inputs"
printf 'agent=agent-rev secret_sha256=%s tooling=%s\n' "$(sha256sum "$PROVIDER_SECRETS_FILE" | cut -d ' ' -f1)" "$TOOLING_PATH" > "$STATE_DIR/desired-inputs"
jq -n --arg d "$DEPLOYMENT_ID" --arg i "$legacy_image" --arg p "$TOOLING_PATH" --arg ino "$(stat -Lc '%i' "$PROVIDER_SECRETS_FILE")" '{deployment_id:$d,image_id:$i,candidate_name:"t3code-candidate-fixture",agent_revision:"agent-rev",agent_path:$p,provider_secret_inode:$ino,live_before:{id:"live"},live_after:{id:"live"},checks:{app_ready:true,provider_turn:true,agent_cli:true,skills:true,desktop_cli:true,desktop_transport:true}}' > "$STATE_DIR/receipts/$DEPLOYMENT_ID.json"
printf '0\n' > "$HEALTH_CLOCK_FILE"
bash "$fixture_writer" > "$tmp/deployment-legacy.log" 2>&1
grep -q 'already applied' "$tmp/deployment-legacy.log"
grep -q 'secret_sha256=' "$STATE_DIR/applied-inputs"
# Both lines may still be legacy. Exact equality stays a no-op: no digest is
# present, so the old string rule decides and nothing restarts.
export DEPLOYMENT_ID=deployment-both-legacy
both_legacy="agent=agent-rev secret_inode=$(stat -Lc '%i' "$PROVIDER_SECRETS_FILE") tooling=$TOOLING_PATH"
printf '%s\n' "$DEPLOYMENT_ID" > "$STATE_DIR/applied"
printf '%s\n' "$DEPLOYMENT_ID" > "$STATE_DIR/desired"
printf '%s\n' "$both_legacy" > "$STATE_DIR/applied-inputs"
printf '%s\n' "$both_legacy" > "$STATE_DIR/desired-inputs"
jq -n --arg d "$DEPLOYMENT_ID" --arg i "$legacy_image" --arg p "$TOOLING_PATH" --arg s "$(sha256sum "$PROVIDER_SECRETS_FILE" | cut -d ' ' -f1)" '{deployment_id:$d,image_id:$i,candidate_name:"t3code-candidate-fixture",agent_revision:"agent-rev",agent_path:$p,provider_secret_sha256:$s,live_before:{id:"live"},live_after:{id:"live"},checks:{app_ready:true,provider_turn:true,agent_cli:true,skills:true,desktop_cli:true,desktop_transport:true}}' > "$STATE_DIR/receipts/$DEPLOYMENT_ID.json"
: > "$EVENTS"
printf '0\n' > "$HEALTH_CLOCK_FILE"
bash "$fixture_writer" > "$tmp/deployment-both-legacy.log" 2>&1
grep -q 'already applied' "$tmp/deployment-both-legacy.log"
! grep -q '^restart$' "$EVENTS"
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

# A missing updater lock must be created owned by the home owner and unreadable
# to others, because the in-container updater runs as that user and opens it for
# append. Creating it as the deploying process with a default umask left a
# root-owned 0644 lock that broke every app update with EACCES.
export STATE_DIR="$tmp/state" ACCEPTED_POINTER_FILE="$tmp/state/accepted-image" RUNNING_CONTAINER=1
export ALARM_LOG="$tmp/alarms.log" EVENTS="$tmp/lock-bootstrap-events" HEALTH_WAIT_BUDGET_SECONDS=390 HEALTHY_AFTER_SECONDS=0
export CANDIDATE_FAIL=0 CANDIDATE_PRECONDITION=0 RECEIPT_MISSING=0 RECEIPT_IMAGE_MISMATCH=0
export DEPLOYMENT_ID=deployment-lock-bootstrap
printf '%s\n' "$DEPLOYMENT_ID" > "$STATE_DIR/desired"
rm -f "$tmp/home/.local/share/t3code-tools/t3/update.lock"
bash "$fixture_writer" > "$tmp/lock-bootstrap.log" 2>&1 || true
[[ -f "$tmp/home/.local/share/t3code-tools/t3/update.lock" ]]
[[ $(stat -c '%a' "$tmp/home/.local/share/t3code-tools/t3/update.lock") == 600 ]]
[[ $(stat -c '%u:%g' "$tmp/home/.local/share/t3code-tools/t3/update.lock") == "$(stat -c '%u:%g' "$tmp/home")" ]]
echo 'Updater lock bootstrap proof: a missing app lock is created owner-owned and private.'

# With a real app tree and no lock yet, a re-run bootstraps the lock for the
# home owner: the updater opens the same file later, so its ownership matters.
rm -f "$tmp/home/.local/share/t3code-tools/t3/update.lock"
bash "$fixture_writer" > "$tmp/t3-bootstrap-lock.log" 2>&1 || { echo 'bootstrap run failed:' >&2; cat "$tmp/t3-bootstrap-lock.log" >&2; exit 1; }
[[ -f "$tmp/home/.local/share/t3code-tools/t3/update.lock" ]] || { echo 'T3 update lock was not bootstrapped' >&2; exit 1; }
[[ $(stat -c '%u:%g' "$tmp/home/.local/share/t3code-tools/t3/update.lock") == "$(stat -c '%u:%g' "$tmp/home")" ]] || { echo 'bootstrapped T3 update lock has the wrong owner' >&2; exit 1; }
# A step that fails after the attempt-result EXIT trap is installed must still
# say why it exited; the trap replaces the earlier logger, so the writer itself
# must emit the rc line.
export DEPLOYMENT_ID=deployment-post-trap
printf '%s\n' "$DEPLOYMENT_ID" > "$STATE_DIR/desired"
printf 'agent=agent-rev secret_sha256=%s\n' "$(sha256sum "$tmp/provider.env" | cut -d ' ' -f1)" > "$STATE_DIR/desired-inputs"
rm -f "$tmp/missing-provider.env"
post_trap_status=0
PROVIDER_SECRETS_FILE="$tmp/missing-provider.env" bash "$fixture_writer" > "$tmp/post-trap.log" 2>&1 || post_trap_status=$?
[[ $post_trap_status -ne 0 ]] || { echo 'missing provider secret did not fail the deploy' >&2; exit 1; }
grep -q 'deploy: exiting rc=1' "$tmp/post-trap.log" || { echo 'post-trap failure exited silently' >&2; cat "$tmp/post-trap.log" >&2; exit 1; }
jq -e '.exit_code == 1' "$STATE_DIR/attempts/$DEPLOYMENT_ID.json" >/dev/null || { echo 'post-trap attempt did not record rc=1' >&2; cat "$STATE_DIR/attempts/$DEPLOYMENT_ID.json" >&2; exit 1; }
echo 'Post-trap failure proof: a step after the attempt trap records and logs deploy: exiting rc=1.'

# Restart-count dwell: a restart after this deploy's own restart fails the
# settle. The exit code must not be 75 (systemd would retry and restart T3),
# nothing is recorded applied, and no second restart is issued. An unreadable
# count is UNKNOWN and fails closed.
dwell_case() {
  local id=$1 mode=$2
  : > "$EVENTS"
  export DEPLOYMENT_ID=$id
  printf '%s\n' "$DEPLOYMENT_ID" > "$STATE_DIR/desired"
  printf 'agent=agent-rev secret_sha256=%s\n' "$(sha256sum "$PROVIDER_SECRETS_FILE" | cut -d ' ' -f1)" > "$STATE_DIR/desired-inputs"
  printf 'sha256:%s\n' "$(printf 'dwell-older-%s' "$id" | sha256sum | cut -d ' ' -f 1)" > "$LIVE_IMAGE_FILE"
  printf '0\n' > "$HEALTH_CLOCK_FILE"
  rm -f "$RESTART_COUNT_CALLS"
  export RESTART_COUNT_MODE=$mode
  if [[ $mode == unreadable ]]; then export RESTART_COUNT_UNREADABLE=1; else unset RESTART_COUNT_UNREADABLE; fi
  set +e
  bash "$fixture_writer" > "$tmp/$id.log" 2>&1
  dwell_rc=$?
  set -e
  unset RESTART_COUNT_MODE RESTART_COUNT_UNREADABLE
}
applied_before=$(cat "$STATE_DIR/applied")
dwell_case deployment-dwell-rising rising
[[ $dwell_rc == 1 ]] || { echo "rising restart count exit=$dwell_rc, want 1 (never 75)" >&2; cat "$tmp/deployment-dwell-rising.log" >&2; exit 1; }
[[ $(cat "$STATE_DIR/applied") == "$applied_before" ]] || { echo 'rising count recorded the deployment applied' >&2; exit 1; }
[[ $(grep -c '^restart$' "$EVENTS") == 1 ]] || { echo 'rising count issued a second restart' >&2; cat "$EVENTS" >&2; exit 1; }
grep -q 'restarted again during the 180s settle' "$tmp/deployment-dwell-rising.log"
jq -e '.exit_code == 1' "$STATE_DIR/attempts/deployment-dwell-rising.json" >/dev/null
dwell_case deployment-dwell-constant constant
[[ $dwell_rc == 0 ]] || { echo "constant count exit=$dwell_rc" >&2; cat "$tmp/deployment-dwell-constant.log" >&2; exit 1; }
[[ $(cat "$STATE_DIR/applied") == deployment-dwell-constant ]] || { echo 'constant count did not record applied' >&2; exit 1; }
dwell_case deployment-dwell-unreadable unreadable
[[ $dwell_rc == 1 ]] || { echo "unreadable count exit=$dwell_rc" >&2; cat "$tmp/deployment-dwell-unreadable.log" >&2; exit 1; }
grep -q 'restart count unreadable' "$tmp/deployment-dwell-unreadable.log"
[[ $(cat "$STATE_DIR/applied") == deployment-dwell-constant ]] || { echo 'unreadable count recorded applied' >&2; exit 1; }
echo 'Restart-count dwell proof: rising count fails without rc 75 or a second restart; unreadable is UNKNOWN.'

echo 'Deploy-image fixture passed.'
