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
config=$(tar -xOf "$IMAGE_ARCHIVE" manifest.json | jq -er '.[0].Config')
image=$(tar -xOf "$IMAGE_ARCHIVE" "$config" | sha256sum | cut -d ' ' -f 1)
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
    '{{ index .Config.Labels "io.ghostship.t3code.deployment" }}') printf '%s\n' "$DEPLOYMENT_ID" ;;
    *) printf 'container-id image-id started healthy %s\n' "$DEPLOYMENT_ID" ;;
  esac
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
export HOME_DIR="$tmp/home" CANDIDATE_ACCEPTANCE="$tmp/accept-candidate" PODMAN_BIN="$tmp/bin/podman"
export SYSTEMCTL_BIN="$tmp/bin/systemctl" CANDIDATE_SOCKET="$tmp/candidate.sock" CANDIDATE_UID=62041
export CANDIDATE_RUNTIME_DIR="$tmp/runtime" CANDIDATE_HOME_TARGET=/candidate-home
export PROVIDER_SECRETS_FILE="$tmp/provider.env" TOOLING_PATH="$tmp/tooling" AGENT_REVISION=agent-rev
export PYTHON_BIN="$tmp/bin/python" JQ_BIN=jq RESTART_LEDGER="$tmp/ledger.jsonl"
export AUDIT_LOG="$tmp/home/restart-audit.log" EVENTS="$tmp/events"

bash "$root/packages/t3code/deploy-image.sh" > "$tmp/success.log"
grep -q '^Candidate acceptance PASS .* receipt=' "$tmp/success.log"
grep -q '^Restarting podman-t3code.service immediately after exact-image candidate acceptance$' "$tmp/success.log"
[[ $(sed -n '1p' "$EVENTS") == candidate-accepted ]]
[[ $(sed -n '2p' "$EVENTS") == restart ]]
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
[[ $(wc -l < "$EVENTS") == 3 ]]
set +e
bash "$root/packages/t3code/deploy-image.sh" > "$tmp/replay.log" 2>&1
replay_status=$?
set -e
[[ $replay_status == 0 ]]
grep -q 'already failed .* image remains blocked' "$tmp/replay.log"
[[ $(wc -l < "$EVENTS") == 3 ]]
[[ $(wc -l < "$tmp/ledger.jsonl") == 1 ]]

echo 'V1 shell proof: candidate acceptance PASS precedes the immediate restart.'
echo 'V3 shell proof: failed acceptance is marked once and never starts or queues the image.'
