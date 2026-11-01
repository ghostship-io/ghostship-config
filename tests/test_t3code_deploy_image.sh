#!/usr/bin/env bash
# Deploy-image proofs: the deployer runs only mechanical activation checks.
# There is no candidate container, provider turn, skills or desktop suite here;
# those live outside deployment (just acceptance).
set -euo pipefail
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
writer="$tmp/fixture-image-writer"
cp "$root/packages/t3code/deploy-image.sh" "$writer"
cp "$root/packages/t3code/receipt-checks.sh" "$tmp/receipt-checks.sh"
mkdir -p "$tmp/bin" "$tmp/state/receipts" "$tmp/home" "$tmp/runtime" "$tmp/tooling"
mkdir -p "$tmp/home/.local/state/t3code-tool-update" "$tmp/home/.local/state/t3code-shared-agents"
mkdir -p "$tmp/home/.local/share/t3code-tools/t3"
: > "$tmp/home/.local/state/t3code-tool-update/tool-update.lock"
: > "$tmp/home/.local/state/t3code-shared-agents/refresh.lock"
: > "$tmp/home/.local/share/t3code-tools/t3/update.lock"

printf '%s\n' '{"config":{"Entrypoint":["/bin/sh"]},"rootfs":{"diff_ids":["fixture"]}}' > "$tmp/config.json"
printf '%s\n' '[{"Config":"config.json","RepoTags":["localhost/t3code:test"]}]' > "$tmp/manifest.json"
tar -cf "$tmp/image.tar" -C "$tmp" manifest.json config.json
image_id=$(tar -xOf "$tmp/image.tar" config.json | sha256sum | cut -d ' ' -f 1)
printf 'provider=fixture\n' > "$tmp/provider.env"
secret_sha=$(sha256sum "$tmp/provider.env" | cut -d ' ' -f 1)
printf 'deployment-1\n' > "$tmp/state/desired"
printf 'agent=agent-rev secret_sha256=%s tooling=%s\n' "$secret_sha" "$tmp/tooling" > "$tmp/state/desired-inputs"
printf 'old\n' > "$tmp/state/applied"
printf 'agent=old secret_sha256=old tooling=old\n' > "$tmp/state/applied-inputs"
printf '%s\n' "sha256:$(printf 'other-image' | sha256sum | cut -d ' ' -f 1)" > "$tmp/accepted-image"
: > "$tmp/events"

cat > "$tmp/bin/podman" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
if [[ $1 == load ]]; then
  echo load >> "$EVENTS"
  exit 0
fi
if [[ $1 == inspect && $2 == t3code ]]; then
  case "${4:-}" in
    '{{.State.Health.Status}}')
      now=$(cat "$HEALTH_CLOCK_FILE")
      if (( now >= HEALTHY_AFTER_SECONDS )); then printf 'healthy\n'; else printf 'starting\n'; fi
      ;;
    '{{.State.Running}} {{.Image}}')
      printf 'true %s\n' "$(cat "$LIVE_IMAGE_FILE")"
      ;;
    '{{.Id}} {{.Image}} {{.State.StartedAt}} {{.State.Health.Status}}')
      calls=0; [[ -r $IDENTITY_CALLS ]] && calls=$(cat "$IDENTITY_CALLS")
      calls=$((calls + 1)); printf '%s\n' "$calls" > "$IDENTITY_CALLS"
      id=$(printf '%064d' 1); started=started
      if [[ ${IDENTITY_MODE:-stable} == change && $calls -ge 3 ]]; then
        id=$(printf '%064d' 2); started=restarted
      fi
      if [[ ${IDENTITY_MODE:-stable} == empty && $calls -ge 3 ]]; then exit 1; fi
      printf '%s %s %s healthy\n' "$id" "$(cat "$LIVE_IMAGE_FILE")" "$started"
      ;;
    '{{.Image}}') cat "$LIVE_IMAGE_FILE" ;;
    *) exit 1 ;;
  esac
  exit 0
