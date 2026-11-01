#!/usr/bin/env bash
# The one T3 deployment script: BUILD -> TEST -> DEPLOY -> VERIFY on one artifact.
#
#   packages/t3code/deploy.sh                 build, test, deploy, verify
#   packages/t3code/deploy.sh --no-deploy     build and test only (CI)
#   packages/t3code/deploy.sh --build-only    build and print the identity
#   packages/t3code/deploy.sh --verify-only   read-only deployed/running check
#
# Run it from a working checkout, as root for anything that deploys. The
# deployment identity (deployment id, agent revision, tooling path, image
# archive) is read from the built system's
# etc/ghostship/t3code-deploy-identity.json, so what is deployed is exactly
# what was built and the caller never passes a release id.
#
# DEPLOY does what nixos-rebuild does, in order: record the built generation in
# the system profile, switch to it, then run ghostship-t3code-deploy.service
# from that now-current system and read its result. VERIFY is read-only and is
# also what an operator runs before any retry.
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd -- "$script_dir/../.." && pwd)

NIX_BIN=${NIX_BIN:-nix}
NIX_STORE_BIN=${NIX_STORE_BIN:-nix-store}
JQ_BIN=${JQ_BIN:-jq}
SYSTEMCTL_BIN=${SYSTEMCTL_BIN:-systemctl}
PODMAN_BIN=${PODMAN_BIN:-podman}
FLOCK_BIN=${FLOCK_BIN:-flock}
NIXOS_REBUILD_BIN=${NIXOS_REBUILD_BIN:-nixos-rebuild}
HOSTNAME_BIN=${HOSTNAME_BIN:-hostname}
ACTIVATE_HOST=${ACTIVATE_HOST:-$repo_root/scripts/activate-host}
DEPLOY_STATUS=${DEPLOY_STATUS:-$script_dir/deploy-status.sh}
CURRENT_SYSTEM=${GHOSTSHIP_CURRENT_SYSTEM:-/run/current-system}
SYSTEM_PROFILE=${GHOSTSHIP_SYSTEM_PROFILE:-/nix/var/nix/profiles/system}
# The artifact identity may be a store symlink (environment.etc); the test
# harness substitutes its own store root.
IDENTITY_STORE_ROOT=${IDENTITY_STORE_ROOT:-/nix/store}

mode=deploy
flake=$repo_root
allow_dirty=0
system=${DEPLOY_SYSTEM:-}
host=${DEPLOY_HOST:-}
state_dir=/var/lib/ghostship/t3code-deployment
state_given=0
override_inputs=()

usage() {
  cat <<'EOF'
Usage: deploy.sh [OPTIONS]

  --no-deploy            build and test the artifact, do not touch the host
  --build-only           build the artifact and print its identity
  --verify-only          read-only deployed and running identity check
  --rollback             switch to the previous generation and return T3 to it
  --allow-dirty          deploy an artifact built from a dirty checkout
  --flake REF            checkout or flake reference to build (default: this checkout)
  --system NAME          nixosConfigurations attribute (default: this host name)
  --host NAME            host name the artifact must name (default: this host name)
  --state DIR            deployment state directory (default: from the artifact)
  --override-file FILE   read "name url" lines as --override-input pairs
  --override-input N U   pass one flake input override
  --help                 show this text

The deployment identity is read from the built system, so no release id is
passed in. BUILD once, TEST that artifact, DEPLOY that artifact, then VERIFY.
EOF
}

die() {
  # Name the step, so a T3 failure says which step failed and nothing else is
  # implied to be at risk.
  echo "deploy: [${phase_name:-start}] $*" >&2
  exit 1
}

phase() {
  phase_name=$1
  printf '\n==> %s\n' "$*"
}

while [[ $# -gt 0 ]]; do
  case $1 in
    --no-deploy) mode=no-deploy; shift ;;
    --build-only) mode=build; shift ;;
    --allow-dirty) allow_dirty=1; shift ;;
    --verify-only) mode=verify-only; shift ;;
    --rollback) mode=rollback; shift ;;
    --flake) flake=${2:?--flake needs a reference}; shift 2 ;;
    --system) system=${2:?--system needs a name}; shift 2 ;;
    --host) host=${2:?--host needs a name}; shift 2 ;;
    --state) state_dir=${2:?--state needs a directory}; state_given=1; shift 2 ;;
    --override-file)
      override_file=${2:?--override-file needs a path}
      [[ -f $override_file && ! -L $override_file ]] || die "override file is missing or a symlink: $override_file"
      while read -r name url; do
        [[ -n ${name:-} ]] || continue
        override_inputs+=(--override-input "$name" "$url")
      done < "$override_file"
      shift 2
      ;;
    --override-input)
      [[ -n ${2:-} && -n ${3:-} ]] || die '--override-input needs a name and a url'
      override_inputs+=(--override-input "$2" "$3")
      shift 3
      ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown argument: $1 (see --help)" ;;
  esac
