set -euo pipefail
if ! declare -F receipt_checks_ok >/dev/null 2>&1; then
  # shellcheck disable=SC1091
  . "$(dirname "${BASH_SOURCE[0]}")/receipt-checks.sh"
fi

publish_attestation() {
  local payload="$1" directory="$STATE_DIR/attestations" temporary
  [[ ! -L "$directory" ]] || { echo 'Attestation directory is a symlink' >&2; return 1; }
  install -d -m 0755 "$directory"
  [[ $(stat -c '%u' "$directory") == "$EUID" ]] || { echo 'Attestation directory has unexpected owner' >&2; return 1; }
  chmod 0755 "$directory"
  temporary=$(mktemp "$directory/.current.XXXXXXXX")
  printf '%s\n' "$payload" > "$temporary"
  chmod 0444 "$temporary"
  sync -f "$temporary"
  mv -f "$temporary" "$directory/current.json"
  sync -f "$directory"
}

publish_unknown_attestation() {
  local failed=false
  if [[ -e "$STATE_DIR/failed-candidate" || -L "$STATE_DIR/failed-candidate" ]]; then failed=true; fi
  publish_attestation "$("$JQ_BIN" -cn --argjson failed "$failed" \
    '{schema:1,state:"unknown",failed_candidate:$failed}')"
}

if [[ ${1:-} == --list-manifest ]]; then
  : "${2:?usage: deploy-image.sh --list-manifest IMAGE_ARCHIVE}"
  exec tar -xOf "$2" manifest.json
fi

# Every non-zero exit must say so; a silent exit 1 hid the failed step. The
# attempt writer below replaces this trap, so it calls the same function.
log_exit_rc() {
  local rc=${1:-0}
  if [ "$rc" -ne 0 ]; then
    echo "deploy: exiting rc=$rc (see the last deploy step above)" >&2
  fi
}
trap 'rc=$?; log_exit_rc "$rc"' EXIT
[[ ! -e ${STATE_DIR:?}/recovery-unknown.json && ! -L $STATE_DIR/recovery-unknown.json ]] || { echo 'release recovery UNKNOWN: writer stopped for investigation' >&2; exit 77; }

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
  publish_unknown_attestation
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
  publish_unknown_attestation
  echo 'Failed candidate marker invalidated; the next deploy runs the mechanical checks again.'
  exit 0
fi

: "${STATE_DIR:?}"
# Either an archive or a streamed image is required; a stream is preferred.
if [[ -z ${IMAGE_STREAM:-} ]]; then : "${IMAGE_ARCHIVE:?}"; fi
# A stream is one-shot: materialise it once, then use the archive path
# everywhere (id derivation, load, acceptance) so no step reads it twice or
# receives an empty archive. IMAGE_STREAMED keeps the post-load id check.
if [[ -n ${IMAGE_STREAM:-} ]]; then
  IMAGE_ARCHIVE="$STATE_DIR/image-stream.tar"
  "$IMAGE_STREAM" > "$IMAGE_ARCHIVE" || fail 'image stream unreadable'
  IMAGE_STREAMED=1
  unset IMAGE_STREAM
fi
# The receipt this attempt writes must not destroy a pre-existing one: a receipt
# for an already-applied or serving deployment is evidence, not scratch space.
receipt_path="$STATE_DIR/receipts/$DEPLOYMENT_ID.json"
receipt_before=absent
receipt_backup="$STATE_DIR/.receipt-before-$DEPLOYMENT_ID.json"
if [[ -f $receipt_path && ! -L $receipt_path ]]; then
  receipt_before=present
  cp "$receipt_path" "$receipt_backup" || fail 'existing receipt could not be preserved'
fi
cleanup_attempt_evidence() {
  [[ ${IMAGE_STREAMED:-0} == 1 ]] && rm -f "$IMAGE_ARCHIVE"
  rm -f "$receipt_backup"
}
trap cleanup_attempt_evidence EXIT
: "${DEPLOYMENT_ID:?}"
: "${HOME_DIR:?}"
: "${PODMAN_BIN:?}"
: "${SYSTEMCTL_BIN:?}"
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
ROUTE_POLICY_FILE=${ROUTE_POLICY_FILE:-/etc/ghostship/route-policy.json}
APPROVED_FREE_FILE=${APPROVED_FREE_FILE:-/etc/ghostship/approved-free-workers.json}

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
publish_unknown_attestation

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
  log_exit_rc "$exit_code"
  return "$exit_code"
}
"$JQ_BIN" -cn --arg deployment "$DEPLOYMENT_ID" \
  --argjson started_at_ms "$attempt_started_at_ms" \
  '{deployment_id:$deployment,started_at_ms:$started_at_ms,status:"running"}' > "$attempt_temporary"