fi
if [[ $1 == tag ]]; then
  printf '%s\n' "${2#sha256:}" > "$ACCEPTED_POINTER_FILE"
  exit 0
fi
if [[ $1 == image && $2 == inspect ]]; then
  if [[ ${3:-} == sha256:* && -n ${FIXTURE_LOADED_ID:-} ]]; then
    printf 'sha256:%s\n' "$FIXTURE_LOADED_ID"
  else
    cat "$ACCEPTED_POINTER_FILE"
  fi
  exit 0
fi
if [[ $1 == exec ]]; then
  case "$3" in
    systemctl) exit 0 ;;
    curl) exit 0 ;;
    readlink) printf '%s\n' "$TOOLING_PATH" ;;
    sha256sum) printf '%s  /run/secrets/t3code.env\n' "$(sha256sum < "$PROVIDER_SECRETS_FILE" | cut -d ' ' -f 1)" ;;
    *) exit 0 ;;
  esac
fi
exit 0
SH
cat > "$tmp/bin/systemctl" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
[[ $1 == restart ]] || exit 0
printf '%s\n' "$2" >> "$EVENTS"
printf '%s\n' "$DEPLOYED_IMAGE" > "$LIVE_IMAGE_FILE"
SH
cat > "$tmp/bin/systemd-cat" <<'SH'
#!/usr/bin/env bash
cat >/dev/null || true
SH
cat > "$tmp/bin/receipt-self-check" <<'SH'
#!/usr/bin/env bash
printf 'alarm\n' >> "$EVENTS"
SH
cat > "$tmp/bin/hostname" <<'SH'
#!/usr/bin/env bash
printf 'fixture-host\n'
SH
cat > "$tmp/bin/health-clock" <<'SH'
#!/usr/bin/env bash
cat "$HEALTH_CLOCK_FILE"
SH
cat > "$tmp/bin/health-sleep" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$(( $(cat "$HEALTH_CLOCK_FILE") + $1 ))" > "$HEALTH_CLOCK_FILE"
SH
chmod +x "$tmp"/bin/*

export STATE_DIR="$tmp/state" IMAGE_ARCHIVE="$tmp/image.tar" DEPLOYMENT_ID=deployment-1
export ACCEPTED_IMAGE_REF=localhost/ghostship-t3code:accepted ACCEPTED_POINTER_FILE="$tmp/accepted-image"
export RECEIPT_SELF_CHECK="$tmp/bin/receipt-self-check" ALARM_LOG="$tmp/alarms.log"
export HOME_DIR="$tmp/home" CANDIDATE_HOME_TARGET=/candidate-home PODMAN_BIN="$tmp/bin/podman"
export SYSTEMCTL_BIN="$tmp/bin/systemctl" PROVIDER_SECRETS_FILE="$tmp/provider.env"
export TOOLING_PATH="$tmp/tooling" AGENT_REVISION=agent-rev PYTHON_BIN=/bin/false
export JQ_BIN=jq RESTART_LEDGER="$tmp/ledger.jsonl" AUDIT_LOG="$tmp/audit.log"
# podman inspect reports the image id without the sha256: prefix, as on the host.
export EVENTS="$tmp/events" LIVE_IMAGE_FILE="$tmp/live-image" DEPLOYED_IMAGE="$image_id" IDENTITY_CALLS="$tmp/identity-calls"
export HEALTH_WAIT_BUDGET_SECONDS=390 HEALTH_WAIT_CLOCK_BIN="$tmp/bin/health-clock"
export HEALTH_WAIT_SLEEP_BIN="$tmp/bin/health-sleep" HEALTH_CLOCK_FILE="$tmp/health-clock"
export HEALTHY_AFTER_SECONDS=0
printf '0\n' > "$tmp/health-clock"
PATH="$tmp/bin:$PATH"
export PATH

run() {
  set +e
  bash "$writer" > "$tmp/out.log" 2>&1
  rc=$?
  set -e
}

fail() {
  echo "FAIL: $*" >&2
  cat "$tmp/out.log" >&2
  exit 1
}

reset_case() {
  : > "$tmp/events"
  rm -f "$tmp/identity-calls"
  rm -rf "$tmp/state/receipts"
  mkdir -p "$tmp/state/receipts"
  rm -f "$tmp/state/schema"
  rm -f "$tmp/state/failed-candidate"
  printf 'deployment-1\n' > "$tmp/state/desired"
  printf 'agent=agent-rev secret_sha256=%s tooling=%s\n' "$secret_sha" "$tmp/tooling" > "$tmp/state/desired-inputs"
  printf 'old\n' > "$tmp/state/applied"
  printf 'agent=old secret_sha256=old tooling=old\n' > "$tmp/state/applied-inputs"
  printf '%s\n' "$(printf 'other-image' | sha256sum | cut -d ' ' -f 1)" > "$tmp/accepted-image"
  printf 'sha256:%s\n' "$(printf 'running-image' | sha256sum | cut -d ' ' -f 1)" > "$tmp/live-image"
  printf '0\n' > "$tmp/health-clock"
  unset IDENTITY_MODE FIXTURE_LOADED_ID IMAGE_STREAM
}

# --- 1. a fresh deployment records a mechanical receipt ----------------------
reset_case
run
[[ $rc == 0 ]] || fail "the deploy exited $rc"
[[ $(grep -c '^podman-t3code.service$' "$tmp/events") == 1 ]] || fail 'T3 was not restarted exactly once'
receipt="$tmp/state/receipts/deployment-1.json"
[[ -f $receipt ]] || fail 'no receipt was written'
jq -e --arg id "sha256:$image_id" --arg image "$image_id" --arg s "$secret_sha" '
  .schema == 2 and .deployment_id == "deployment-1" and .image_id == $id
  and (.candidate_name | startswith("t3code-candidate-"))
  and .agent_revision == "agent-rev" and .agent_path == "'"$tmp/tooling"'"
  and .provider_secret_sha256 == $s and .verified == true
  and ((.live_after.image | sub("^sha256:"; "")) == $image) and .live_before != null
  and (.checks == null)
' "$receipt" >/dev/null || fail 'the receipt is not mechanical'
. "$root/packages/t3code/receipt-checks.sh"
JQ_BIN=jq receipt_checks_ok "$receipt" || fail 'the mechanical receipt was not accepted'
[[ $(cat "$tmp/state/applied") == deployment-1 ]] || fail 'the deployment was not recorded applied'
[[ "$(cat "$tmp/state/applied-inputs")" == "agent=agent-rev secret_sha256=$secret_sha tooling=$tmp/tooling" ]] \
  || fail 'the applied inputs were not recorded'
[[ "$(cat "$tmp/accepted-image")" == "$image_id" ]] || fail 'the accepted alias did not move'
echo 'Mechanical receipt proof: the image is promoted and restarted once, and the receipt records identity only.'

# --- 2. an incompatible state schema is refused before any effect ------------
reset_case
printf '1\n' > "$tmp/state/schema"
run
[[ $rc != 0 ]] || fail 'an incompatible state schema was accepted'
grep -q 'state schema is 1' "$tmp/out.log" || fail 'the schema refusal was not named'
[[ ! -s $tmp/events ]] || fail 'an incompatible schema had an effect'
echo 'Schema proof: an incompatible state schema is refused before any effect.'

# --- 3. missing tooling is refused before any effect -------------------------
reset_case
TOOLING_PATH="$tmp/missing-tooling" run
[[ $rc != 0 ]] || fail 'a deployment without tooling was accepted'
grep -q 'deployment tooling is missing' "$tmp/out.log" || fail 'the missing tooling was not named'
[[ ! -s $tmp/events ]] || fail 'a deployment without tooling had an effect'
echo 'Tooling proof: a missing tooling path is refused before any effect.'

# --- 4. a restart that changes identity is not recorded applied --------------
reset_case
IDENTITY_MODE=change run
[[ $rc != 0 ]] || fail 'a changed container identity was accepted'
grep -q 'restarted again during the readiness probe' "$tmp/out.log" || fail 'the identity change was not named'
[[ $(cat "$tmp/state/applied") == old ]] || fail 'a changed identity recorded the deployment applied'
[[ ! -f $tmp/state/receipts/deployment-1.json ]] || fail 'a changed identity wrote a receipt'
echo 'Readiness proof: a second restart is refused and never recorded applied.'

# --- 5. an already-applied deployment is not restarted -----------------------
reset_case
jq -cn --arg id "sha256:$image_id" --arg s "$secret_sha" --arg t "$tmp/tooling" '
  {schema:2,deployment_id:"deployment-1",image_id:$id,candidate_name:"t3code-candidate-fixture",
   agent_revision:"agent-rev",agent_path:$t,provider_secret_sha256:$s,
   live_before:{id:"a",image:$id},live_after:{id:"a",image:$id},verified:true}' \
  > "$tmp/state/receipts/deployment-1.json"
printf 'deployment-1\n' > "$tmp/state/applied"
printf 'agent=agent-rev secret_sha256=%s tooling=%s\n' "$secret_sha" "$tmp/tooling" > "$tmp/state/applied-inputs"
printf '%s\n' "$image_id" > "$tmp/accepted-image"
printf '%s\n' "sha256:$image_id" > "$tmp/live-image"
run
[[ $rc == 0 ]] || fail "the already-applied deploy exited $rc"
grep -q 'already applied' "$tmp/out.log" || fail 'the already-applied path did not say so'
[[ ! -s $tmp/events ]] || fail 'an already-applied deployment had an effect'
echo 'Already-applied proof: a receipted deployment is not restarted.'

# --- 6. bootstrap keeps the running image and does not restart --------------
reset_case
rm -f "$tmp/accepted-image"
run
[[ $rc == 0 ]] || fail "the bootstrap deploy exited $rc"
grep -q 'BOOTSTRAP: no PASS receipt matches running image' "$tmp/out.log" || fail 'the bootstrap path did not say so'
! grep -q '^podman-t3code.service$' "$tmp/events" || fail 'the bootstrap path restarted T3'
[[ -f $tmp/accepted-image ]] || fail 'the bootstrap path left the accepted alias absent'
echo 'Bootstrap proof: with no receipt for the running image, it is retained and nothing restarts.'

# --- 7. a streamed image whose load id differs is refused -------------------
reset_case
mkdir -p "$tmp/stream"
cp "$tmp/manifest.json" "$tmp/config.json" "$tmp/stream/"
cat > "$tmp/stream.sh" <<SH
#!/usr/bin/env bash
tar -cf - -C "$tmp/stream" manifest.json config.json
SH
chmod +x "$tmp/stream.sh"
IMAGE_STREAM="$tmp/stream.sh" IMAGE_ARCHIVE= FIXTURE_LOADED_ID="$(printf '%064d' 9)" run
[[ $rc == 77 ]] || fail "a mismatched streamed id exited $rc, want 77"
grep -q 'does not match the pre-load id' "$tmp/out.log" || fail 'the streamed mismatch was not named'
[[ "$(cat "$tmp/accepted-image")" == "$(printf 'other-image' | sha256sum | cut -d ' ' -f 1)" ]] \
  || fail 'a mismatched streamed image was aliased'
! grep -q '^podman-t3code.service$' "$tmp/events" || fail 'a mismatched streamed image restarted T3'
[[ ! -f $tmp/state/receipts/deployment-1.json ]] || fail 'a mismatched streamed image wrote a receipt'
echo 'Stream proof: a streamed image whose load id differs is refused before any effect.'

echo 'Deploy-image fixture passed.'