done

# nix build ARGS... prints the built store path and nothing else. NIX_BUILD_LOGS=1
# adds the build log so CI can show which derivations were built, fetched or
# reused instead of only the final path.
nix_build() {
  local logs=()
  [[ ${NIX_BUILD_LOGS:-0} == 1 ]] && logs=(--print-build-logs)
  "$NIX_BIN" build --no-link --print-out-paths --impure "${logs[@]}" "${override_inputs[@]}" "$@"
}

read_identity() {
  local file=$1 target
  # environment.etc renders the identity as a symlink into an immutable store
  # path, not a regular file under the toplevel. Follow that link only when it
  # stays inside the store; a link anywhere else is refused.
  if [[ -L $file ]]; then
    target=$(readlink -f "$file") || die "the deployment identity symlink is unresolvable: $file"
    case $target in
      "$IDENTITY_STORE_ROOT"/*) ;;
      *) die "the deployment identity symlink leaves the store: $file -> $target" ;;
    esac
    [[ -f $target && ! -L $target ]] || die "the deployment identity symlink target is not a regular file: $target"
    [[ -n ${build:-} ]] || die "the deployment identity symlink has no built system to check: $file"
    "$NIX_STORE_BIN" -qR "$build" 2>/dev/null | grep -qxF "$target" \
      || die "the deployment identity symlink target is not in the built system's closure: $target"
    file=$target
  fi
  [[ -f $file ]] || die "the built system has no deployment identity at $1"
  deployment_id=$("$JQ_BIN" -er '.deployment_id // empty' "$file")
  agent_revision=$("$JQ_BIN" -er '.agent_revision // empty' "$file")
  tooling_path=$("$JQ_BIN" -er '.tooling_path // empty' "$file")
  image_archive=$("$JQ_BIN" -er '.image_archive // empty' "$file")
  identity_state=$("$JQ_BIN" -er '.state_dir // empty' "$file")
  identity_host=$("$JQ_BIN" -er '.host // empty' "$file")
  identity_unit=$("$JQ_BIN" -er '.unit // empty' "$file")
  identity_tree=$("$JQ_BIN" -r '.tree // "unknown"' "$file")
  identity_dirty=$("$JQ_BIN" -r '.dirty // false' "$file")
  identity_agent_dirty=$("$JQ_BIN" -r '.agent_dirty // false' "$file")
  provider_secrets_file=$("$JQ_BIN" -er '.provider_secrets_file // empty' "$file")
  [[ -n $provider_secrets_file ]] || die 'the built identity names no provider secret file'
  [[ $deployment_id =~ ^[0-9a-f]{64}$ ]] || die 'the built identity has no deployment id'
  [[ -n $agent_revision && -n $tooling_path && -n $image_archive ]] || die 'the built identity is incomplete'
  [[ -n $identity_state && -n $identity_unit ]] || die 'the built identity names no state directory or unit'
}

resolve_nix_system() {
  nix_system=$("$NIX_BIN" eval --raw --impure --expr builtins.currentSystem)
}

# The fast path: the T3 deployment closure only (identity JSON, image metadata
# and the deploy unit's wiring). The archive and the host toplevel are not
# inputs to a deployment identity, so a pull request does not build them.
build_closure() {
  [[ -n $system ]] || die 'no --system and no host name to build'
  phase "BUILD the T3 deployment closure for $system"
  closure=$(nix_build "$flake#checks.$nix_system.t3code-deploy-closure")
  [[ -n $closure ]] || die 'the deployment closure did not build'
  read_identity "$closure/deploy-identity.json"
  (( state_given == 1 )) || state_dir=$identity_state
  echo "deploy: deployment closure $closure"
  echo "deploy: deployment $deployment_id agent $agent_revision tree $identity_tree dirty $identity_dirty"
}

# The full path: the host system generation a switch activates. A T3-only
# change reuses everything else in it from the cache.
build_artifact() {
  [[ -n $system ]] || die 'no --system and no host name to build'
  phase "BUILD $flake#nixosConfigurations.$system"
  build=$(nix_build "$flake#nixosConfigurations.$system.config.system.build.toplevel")
  [[ -n $build && -x $build/bin/switch-to-configuration ]] \
    || die "the build produced no system generation: ${build:-<none>}"
  read_identity "$build/etc/ghostship/t3code-deploy-identity.json"
  (( state_given == 1 )) || state_dir=$identity_state
  echo "deploy: artifact $build"
  echo "deploy: deployment $deployment_id agent $agent_revision tree $identity_tree dirty $identity_dirty"
}

test_artifact() {
  phase 'TEST the deployment artifact'
  # #801/#1747: build the deployment wrappers the host installs. Their build
  # runs shellcheck over every generated wrapper, so this tests the artifact
  # instead of keeping a second copy of the checks.
  nix_build "$flake#checks.$nix_system.deployment-wrappers" >/dev/null
  echo 'deploy: deployment wrappers built and shellchecked'

  if [[ $mode == deploy || $mode == build ]]; then
    local unit_file=$build/etc/systemd/system/$identity_unit
    [[ -f $unit_file ]] || die "the built system has no $identity_unit"
    # The unit and the identity file are generated from the same values; if
    # they ever disagree the deployment would not run what was tested.
    grep -Fq "DEPLOYMENT_ID=$deployment_id" "$unit_file" \
      || die 'the unit does not name the built deployment id'
    grep -Fq "IMAGE_ARCHIVE=$image_archive" "$unit_file" \
      || die 'the unit does not name the built image archive'
    # The tooling and the image must come from the built system, not from a
    # stale store path: a mixed old-system/new-tools state is refused here,
    # before any effect.
    local required
    for required in "$tooling_path" "$image_archive"; do
      "$NIX_STORE_BIN" -qR "$build" | grep -qxF "$required" \
        || die "the built system does not contain $required (a mixed old-system/new-tools state)"
    done
    echo 'deploy: tooling and image belong to the built system'
    test_baked_identity
    return 0
  fi
  test_closure_metadata
}

test_closure_metadata() {
  # The closure check already asserted the identity and the unit wiring and
  # read the baked version through served-identity.sh; run the same selector
  # again here so the fast path prints what it proved.
  local served
  served=$(T3CODE_HOME_PREFIX=$closure/image/home/t3code \
    "$closure/image/usr/share/t3code/served-identity.sh" --root "$closure/image") \
    || die 'served-identity refused the image metadata'
  echo "deploy: baked app $("$JQ_BIN" -r '.baked.version' <<< "$served") is the image's served identity"
}

test_baked_identity() {
  # The baked app is a store path the image archive references. Read the real
  # VERSION/DIGEST through the image's own selector, not a copy of its rules.
  local baked version digest root served
  [[ -d $image_archive ]] || die "the built image archive is missing: $image_archive"
  baked=$("$NIX_STORE_BIN" -qR "$image_archive" | grep -E -- '-t3code-baked-app$' | head -n 1 || true)
  [[ -n $baked ]] || die 'the image archive does not reference the baked T3 app'
  version=$(tr -d '[:space:]' < "$baked/VERSION")
  digest=$(tr -d '[:space:]' < "$baked/DIGEST")
  [[ $version =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "the baked app has no usable VERSION: $version"
  [[ $digest =~ ^[0-9a-f]{64}$ ]] || die 'the baked app has no usable DIGEST'

  root=$(mktemp -d)
  mkdir -p "$root/usr/share" "$root/home/t3code"
  ln -s "$baked" "$root/usr/share/t3code-app"
  if ! served=$(T3CODE_HOME_PREFIX=$root/home/t3code "$script_dir/served-identity.sh" --root "$root" 2>&1); then
    rm -rf "$root"
    die "served-identity refused the baked artifact: $served"
  fi
  rm -rf "$root"
  [[ $("$JQ_BIN" -r '.baked.version' <<< "$served") == "$version" ]] \
    || die 'served-identity disagrees with the baked VERSION'
  echo "deploy: baked app $version ($digest) is the image's served identity"
}

deploy_status_output() {
  "$DEPLOY_STATUS" --state "$state_dir" 2>/dev/null
}

running_container() {
  "$PODMAN_BIN" inspect t3code --format '{{.State.Running}} {{.Image}} {{.State.Health.Status}}' 2>/dev/null || true
}

# read_applied sets applied_deployment/applied_image from deploy-status and
# applied_running_image/applied_health from the running container. It returns 1
# with applied_reason instead of exiting, so callers can decide.
read_applied() {
  local status line
  applied_reason=''
  status=$(deploy_status_output) || { applied_reason='deploy-status reports no coherent tuple'; return 1; }
  applied_deployment=$("$JQ_BIN" -r '.deployment // empty' <<< "$status")
  applied_image=$("$JQ_BIN" -r '.image // empty' <<< "$status")
  [[ -n $applied_deployment && -n $applied_image ]] \
    || { applied_reason='deploy-status named no deployment image'; return 1; }
  line=$(running_container)
  read -r applied_running applied_running_image applied_health <<< "$line"
  [[ $applied_running == true ]] || { applied_reason='the T3 container is not running'; return 1; }
  [[ $applied_running_image == "$applied_image" ]] \
    || { applied_reason="the running container is ${applied_running_image:-unknown}, not the deployed image $applied_image"; return 1; }
  [[ $applied_health == healthy ]] \
    || { applied_reason="the T3 container health is ${applied_health:-unknown}"; return 1; }
  return 0
}

# The installed system records what it wants in its own identity file. A plain
# `nixos-rebuild switch` or a system-only rollback changes this without touching
# the T3 deployment state, so VERIFY has to name that divergence instead of
# reporting the old coherent tuple.
installed_deployment() {
  "$JQ_BIN" -r '.deployment_id // empty' \
    "$CURRENT_SYSTEM/etc/ghostship/t3code-deploy-identity.json" 2>/dev/null || true
}

verify_running() {
  deployment_id=${deployment_id:-}
  phase 'VERIFY the deployed and running identity'
  if ! read_applied; then
    die "${applied_reason:-the deployed identity is not verifiable}"
  fi
  local installed
  installed=$(installed_deployment)
  if [[ -n $installed && $installed != "$applied_deployment" ]]; then
    die "the installed system wants $installed but the applied deployment is $applied_deployment; run just deploy to deploy the installed system"
  fi
  if [[ -n $deployment_id && $applied_deployment != "$deployment_id" ]]; then
    die "the deployed identity $applied_deployment is not the built deployment $deployment_id"
  fi
  echo "deploy: deployment $applied_deployment serves $applied_image and is healthy"
}

verify_deployable() {
  local expected_host=${host:-$($HOSTNAME_BIN -s 2>/dev/null || true)}
  [[ -n $expected_host ]] || die 'cannot read this host name; pass --host'
  [[ $identity_host == "$expected_host" ]] \
    || die "the artifact is for $identity_host, this host is $expected_host"
  if [[ $allow_dirty != 1 ]]; then
    [[ $identity_dirty != true ]] \
      || die "the artifact was built from a dirty checkout at $identity_tree; commit it or pass --allow-dirty"
    [[ $identity_agent_dirty != true ]] \
      || die "the artifact pins a dirty agent input at $agent_revision; pin a clean revision or pass --allow-dirty"
  fi
}

assert_current_build() {
  local running profile
  running=$(readlink -f "$CURRENT_SYSTEM" 2>/dev/null || true)
  profile=$(readlink -f "$SYSTEM_PROFILE" 2>/dev/null || true)
  [[ $running == "$build" ]] || die "the running system is ${running:-unknown}, not the build $build"
  [[ $profile == "$build" ]] || die "the system profile is ${profile:-unknown}, not the build $build"
}

unit_result() {
  "$SYSTEMCTL_BIN" show -p Result --value "$identity_unit" 2>/dev/null || true
}

attempt_file() {
  printf '%s/attempts/%s.json\n' "$state_dir" "$deployment_id"
}

# Record the request under the deployer's own lock: one writer, and the deployer
# can never read a half-written request. The lock is released before the start,
# because the deployer holds it for the whole deployment.
write_desired() {
  phase 'RECORD the deployment request'
  install -d -m 0700 "$state_dir"
  exec 7>"$state_dir/deploy.lock"
  "$FLOCK_BIN" -x 7
  printf '%s\n' "$deployment_id" > "$state_dir/desired.tmp"
  mv -f "$state_dir/desired.tmp" "$state_dir/desired"
  local secret_sha256
  secret_sha256=$(sha256sum "$provider_secrets_file" | cut -d ' ' -f 1)
  printf 'agent=%s secret_sha256=%s tooling=%s\n' \
    "$agent_revision" "$secret_sha256" "$tooling_path" > "$state_dir/desired-inputs.tmp"
  mv -f "$state_dir/desired-inputs.tmp" "$state_dir/desired-inputs"
  rm -f "$state_dir/restart.pending" "$state_dir/restart.pending.tmp"
  exec 7>&-
}

# reconcile_attempt returns 0 when this deployment is already applied, 1 when a
# new start is required, and exits when the recorded outcome is uncertain.
reconcile_attempt() {
  local file=$1 code
  [[ -f $file && ! -L $file ]] || return 1
  code=$("$JQ_BIN" -r '.exit_code // empty' "$file" 2>/dev/null || true)
  if [[ -z $code ]]; then
    die "an earlier attempt for $deployment_id never recorded an outcome; run $DEPLOY_STATUS --state $state_dir and inspect it before retrying"
  fi
  if [[ $code == 0 ]] && read_applied && [[ $applied_deployment == "$deployment_id" ]]; then
    echo "deploy: $deployment_id is already applied and verified; nothing to deploy"
    return 0
  fi
  echo "deploy: an earlier attempt exited $code; its recorded state is below" >&2
  "$DEPLOY_STATUS" --state "$state_dir" || true
  return 1
}

deploy_artifact() {
  verify_deployable
  phase 'DEPLOY the built artifact'
  install -d -m 0700 "$state_dir"
  # One writer for the switch. The deployer's own lock cannot be held across
  # the switch: the activation script takes it, so holding it here would
  # deadlock the activation.
  exec 6>"$state_dir/deploy-run.lock"
  "$FLOCK_BIN" -x 6

  "$ACTIVATE_HOST" --toplevel "$build"
  assert_current_build

  if reconcile_attempt "$(attempt_file)"; then
    verify_running
    return 0
  fi
  write_desired
  echo "deploy: starting $identity_unit from $build"
  "$SYSTEMCTL_BIN" start "$identity_unit"
  local result
  result=$(unit_result)
  [[ $result == success ]] || die "the deployer unit reported Result=$result"
  verify_running
}

if [[ $mode == verify-only ]]; then
  verify_running
  exit 0
fi

# The generation link below the current one. Deployments record their own image
# archive, so rollback can refuse before the switch when that archive is gone.
previous_generation() {
  local link
  link=$(
    for candidate in "$SYSTEM_PROFILE"-*-link; do
      [[ -e $candidate ]] || continue
      printf '%s\n' "$candidate"
    done | sort -V | tail -n 2 | head -n 1
  )
  [[ -n $link ]] || return 1
  readlink -f "$link"
}

if [[ $mode == rollback ]]; then
  phase 'ROLLBACK the host system generation'
  previous=$(previous_generation) || die 'there is no previous system generation to roll back to'
  [[ $previous != "$(readlink -f "$CURRENT_SYSTEM" 2>/dev/null || true)" ]] \
    || die 'the previous generation is the running system; nothing to roll back to'
  previous_identity=$previous/etc/ghostship/t3code-deploy-identity.json
  previous_archive=''
  if [[ -e $previous_identity || -L $previous_identity ]]; then
    previous_archive=$("$JQ_BIN" -r '.image_archive // empty' "$previous_identity" 2>/dev/null || true)
  fi
  # The old generation's unit loads its own archive. If that archive has been
  # collected, the container could not return to the old image, so refuse
  # before the system switch rather than leave the system and T3 disagreeing.
  [[ -z $previous_archive || -d $previous_archive ]] \
    || die "the previous generation's image archive is gone: $previous_archive; refusing to switch"
  "$NIXOS_REBUILD_BIN" --rollback switch
  build=$(readlink -f "$CURRENT_SYSTEM" 2>/dev/null || true)
  [[ -n $build && -x $build/bin/switch-to-configuration ]] \
    || die "the previous generation is not a built system: ${build:-unknown}"
  read_identity "$build/etc/ghostship/t3code-deploy-identity.json"
  (( state_given == 1 )) || state_dir=$identity_state
  echo "deploy: rolled back system $build, deployment $deployment_id"
  assert_current_build
  install -d -m 0700 "$state_dir"
  if reconcile_attempt "$(attempt_file)"; then
    verify_running
    exit 0
  fi
  write_desired
  "$SYSTEMCTL_BIN" start "$identity_unit"
  [[ $(unit_result) == success ]] || die "the deployer unit reported Result=$(unit_result)"
  verify_running
  echo "deploy: rollback complete for $deployment_id"
  exit 0
fi

[[ -n $system ]] || system=$($HOSTNAME_BIN -s 2>/dev/null || true)
resolve_nix_system
if [[ $mode == no-deploy ]]; then
  build_closure
else
  build_artifact
fi
if [[ $mode == build ]]; then
  exit 0
fi
test_artifact
if [[ $mode == no-deploy ]]; then
  echo 'deploy: deployment closure built and tested; deployment skipped'
  exit 0
fi
deploy_artifact
echo "deploy: complete for $deployment_id"