chmod 0600 "$attempt_temporary"
mv -f "$attempt_temporary" "$attempt_file"
trap 'write_attempt_result; cleanup_attempt_evidence' EXIT
# The image id is the sha256 of the image's config blob, known before the load
# from the archive. A streamed input was materialised to an archive before this
# point, so there is exactly one derivation.
image_config=$(tar -xOf "$IMAGE_ARCHIVE" manifest.json | "$JQ_BIN" -er '.[0].Config')
image_id=$(tar -xOf "$IMAGE_ARCHIVE" "$image_config" | sha256sum | cut -d ' ' -f 1)
secret_sha256=$(sha256sum "$PROVIDER_SECRETS_FILE" | cut -d ' ' -f 1)
receipt="$STATE_DIR/receipts/$DEPLOYMENT_ID.json"

# A receipt written before the digest identity carries only the inode. Its
# content is unknown from the file, so accept it only when the live container
# secret digest proves the same input; never rewrite an old receipt.
secret_identity_ok() {
  local file=$1 recorded live
  recorded=$("$JQ_BIN" -r '.provider_secret_sha256 // empty' "$file" 2>/dev/null || true)
  if [[ -n "$recorded" ]]; then
    [[ "$recorded" == "$secret_sha256" ]]
    return
  fi
  live=$("$PODMAN_BIN" exec t3code sha256sum /run/secrets/t3code.env 2>/dev/null | cut -d ' ' -f 1 || true)
  [[ -n "$live" && "$live" == "$secret_sha256" ]]
}

# The desired and applied input lines use the secret content digest. An applied
# line written before the change still names the inode; compare its other
# inputs exactly and the secret by content so the first no-op deploy does not
# restart T3.
inputs_equal() {
  local desired=$1 applied=$2 token d_agent="" d_secret="" d_inode="" d_tool="" a_agent="" a_secret="" a_inode="" a_tool="" live=""
  for token in $desired; do
    case "$token" in
      agent=*) d_agent=${token#agent=};;
      secret_sha256=*) d_secret=${token#secret_sha256=};;
      secret_inode=*) d_inode=${token#secret_inode=};;
      tooling=*) d_tool=${token#tooling=};;
    esac
  done
  for token in $applied; do
    case "$token" in
      agent=*) a_agent=${token#agent=};;
      secret_sha256=*) a_secret=${token#secret_sha256=};;
      secret_inode=*) a_inode=${token#secret_inode=};;
      tooling=*) a_tool=${token#tooling=};;
    esac
  done
  [[ "$d_agent" == "$a_agent" && "$d_tool" == "$a_tool" ]] || return 1
  if [[ -z "$d_secret" && -z "$a_secret" ]]; then
    # Both lines predate the digest. The old exact-string rule still decides.
    [[ "$desired" == "$applied" ]]
    return
  fi
  if [[ -n "$d_secret" && -n "$a_secret" ]]; then
    [[ "$d_secret" == "$a_secret" ]]
    return
  fi
  [[ -n "$d_inode" || -n "$a_inode" ]] || return 1
  live=$("$PODMAN_BIN" exec t3code sha256sum /run/secrets/t3code.env 2>/dev/null | cut -d ' ' -f 1 || true)
  [[ -n "$live" && "$live" == "${d_secret:-$a_secret}" ]]
}

receipt_matches_image() {
  "$JQ_BIN" -e \
    --arg deployment "$DEPLOYMENT_ID" \
    --arg image "$image_id" \
    --arg agent "$AGENT_REVISION" \
    --arg tooling "$TOOLING_PATH" \
    '(.deployment_id == $deployment)
     and (.image_id | sub("^sha256:"; "")) == $image
     and (.candidate_name | startswith("t3code-candidate-"))
     and (.live_after != null) and (.live_after.image == "sha256:" + $image)
     and (.agent_revision == $agent)
     and (.agent_path == $tooling)' \
    "$receipt" >/dev/null 2>&1 \
    && receipt_checks_ok "$receipt" \
    && secret_identity_ok "$receipt"
}

