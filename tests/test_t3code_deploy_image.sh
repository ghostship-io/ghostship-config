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
    '{{.State.Health.Status}}') printf 'healthy\n' ;;
    *) printf 'container-id sha256:%s started healthy\n' "$(tar -xOf "$IMAGE_ARCHIVE" manifest.json | jq -r '.[0].Config' | xargs -I{} tar -xOf "$IMAGE_ARCHIVE" {} | sha256sum | cut -d ' ' -f 1)" ;;
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
fi
SH
cat > "$tmp/bin/systemctl" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
if [[ $1 == restart && $2 == podman-t3code.service ]]; then
  printf '%s\n' restart >> "$EVENTS"
elif [[ $1 == is-active ]]; then
  exit 0
fi
SH
cat > "$tmp/bin/systemd-cat" <<'SH'
#!/usr/bin/env bash
cat >/dev/null
SH
cat > "$tmp/bin/hostname" <<'SH'
#!/usr/bin/env bash
printf 'test-host\n'
SH
chmod +x "$tmp/bin/python" "$tmp/accept-candidate" "$tmp/bin/podman" "$tmp/bin/systemctl" "$tmp/bin/systemd-cat" "$tmp/bin/hostname"

export STATE_DIR="$tmp/state" IMAGE_ARCHIVE="$tmp/image.tar" DEPLOYMENT_ID=deployment-1
export ACCEPTED_POINTER_FILE="$tmp/state/accepted-image"
export HOME_DIR="$tmp/home" CANDIDATE_ACCEPTANCE="$tmp/accept-candidate" PODMAN_BIN="$tmp/bin/podman"
export SYSTEMCTL_BIN="$tmp/bin/systemctl" ACCEPTED_IMAGE_REF=localhost/ghostship-t3code:accepted
export CANDIDATE_SOCKET="$tmp/candidate.sock" CANDIDATE_UID=62041
export CANDIDATE_RUNTIME_DIR="$tmp/runtime" CANDIDATE_HOME_TARGET=/candidate-home
export PROVIDER_SECRETS_FILE="$tmp/provider.env" TOOLING_PATH="$tmp/tooling" AGENT_REVISION=agent-rev
export PYTHON_BIN="$tmp/bin/python" JQ_BIN=jq RESTART_LEDGER="$tmp/ledger.jsonl"
export AUDIT_LOG="$tmp/home/restart-audit.log" EVENTS="$tmp/events"

bash "$root/packages/t3code/deploy-image.sh" > "$tmp/success.log"
grep -q '^Candidate acceptance PASS .* receipt=' "$tmp/success.log"
grep -q '^Restarting podman-t3code.service immediately after exact-image candidate acceptance$' "$tmp/success.log"
[[ $(sed -n '1p' "$EVENTS") == candidate-accepted ]]
[[ $(sed -n '2p' "$EVENTS") == image-load ]]
[[ $(sed -n '3p' "$EVENTS") == image-tag ]]
[[ $(sed -n '4p' "$EVENTS") == restart ]]
[[ $(cat "$tmp/state/applied") == "$DEPLOYMENT_ID" ]]
[[ $(jq -r '.mode' "$tmp/ledger.jsonl") == candidate-accepted ]]

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
[[ $(cat "$tmp/state/failed-candidate") == "$DEPLOYMENT_ID" ]]
[[ $(wc -l < "$EVENTS") == 5 ]]
set +e
bash "$root/packages/t3code/deploy-image.sh" > "$tmp/replay.log" 2>&1
replay_status=$?
set -e
[[ $replay_status == 0 ]]
grep -q 'already failed .* image remains blocked' "$tmp/replay.log"
[[ $(wc -l < "$EVENTS") == 5 ]]
[[ $(wc -l < "$tmp/ledger.jsonl") == 1 ]]

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
[[ $(cat "$tmp/state/applied") == deployment-1 ]]
[[ $(wc -l < "$tmp/ledger.jsonl") == 1 ]]

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

echo 'V1 shell proof: candidate acceptance PASS precedes the immediate restart.'
echo 'Receipt guard demonstration: absent and mismatched receipts refuse tag movement and restart.'
echo 'Upgrade proof: an existing matching PASS receipt initializes a missing accepted alias without rerunning checks or restarting.'
echo 'V3 shell proof: failed acceptance is marked once and never starts or queues the image.'
echo 'V2 shell proof: a superseded exact-image receipt cannot restart the newer target.'
