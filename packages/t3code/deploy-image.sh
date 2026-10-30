set -euo pipefail

if [[ ${1:-} == --list-manifest ]]; then
  : "${2:?usage: deploy-image.sh --list-manifest IMAGE_ARCHIVE}"
  exec tar -xOf "$2" manifest.json
fi

if [[ ${1:-} == --invalidate-failure ]]; then
  [[ $# == 2 && -n ${2//[[:space:]]/} && ${#2} -le 500 && $2 != *$'\n'* && $2 != *$'\r'* ]] || {
    echo 'usage: ghostship-t3code-invalidate-failure REASON (one nonempty line)' >&2; exit 2;
  }
  : "${STATE_DIR:?}"
  : "${JQ_BIN:?}"
  umask 077
  install -d -m 0700 "$STATE_DIR"
  exec 9>"$STATE_DIR/deploy.lock"
  flock -x 9
  failed_file="$STATE_DIR/failed-candidate"
  [[ -f "$failed_file" && ! -L "$failed_file" ]] || { echo 'No failed candidate marker to invalidate' >&2; exit 1; }
  marker=$(cat "$failed_file")
  [[ -n "$marker" ]] || { echo 'Failed candidate marker is empty; inspect it manually' >&2; exit 1; }
  audit="$STATE_DIR/failure-invalidations.jsonl"
  [[ ! -L "$audit" ]] || { echo 'Invalidation audit must not be a symlink' >&2; exit 1; }
  touch "$audit"
  chmod 0600 "$audit"
  "$JQ_BIN" -cn --arg at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --arg failed_key "$marker" --arg reason "$2" \
    '{event:"invalidation_requested",at:$at,failed_key:$failed_key,reason:$reason}' >> "$audit"
  sync -f "$audit"
  rm "$failed_file"
  echo 'Failed candidate marker invalidated; acceptance must run again.'
  exit 0
fi

: "${STATE_DIR:?}"
: "${IMAGE_ARCHIVE:?}"
: "${DEPLOYMENT_ID:?}"
: "${HOME_DIR:?}"
: "${CANDIDATE_ACCEPTANCE:?}"
: "${PODMAN_BIN:?}"
: "${SYSTEMCTL_BIN:?}"
: "${CANDIDATE_SOCKET:?}"
: "${CANDIDATE_UID:?}"
: "${CANDIDATE_RUNTIME_DIR:?}"
: "${CANDIDATE_HOME_TARGET:?}"
: "${PROVIDER_SECRETS_FILE:?}"
: "${TOOLING_PATH:?}"
: "${AGENT_REVISION:?}"
: "${PYTHON_BIN:?}"
: "${JQ_BIN:?}"
: "${RESTART_LEDGER:?}"
: "${AUDIT_LOG:?}"
: "${ACCEPTED_IMAGE_REF:?}"
: "${RECEIPT_SELF_CHECK:?}"
: "${HEALTH_WAIT_BUDGET_SECONDS:?}"

health_wait_now() {
  if [[ -n ${HEALTH_WAIT_CLOCK_BIN:-} ]]; then
    "$HEALTH_WAIT_CLOCK_BIN"
  else
    printf '%s\n' "$SECONDS"
  fi
}

health_wait_sleep() {
  if [[ -n ${HEALTH_WAIT_SLEEP_BIN:-} ]]; then
    "$HEALTH_WAIT_SLEEP_BIN" "$1"
  else
    sleep "$1"
  fi
}

install -d -m 0700 "$STATE_DIR" "$STATE_DIR/receipts"
exec 9>"$STATE_DIR/deploy.lock"
flock -x 9

desired=$(cat "$STATE_DIR/desired" 2>/dev/null || true)
desired_inputs=$(cat "$STATE_DIR/desired-inputs" 2>/dev/null || true)
applied=$(cat "$STATE_DIR/applied" 2>/dev/null || true)
applied_inputs=$(cat "$STATE_DIR/applied-inputs" 2>/dev/null || true)
if [[ "$desired" != "$DEPLOYMENT_ID" ]]; then
  echo "T3 deployment request was superseded before it started" >&2
  exit 0
fi
attempts_dir="$STATE_DIR/attempts"
install -d -m 0700 "$attempts_dir"
attempt_file="$attempts_dir/$DEPLOYMENT_ID.json"
attempt_temporary="$attempt_file.tmp"
attempt_started_at_ms=$(date +%s%3N)
write_attempt_result() {
  local exit_code=$?
  trap - EXIT
  if "$JQ_BIN" -c --arg deployment "$DEPLOYMENT_ID" \
    --argjson started_at_ms "$attempt_started_at_ms" --argjson exit_code "$exit_code" \
    '. + {deployment_id:$deployment,started_at_ms:$started_at_ms,exit_code:$exit_code} | del(.status)' "$attempt_file" \
    > "$attempt_temporary"; then
    chmod 0600 "$attempt_temporary"
    mv -f "$attempt_temporary" "$attempt_file"
  fi
  return "$exit_code"
}
"$JQ_BIN" -cn --arg deployment "$DEPLOYMENT_ID" \
  --argjson started_at_ms "$attempt_started_at_ms" \
  '{deployment_id:$deployment,started_at_ms:$started_at_ms,status:"running"}' > "$attempt_temporary"
chmod 0600 "$attempt_temporary"
mv -f "$attempt_temporary" "$attempt_file"
trap write_attempt_result EXIT
image_config=$(tar -xOf "$IMAGE_ARCHIVE" manifest.json | "$JQ_BIN" -er '.[0].Config')
image_id=$(tar -xOf "$IMAGE_ARCHIVE" "$image_config" | sha256sum | cut -d ' ' -f 1)
secret_inode=$(stat -Lc '%i' "$PROVIDER_SECRETS_FILE")
receipt="$STATE_DIR/receipts/$DEPLOYMENT_ID.json"

receipt_matches_image() {
  "$JQ_BIN" -e \
    --arg deployment "$DEPLOYMENT_ID" \
    --arg image "$image_id" \
    --arg agent "$AGENT_REVISION" \
    --arg tooling "$TOOLING_PATH" \
    --arg secret_inode "$secret_inode" \
    '(.deployment_id == $deployment)
     and (.image_id | sub("^sha256:"; "")) == $image
     and (.candidate_name | startswith("t3code-candidate-"))
     and (.live_before != null) and (.live_before == .live_after)
     and (.agent_revision == $agent)
     and (.agent_path == $tooling)
     and (.provider_secret_inode == $secret_inode)
     and ([.checks.app_ready, .checks.provider_turn, .checks.agent_cli,
           .checks.skills, .checks.desktop_transport] | all(. == true))' \
    "$receipt" >/dev/null 2>&1
}

any_receipt_matches_image() {
  local candidate
  for candidate in "$STATE_DIR"/receipts/*.json; do
    [[ -f "$candidate" ]] || continue
    if "$JQ_BIN" -e --arg image "$1" \
      '((.image_id | sub("^sha256:"; "")) == $image)
       and (.deployment_id | type == "string" and length > 0)
       and (.candidate_name | type == "string" and startswith("t3code-candidate-"))
       and (.live_before != null and .live_before == .live_after)
       and ([.checks.app_ready, .checks.provider_turn, .checks.agent_cli,
             .checks.skills, .checks.desktop_transport] | all(. == true))' \
      "$candidate" >/dev/null 2>&1; then
      return 0
    fi
  done
  return 1
}

promote_image_id() {
  local source_id="$1" accepted_id
  "$PODMAN_BIN" tag "$source_id" "$ACCEPTED_IMAGE_REF"
  accepted_id=$("$PODMAN_BIN" image inspect "$ACCEPTED_IMAGE_REF" --format '{{.Id}}' 2>/dev/null || true)
  if [[ "${accepted_id#sha256:}" != "${source_id#sha256:}" ]]; then
    echo "Accepted image alias does not resolve to source image $source_id" >&2
    return 1
  fi
}

promote_accepted_alias() {
  "$PODMAN_BIN" load --input "$IMAGE_ARCHIVE"
  promote_image_id "sha256:$image_id"
}

if [[ "$applied" == "$DEPLOYMENT_ID" && "$applied_inputs" == "$desired_inputs" ]]; then
  if receipt_matches_image; then
    accepted_id=$("$PODMAN_BIN" image inspect "$ACCEPTED_IMAGE_REF" --format '{{.Id}}' 2>/dev/null || true)
    if [[ "${accepted_id#sha256:}" != "$image_id" ]]; then
      promote_accepted_alias
      echo "Initialized accepted image alias from the existing PASS receipt: $ACCEPTED_IMAGE_REF -> sha256:$image_id"
    else
      echo "T3 image, runtime inputs, and accepted image alias are already applied: $DEPLOYMENT_ID"
    fi
    exit 0
  fi
fi

# The first upgrade may have no receipt for any image and no accepted alias.
# Preserve the already-running image as the restart target; do not load a new
# archive or restart T3 in this bootstrap path.
accepted_id=$("$PODMAN_BIN" image inspect "$ACCEPTED_IMAGE_REF" --format '{{.Id}}' 2>/dev/null || true)
if [[ -z "$accepted_id" ]]; then
  running_identity=$("$PODMAN_BIN" inspect t3code --format '{{.State.Running}} {{.Image}}' 2>/dev/null || true)
  read -r running running_image_id <<< "$running_identity"
  if [[ "$running" != true || -z "$running_image_id" ]]; then
    echo "Cannot bootstrap the accepted T3 image alias: no T3 container is running and no accepted alias exists" >&2
    exit 1
  fi
  if any_receipt_matches_image "${running_image_id#sha256:}"; then
    promote_image_id "$running_image_id"
    echo "Initialized accepted image alias from the running image's PASS receipt: $ACCEPTED_IMAGE_REF -> $running_image_id"
  else
    "$RECEIPT_SELF_CHECK"
    promote_image_id "$running_image_id"
    echo "BOOTSTRAP: no PASS receipt matches running image $running_image_id; alarm logged, retained it as $ACCEPTED_IMAGE_REF, and skipped new image activation and restart"
    exit 0
  fi
fi

failed_file="$STATE_DIR/failed-candidate"
# Hash only the executable acceptance bundle and the candidate/tooling identity.
# The bundle is copied as four named files by t3codeDeploymentScripts; adding a
# dependency requires updating that bundle and this manifest together. Paths
# within the bundle do not affect identity, and unrelated files are excluded.
acceptance_dir=$(dirname "$CANDIDATE_ACCEPTANCE")
acceptance_id=$(
  {
    printf 'candidate-acceptance-v2\nimage=%s\nagent=%s\ntooling=%s\npython=%s\n' "$image_id" "$AGENT_REVISION" "$TOOLING_PATH" "$PYTHON_BIN"
    for file in "$CANDIDATE_ACCEPTANCE" "$acceptance_dir/hardening-probe.py" "$acceptance_dir/provider-turn-probe.py" "$acceptance_dir/runtime-caps.json"; do
      [[ -f "$file" && -r "$file" ]] || { echo 'Acceptance input missing or unreadable' >&2; exit 1; }
      sha256sum < "$file" || exit 1
    done
  } | sha256sum | cut -d ' ' -f 1
)
failed_key="$DEPLOYMENT_ID $acceptance_id"
if [[ -r "$failed_file" && "$(cat "$failed_file")" == "$failed_key" ]]; then
  echo "Candidate acceptance already failed for $DEPLOYMENT_ID; image remains blocked" >&2
  exit 0
fi

# A precondition miss (exit 75) is retried by systemd (RestartForceExitStatus=75)
# after RestartSec; this counter bounds the retries for one image and acceptance
# code. The last attempt exits 1, which stops the retries and leaves the image
# retryable by a later run.
precondition_file="$STATE_DIR/precondition-attempts"
precondition_attempts=${PRECONDITION_ATTEMPTS:-6}

mark_candidate_failed() {
  local temporary="$failed_file.tmp"
  printf '%s\n' "$failed_key" > "$temporary"
  chmod 0600 "$temporary"
  mv -f "$temporary" "$failed_file"
}

candidate_args=(
  --state-dir "$STATE_DIR"
  --image-archive "$IMAGE_ARCHIVE"
  --podman-bin "$PODMAN_BIN"
  --candidate-socket "$CANDIDATE_SOCKET"
  --home-dir "$HOME_DIR"
  --candidate-runtime-dir "$CANDIDATE_RUNTIME_DIR"
  --candidate-uid "$CANDIDATE_UID"
  --provider-secrets-file "$PROVIDER_SECRETS_FILE"
  --tooling-path "$TOOLING_PATH"
  --agent-revision "$AGENT_REVISION"
  --candidate-home-target "$CANDIDATE_HOME_TARGET"
  --systemctl-bin "$SYSTEMCTL_BIN"
)
candidate_args+=(--volume /etc/ghostship/route-policy.json:/etc/ghostship/route-policy.json:ro)
candidate_args+=(--volume /etc/ghostship/approved-free-workers.json:/etc/ghostship/approved-free-workers.json:ro)
candidate_args+=(--volume /nix/store:/nix/store:O)

acceptance_status=0
"$PYTHON_BIN" "$CANDIDATE_ACCEPTANCE" "${candidate_args[@]}" || acceptance_status=$?
# 75: a host precondition failed before the candidate ran; the image is not at
# fault and the next run re-runs full acceptance.
if [[ $acceptance_status == 75 ]]; then
  attempt=1
  previous_deployment="" previous_acceptance="" previous_attempt=""
  if [[ -r "$precondition_file" ]]; then
    read -r previous_deployment previous_acceptance previous_attempt < "$precondition_file" || true
  fi
  if [[ "${previous_deployment:-} ${previous_acceptance:-}" == "$failed_key" && ${previous_attempt:-} =~ ^[0-9]+$ ]]; then
    attempt=$((previous_attempt + 1))
  fi
  if (( attempt >= precondition_attempts )); then
    rm -f "$precondition_file"
    echo "Candidate acceptance precondition not met for $DEPLOYMENT_ID after $attempt attempts; image stays retryable" >&2
    exit 1
  fi
  printf '%s %s\n' "$failed_key" "$attempt" > "$precondition_file.tmp"
  mv -f "$precondition_file.tmp" "$precondition_file"
  echo "Candidate acceptance precondition not met for $DEPLOYMENT_ID (attempt $attempt of $precondition_attempts); image stays retryable and is retried" >&2
  exit 75
fi
rm -f "$precondition_file"
if [[ $acceptance_status != 0 ]]; then
  mark_candidate_failed
  echo "Candidate acceptance FAILED for $DEPLOYMENT_ID; image will not be queued" >&2
  exit 1
fi

if ! receipt_matches_image; then
  mark_candidate_failed
  echo "Candidate acceptance receipt did not approve this exact image: $DEPLOYMENT_ID" >&2
  exit 1
fi

rm -f "$failed_file"
echo "Candidate acceptance PASS deployment=$DEPLOYMENT_ID image=$image_id receipt=$receipt"

tool_lock="$HOME_DIR/.local/state/t3code-tool-update/tool-update.lock"
if [[ -d "$(dirname "$tool_lock")" ]]; then
  exec 8>"$tool_lock"
  flock -x 8
fi

container_identity() {
  local fields
  fields=$("$PODMAN_BIN" inspect t3code --format '{{.Id}} {{.Image}} {{.State.StartedAt}} {{.State.Health.Status}}' 2>/dev/null || true)
  if [[ -z "$fields" ]]; then
    printf '{}\n'
    return
  fi
  read -r container_id image started health <<< "$fields"
  "$JQ_BIN" -cn --arg id "$container_id" --arg image "$image" --arg started_at "$started" \
    --arg health "$health" \
    '{id:$id,image:$image,started_at:$started_at,health:$health}'
}

# record_applied AGENT_PATH SECRET_INODE marks this deployment and its inputs
# applied, with what the running container verifiably uses.
record_applied() {
  printf '%s\n' "$DEPLOYMENT_ID" > "$STATE_DIR/applied.tmp"
  mv -f "$STATE_DIR/applied.tmp" "$STATE_DIR/applied"
  printf '%s\n' "$desired_inputs" > "$STATE_DIR/applied-inputs.tmp"
  mv -f "$STATE_DIR/applied-inputs.tmp" "$STATE_DIR/applied-inputs"
  "$JQ_BIN" -cn --arg deployment_id "$DEPLOYMENT_ID" --arg agent_revision "$AGENT_REVISION" \
    --arg agent_path "$1" --arg provider_secret_inode "$2" \
    --arg verified_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    '{deployment_id:$deployment_id,agent_revision:$agent_revision,agent_path:$agent_path,
      provider_secret_inode:$provider_secret_inode,verified:true,verified_at:$verified_at}' \
    > "$STATE_DIR/deployed-inputs.json.tmp"
  chmod 0600 "$STATE_DIR/deployed-inputs.json.tmp"
  mv -f "$STATE_DIR/deployed-inputs.json.tmp" "$STATE_DIR/deployed-inputs.json"
}

pre=$(container_identity)
# Activation writes desired under the same lock, so a completed acceptance
# cannot restart a unit for a newer image using this image's receipt.
current_desired=$(cat "$STATE_DIR/desired" 2>/dev/null || true)
current_inputs=$(cat "$STATE_DIR/desired-inputs" 2>/dev/null || true)
if [[ "$current_desired" != "$DEPLOYMENT_ID" || "$current_inputs" != "$desired_inputs" ]]; then
  echo "T3 deployment request was superseded before restart; refusing stale image" >&2
  exit 0
fi

# A re-run of acceptance may find T3 already running exactly what it accepted:
# every activation re-decrypts the provider secret to a new inode, which
# changes the desired inputs without changing anything T3 uses. Restart only
# when the image, the agent or the secret content differs; a restart onto the
# same inputs would only end every session. The digests stay in memory.
pre_image=$(printf '%s' "$pre" | "$JQ_BIN" -r '.image // empty')
if [[ -n "$pre_image" && "${pre_image#sha256:}" == "$image_id" ]]; then
  running_agent=$("$PODMAN_BIN" exec t3code readlink -f "$CANDIDATE_HOME_TARGET/.local/state/ghostship-t3-tools/current" 2>/dev/null || true)
  running_secret=$("$PODMAN_BIN" exec t3code sha256sum /run/secrets/t3code.env 2>/dev/null | cut -d ' ' -f 1 || true)
  desired_secret=$(sha256sum "$PROVIDER_SECRETS_FILE" | cut -d ' ' -f 1)
  if [[ "$running_agent" == "$TOOLING_PATH" && -n "$running_secret" && "$running_secret" == "$desired_secret" ]]; then
    accepted_id=$("$PODMAN_BIN" image inspect "$ACCEPTED_IMAGE_REF" --format '{{.Id}}' 2>/dev/null || true)
    if [[ "${accepted_id#sha256:}" != "$image_id" ]]; then
      promote_accepted_alias
    fi
    running_secret_inode=$("$PODMAN_BIN" exec t3code stat -Lc '%i' /run/secrets/t3code.env)
    record_applied "$running_agent" "$running_secret_inode"
    echo "T3 already runs accepted image sha256:$image_id with the accepted agent and provider secret; PASS recorded, no restart"
    exit 0
  fi
fi

# Only this receipt-checked path may move the unit's stable image alias. The
# systemd unit has no imageFile, so an ordinary restart cannot import or retag
# the current Nix image archive.
promote_accepted_alias
echo "Accepted image pointer moved after exact-image candidate acceptance: $ACCEPTED_IMAGE_REF -> sha256:$image_id"
echo "Restarting podman-t3code.service immediately after exact-image candidate acceptance"
"$SYSTEMCTL_BIN" restart podman-t3code.service

deadline=$(($(health_wait_now) + HEALTH_WAIT_BUDGET_SECONDS))
healthy=false
while (( $(health_wait_now) < deadline )); do
  status=$("$PODMAN_BIN" inspect t3code --format '{{.State.Health.Status}}' 2>/dev/null || true)
  if [[ "$status" == healthy ]] \
    && "$PODMAN_BIN" exec t3code systemctl is-active --quiet t3code-server.service \
    && "$PODMAN_BIN" exec t3code curl -fsS --max-time 5 http://127.0.0.1:3773/ >/dev/null 2>&1; then
    healthy=true
    break
  fi
  health_wait_sleep 5
done
if [[ "$healthy" != true ]]; then
  echo "T3 Code did not become healthy after the accepted image restart" >&2
  exit 1
fi

live_agent=$("$PODMAN_BIN" exec t3code readlink -f "$CANDIDATE_HOME_TARGET/.local/state/ghostship-t3-tools/current")
live_secret_inode=$("$PODMAN_BIN" exec t3code stat -Lc '%i' /run/secrets/t3code.env)
if [[ "$live_agent" != "$TOOLING_PATH" || "$live_secret_inode" != "$secret_inode" ]]; then
  echo "T3 restart did not load the accepted agent and provider inputs" >&2
  exit 1
fi

post=$(container_identity)
post_image=$(printf '%s' "$post" | "$JQ_BIN" -r '.image // empty')
if [[ "${post_image#sha256:}" != "$image_id" ]]; then
  echo "T3 container did not start the receipted image sha256:$image_id" >&2
  exit 1
fi
now=$(date -u +%Y-%m-%dT%H:%M:%SZ)
entry=$("$JQ_BIN" -cn \
  --arg time "$now" --arg user "${USER:-root}" --argjson uid "$EUID" \
  --arg host "$(hostname)" --arg ssh_client "${SSH_CLIENT:-}" \
  --argjson pid "$$" --argjson pre "$pre" --argjson post "$post" \
  '{time:$time,mode:"candidate-accepted",actor:{user:$user,uid:$uid,host:$host,ssh_client:$ssh_client,pid:$pid},pre:$pre,post:$post}')
install -d -m 0700 "$(dirname "$RESTART_LEDGER")"
printf '%s\n' "$entry" >> "$RESTART_LEDGER"
chmod 0600 "$RESTART_LEDGER"

record_applied "$live_agent" "$live_secret_inode"
install -d -m 0700 "$(dirname "$AUDIT_LOG")"
printf '%s\n' "action=candidate-accepted-restart deployment=$DEPLOYMENT_ID" >> "$AUDIT_LOG"
chmod 0600 "$AUDIT_LOG"
printf '%s\n' "candidate-accepted T3 Code restart: before $(printf '%s' "$pre" | "$JQ_BIN" -r '.id // "unknown"'), after $(printf '%s' "$post" | "$JQ_BIN" -r '.id // "unknown"')" \
  | systemd-cat -t t3code-restart -p warning
echo "Restart issued for accepted T3 image $DEPLOYMENT_ID"