any_receipt_matches_image() {
  local candidate
  for candidate in "$STATE_DIR"/receipts/*.json; do
    [[ -f "$candidate" ]] || continue
    if "$JQ_BIN" -e --arg image "$1" \
      '((.image_id | sub("^sha256:"; "")) == $image)
       and (.deployment_id | type == "string" and length > 0)
       and (.candidate_name | type == "string" and startswith("t3code-candidate-"))
       and (.live_before != null and .live_before == .live_after)' \
      "$candidate" >/dev/null 2>&1 \
      && receipt_checks_ok "$candidate"; then
      return 0
    fi
  done
  return 1
}

acquire_managed_locks() {
  local tool_lock="$HOME_DIR/.local/state/t3code-tool-update/tool-update.lock"
  local refresh_lock="$HOME_DIR/.local/state/t3code-shared-agents/refresh.lock"
  local t3_tree="$HOME_DIR/.local/share/t3code-tools/t3"
  local t3_update_lock="$t3_tree/update.lock"
  local t3_owner
  [[ -f "$tool_lock" && ! -L "$tool_lock" && -f "$refresh_lock" && ! -L "$refresh_lock" ]] || {
    echo 'Managed tool or refresh lock missing; candidate is not inspected' >&2; return 1;
  }
  # A host that has never promoted an in-container T3 app has no app tree, so
  # there is no competing updater to serialize against and nothing for a receipt
  # to be bound to. The tree is never created here; a tree that exists with a
  # non-regular lock is refused, because flock on a symlink or directory can
  # lock something other than what the updater locks.
  if [[ -e "$t3_tree" || -L "$t3_tree" ]]; then
    [[ -d "$t3_tree" && ! -L "$t3_tree" ]] || {
      echo 'T3 app tree is not a directory; candidate is not inspected' >&2; return 1;
    }
    [[ ! -e "$t3_update_lock" || ( -f "$t3_update_lock" && ! -L "$t3_update_lock" ) ]] || {
      echo 'T3 update lock is not a regular file; candidate is not inspected' >&2; return 1;
    }
  fi
  exec 8<>"$tool_lock"
  flock -x 8
  exec 7<>"$refresh_lock"
  flock -x 7
  if [[ -d "$t3_tree" ]]; then
    # The updater opens this file with O_CREAT, so creating it here is the same
    # file the updater will lock. Create it owned by the home owner: the updater
    # runs as that user and opens the lock for append, so a root-owned lock
    # would fail every app update with EACCES.
    if [[ ! -e "$t3_update_lock" ]]; then
      t3_owner=$(stat -c '%u:%g' "$HOME_DIR") || {
        echo 'T3 app owner unknown; candidate is not inspected' >&2; return 1;
      }
      [[ $t3_owner =~ ^[1-9][0-9]*:[0-9]+$ ]] || {
        echo 'T3 app owner invalid; candidate is not inspected' >&2; return 1;
      }
      install -m 0600 -o "${t3_owner%%:*}" -g "${t3_owner##*:}" /dev/null "$t3_update_lock" || {
        echo 'T3 update lock bootstrap failed; candidate is not inspected' >&2; return 1;
      }
    fi
    exec 6>>"$t3_update_lock"
    flock -x 6
  fi
}

publish_pass_attestation() {
  local fields container_id live_image started health receipt_hash
  [[ ! -e "$STATE_DIR/failed-candidate" && ! -L "$STATE_DIR/failed-candidate" ]] || return 1
  receipt_matches_image || return 1
  fields=$("$PODMAN_BIN" inspect t3code --format '{{.Id}} {{.Image}} {{.State.StartedAt}} {{.State.Health.Status}}') || return 1
  read -r container_id live_image rest <<< "$fields"
  health=${rest##* }
  [[ $container_id =~ ^[0-9a-f]{64}$ && ${live_image#sha256:} == "$image_id" && $health == healthy ]] || return 1
  receipt_hash=$(sha256sum < "$receipt" | cut -d ' ' -f 1)
  publish_attestation "$("$JQ_BIN" -cn --arg image "$image_id" --arg container "$container_id" \
    --arg receipt "$DEPLOYMENT_ID" --arg receipt_hash "$receipt_hash" \
    '{schema:1,state:"pass",image_id:$image,container_id:$container,receipt_id:$receipt,
      receipt_sha256:$receipt_hash,failed_candidate:false}')"
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

load_image() {
  "$PODMAN_BIN" load --input "$IMAGE_ARCHIVE"
  # For a streamed input the pre-load id came from the stream itself, so the id
  # podman computed must agree. A mismatch is UNKNOWN: no alias promotion and no
  # receipt, rather than silently trusting either value.
  [[ ${IMAGE_STREAMED:-0} == 1 ]] || return 0
  local loaded
  loaded=$("$PODMAN_BIN" image inspect "sha256:$image_id" --format '{{.Id}}' 2>/dev/null || true)
  [[ $loaded == "sha256:$image_id" ]] || {
    echo "Loaded image id does not match the pre-load id: expected sha256:$image_id, got ${loaded:-absent}" >&2
    # The receipt describes the archive, but the image that loaded is not that
    # archive. Retire only what this attempt wrote: restore a pre-existing
    # receipt, or remove the one this attempt created.
    if [[ $receipt_before == present ]]; then
      cp "$receipt_backup" "$receipt_path.restore" && mv -f "$receipt_path.restore" "$receipt_path"
    else
      rm -f "$receipt_path"
    fi
    "$JQ_BIN" -c '. + {outcome:"acceptance_unknown",reason:"loaded image id differs from the streamed config digest"}' "$attempt_file" > "$attempt_temporary"
    chmod 0600 "$attempt_temporary"; mv -f "$attempt_temporary" "$attempt_file"
    exit 77
  }
}

promote_accepted_alias() {
  load_image
  promote_image_id "sha256:$image_id"
}

if [[ "$applied" == "$DEPLOYMENT_ID" ]] && inputs_equal "$desired_inputs" "$applied_inputs"; then
  if receipt_matches_image; then
    acquire_managed_locks
    accepted_id=$("$PODMAN_BIN" image inspect "$ACCEPTED_IMAGE_REF" --format '{{.Id}}' 2>/dev/null || true)
    if [[ "${accepted_id#sha256:}" != "$image_id" ]]; then
      promote_accepted_alias
      echo "Initialized accepted image alias from the existing PASS receipt: $ACCEPTED_IMAGE_REF -> sha256:$image_id"
    else
      echo "T3 image, runtime inputs, and accepted image alias are already applied: $DEPLOYMENT_ID"
    fi
    # A legacy applied line named the inode; record the digest form now so the
    # identity does not stay ambiguous.
    if [[ "$applied_inputs" != "$desired_inputs" ]]; then
      printf '%s\n' "$desired_inputs" > "$STATE_DIR/applied-inputs.tmp"
      mv -f "$STATE_DIR/applied-inputs.tmp" "$STATE_DIR/applied-inputs"
    fi
    publish_pass_attestation
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
# Lock order matches managed maintenance: tool, refresh, then the T3 app
# updater, whose lock is bootstrapped for its owner when the tree exists.
acquire_managed_locks

# --- activation compatibility checks -----------------------------------------
# Only mechanical checks run in activation. Behavioural suites (the candidate
# container, provider turn, skills, desktop) are not part of a deploy: they are
# fast-and-relevant (TEST) or an explicit proportional suite (just acceptance).
#
# 1. The image id is the artifact identity. load_image derived it from the
#    archive (and verified it against the stream when one was supplied) before
#    the load, which prevents running an unbuilt or substituted image.
# 2. The provider secret digest is present. Without it the container starts
#    with no provider inputs and cannot reach a provider.
[[ $secret_sha256 =~ ^[0-9a-f]{64}$ ]] \
  || { echo 'the provider secret digest is missing or malformed; refusing to activate' >&2; exit 1; }
# 3. The deployment tooling is present. A missing tooling path would start a
#    container whose agents and skills are absent.
[[ -d $TOOLING_PATH ]] \
  || { echo "the deployment tooling is missing: $TOOLING_PATH; refusing to activate" >&2; exit 1; }
# 4. The state schema is compatible. An older deployer must not write into a
#    newer state layout.
STATE_SCHEMA=2
state_schema() {
  local file="$STATE_DIR/schema" value
  if [[ -e $file || -L $file ]]; then
    [[ -f $file && ! -L $file ]] || { echo 'the deployment state schema marker is not a regular file; refusing to activate' >&2; return 1; }
    value=$(cat "$file")
    [[ $value == "$STATE_SCHEMA" ]] \
      || { echo "the deployment state schema is $value, this deployer writes $STATE_SCHEMA; refusing to activate" >&2; return 1; }
  else
    printf '%s\n' "$STATE_SCHEMA" > "$STATE_DIR/schema.tmp"
    mv -f "$STATE_DIR/schema.tmp" "$STATE_DIR/schema"
  fi
}
state_schema

container_identity() {
  local fields
  fields=$("$PODMAN_BIN" inspect t3code --format '{{.Id}} {{.Image}} {{.State.StartedAt}} {{.State.Health.Status}}' 2>/dev/null || true)
  if [[ -z "$fields" ]]; then
    printf '{}\n'
    return
  fi
  # .State.StartedAt contains spaces; the health status is the final field, so
  # split it from the end and keep the whole timestamp.
  read -r container_id image rest <<< "$fields"
  started=${rest% *}; health=${rest##* }
  "$JQ_BIN" -cn --arg id "$container_id" --arg image "$image" --arg started_at "$started" \
    --arg health "$health" \
    '{id:$id,image:$image,started_at:$started_at,health:$health}'
}

# record_applied AGENT_PATH SECRET_SHA256 marks this deployment and its inputs
# applied, with what the running container verifiably uses.
record_applied() {
  printf '%s\n' "$DEPLOYMENT_ID" > "$STATE_DIR/applied.tmp"
  mv -f "$STATE_DIR/applied.tmp" "$STATE_DIR/applied"
  printf '%s\n' "$desired_inputs" > "$STATE_DIR/applied-inputs.tmp"
  mv -f "$STATE_DIR/applied-inputs.tmp" "$STATE_DIR/applied-inputs"
  "$JQ_BIN" -cn --arg deployment_id "$DEPLOYMENT_ID" --arg agent_revision "$AGENT_REVISION" \
    --arg agent_path "$1" --arg provider_secret_sha256 "$2" \
    --arg verified_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    '{deployment_id:$deployment_id,agent_revision:$agent_revision,agent_path:$agent_path,
      provider_secret_sha256:$provider_secret_sha256,verified:true,verified_at:$verified_at}' \
    > "$STATE_DIR/deployed-inputs.json.tmp"
  chmod 0600 "$STATE_DIR/deployed-inputs.json.tmp"
  mv -f "$STATE_DIR/deployed-inputs.json.tmp" "$STATE_DIR/deployed-inputs.json"
}

pre=$(container_identity)
# Activation writes desired under the same lock, so a completed acceptance
# cannot restart a unit for a newer image using this image's receipt.
current_desired=$(cat "$STATE_DIR/desired" 2>/dev/null || true)
current_inputs=$(cat "$STATE_DIR/desired-inputs" 2>/dev/null || true)
if [[ "$current_desired" != "$DEPLOYMENT_ID" ]] || ! inputs_equal "$desired_inputs" "$current_inputs"; then
  echo "T3 deployment request was superseded before restart; refusing stale image" >&2
  exit 0
fi

# A re-run of acceptance may find T3 already running exactly what it accepted:
# every activation re-decrypts the provider secret to a new inode; the content
# digest in desired inputs stays the same. Restart only
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
    record_applied "$running_agent" "$running_secret"
    publish_pass_attestation
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

# Readiness, observed instead of waited out. The health budget bounds the
# observation; it is a ceiling, not a fixed dwell, so a host that is ready on
# the first probe is accepted immediately.
t3_ready() {
  local status
  status=$("$PODMAN_BIN" inspect t3code --format '{{.State.Health.Status}}' 2>/dev/null || true)
  [[ "$status" == healthy ]] \
    && "$PODMAN_BIN" exec t3code systemctl is-active --quiet t3code-server.service \
    && "$PODMAN_BIN" exec t3code curl -fsS --max-time 5 http://127.0.0.1:3773/ >/dev/null 2>&1
}

deadline=$(($(health_wait_now) + HEALTH_WAIT_BUDGET_SECONDS))
healthy=false
while (( $(health_wait_now) < deadline )); do
  if t3_ready; then
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
live_secret=$("$PODMAN_BIN" exec t3code sha256sum /run/secrets/t3code.env | cut -d ' ' -f 1)
if [[ "$live_agent" != "$TOOLING_PATH" || "$live_secret" != "$secret_sha256" ]]; then
  echo "T3 restart did not load the accepted agent and provider inputs" >&2
  exit 1
fi

# Baseline once the health loop reports healthy: systemd-driven restarts create
# a new container, so podman's RestartCount stays 0 and misses the 329 shape.
# Id + StartedAt is the identity the ledger already uses.
healthy_identity=$(container_identity)
healthy_id=$(printf '%s' "$healthy_identity" | "$JQ_BIN" -r '.id // empty')
healthy_started=$(printf '%s' "$healthy_identity" | "$JQ_BIN" -r '.started_at // empty')
if [[ -z "$healthy_id" || -z "$healthy_started" ]]; then
  echo 'container identity unreadable at settle start' >&2
  exit 1
fi

# Read the identity immediately: a second restart is visible now, without a
# fixed settle window. A different Id or StartedAt means T3 restarted again;
# exit 1 (never 75, which systemd would retry and restart T3 again) and do not
# record applied. The bounded probe below only confirms that the identity and
# readiness hold together; it never waits out a constant.
post=""
probe_deadline=$(($(health_wait_now) + HEALTH_WAIT_BUDGET_SECONDS))
while (( $(health_wait_now) < probe_deadline )); do
  post=$(container_identity)
  post_id=$(printf '%s' "$post" | "$JQ_BIN" -r '.id // empty')
  post_started=$(printf '%s' "$post" | "$JQ_BIN" -r '.started_at // empty')
  if [[ -z "$post_id" || -z "$post_started" ]]; then
    echo 'container identity unreadable at settle' >&2
    exit 1
  fi
  if [[ "$post_id" != "$healthy_id" || "$post_started" != "$healthy_started" ]]; then
    echo 'T3 restarted again during the readiness probe (container identity changed)' >&2
    exit 1
  fi
  if t3_ready; then
    break
  fi
  health_wait_sleep 5
done
if [[ -z "$post" ]] || ! t3_ready; then
  echo 'T3 did not stay ready after the accepted image restart' >&2
  exit 1
fi

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

# The receipt is mechanical: what was deployed, from which artifact, with which
# inputs, and what the container looked like before and after the restart. It
# records no behavioural PASS, because no behavioural suite runs in activation.
write_receipt() {
  local temporary="$receipt.tmp"
  "$JQ_BIN" -cn --arg deployment "$DEPLOYMENT_ID" --arg image "sha256:$image_id" \
    --arg candidate "t3code-candidate-$image_id" --arg agent "$AGENT_REVISION" \
    --arg tooling "$TOOLING_PATH" --arg secret "$secret_sha256" \
    --argjson before "$pre" --argjson after "$post" --arg at "$(date -u +%FT%TZ)" \
    --argjson schema "$STATE_SCHEMA" \
    '{schema:$schema,deployment_id:$deployment,image_id:$image,candidate_name:$candidate,
      agent_revision:$agent,agent_path:$tooling,provider_secret_sha256:$secret,
      live_before:$before,live_after:$after,verified:true,verified_at:$at}' > "$temporary"
  chmod 0600 "$temporary"
  mv -f "$temporary" "$receipt"
}
write_receipt
record_applied "$live_agent" "$live_secret"
publish_pass_attestation
install -d -m 0700 "$(dirname "$AUDIT_LOG")"
printf '%s\n' "action=candidate-accepted-restart deployment=$DEPLOYMENT_ID" >> "$AUDIT_LOG"
chmod 0600 "$AUDIT_LOG"
printf '%s\n' "candidate-accepted T3 Code restart: before $(printf '%s' "$pre" | "$JQ_BIN" -r '.id // "unknown"'), after $(printf '%s' "$post" | "$JQ_BIN" -r '.id // "unknown"')" \
  | systemd-cat -t t3code-restart -p warning
echo "Restart issued for accepted T3 image $DEPLOYMENT_ID"
