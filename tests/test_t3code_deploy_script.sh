#!/usr/bin/env bash
# Hermetic proof for packages/t3code/deploy.sh (the one T3 deploy script).
#
# Nothing here touches a host: nix, nix-store, nix-env, systemctl, podman and
# hostname are stubs, the built system is a temporary directory, and the
# current-system and system-profile links are temporary files. The real
# scripts/activate-host and packages/t3code/served-identity.sh run unchanged.
set -euo pipefail
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
deploy="$root/packages/t3code/deploy.sh"
[[ -x $deploy ]] || { echo "deploy.sh is not executable: $deploy" >&2; exit 1; }

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin" "$tmp/build/bin" "$tmp/build/etc/systemd/system" "$tmp/build/etc/ghostship"
mkdir -p "$tmp/store/layered-baked-t3code-baked-app" "$tmp/image" "$tmp/state" "$tmp/calls" "$tmp/systemd"

deployment_id=$(printf 'deploy-artifact' | sha256sum | cut -d ' ' -f 1)
image_id=$(printf 'image-artifact' | sha256sum | cut -d ' ' -f 1)
build=$tmp/build
image=$tmp/image
baked=$tmp/store/layered-baked-t3code-baked-app
printf '0.1.5\n' > "$baked/VERSION"
printf '%064d\n' 7 > "$baked/DIGEST"

# The built system: a switch stub, the deploy unit, and the artifact identity.
cat > "$build/bin/switch-to-configuration" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
printf 'switch %s\n' "$*" >> "$CALLS/switch"
ln -sfn "${FAKE_SWITCH_TARGET:?}" "${GHOSTSHIP_CURRENT_SYSTEM:?}"
SH
chmod +x "$build/bin/switch-to-configuration"
cat > "$build/etc/systemd/system/ghostship-t3code-deploy.service" <<EOF
[Service]
Environment="STATE_DIR=$tmp/state" "DEPLOYMENT_ID=$deployment_id" "IMAGE_ARCHIVE=$image"
EOF
cat > "$build/etc/ghostship/t3code-deploy-identity.json" <<EOF
{"host":"test-host","unit":"ghostship-t3code-deploy.service","state_dir":"$tmp/state",
 "deployment_id":"$deployment_id","agent_revision":"agent-rev","tooling_path":"$tmp/tooling",
 "image_archive":"$image","tree":"test-rev","dirty":false}
EOF

# The fast closure: the same identity, the image metadata root, and the
# image's own served-identity selector.
mkdir -p "$tmp/closure/image/usr/share/t3code" "$tmp/closure/image/home/t3code"
cp "$build/etc/ghostship/t3code-deploy-identity.json" "$tmp/closure/deploy-identity.json"
ln -s "$baked" "$tmp/closure/image/usr/share/t3code-app"
cp "$root/packages/t3code/served-identity.sh" "$tmp/closure/image/usr/share/t3code/served-identity.sh"

# --- stubs -------------------------------------------------------------------
cat > "$tmp/bin/nix" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
printf 'nix %s\n' "$*" >> "$CALLS/nix"
case "$1" in
  eval) printf 'aarch64-linux\n' ;;
  build)
    case "${!#}" in
      *t3code-deploy-closure) printf '%s\n' "$tmp/closure" ;;
      *deployment-wrappers) printf '%s\n' "$tmp/wrappers" ;;
      *) printf '%s\n' "$tmp/build" ;;
    esac
    ;;
  *) echo "unexpected nix invocation: $*" >&2; exit 1 ;;
esac
SH
cat > "$tmp/bin/nix-store" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$tmp/store/layered-baked-t3code-baked-app"
SH
cat > "$tmp/bin/nix-env" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
printf 'nix-env %s\n' "$*" >> "$CALLS/nix-env"
[[ $1 == -p && $3 == --set ]] || { echo "unexpected nix-env invocation: $*" >&2; exit 1; }
ln -sfn "$4" "$2"
SH
cat > "$tmp/bin/systemctl" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
case "$1" in
  show)
    case "$3" in
      ActiveState)
        state=$(cat "$SYSTEMD/active" 2>/dev/null || echo inactive)
        # An activation start is asynchronous: the first observation is
        # activating, the next one has finished.
        if [[ $state == activating ]]; then printf 'inactive\n' > "$SYSTEMD/active"; fi
        printf '%s\n' "$state"
        ;;
      Result) cat "$SYSTEMD/result" 2>/dev/null || echo success ;;
      *) echo "unexpected systemctl show: $*" >&2; exit 1 ;;
    esac
    ;;
  start)
    printf 'start %s\n' "$2" >> "$CALLS/systemctl"
    printf '%s\n' "${SYSTEMCTL_START_RESULT:-success}" > "$SYSTEMD/result"
    printf 'inactive\n' > "$SYSTEMD/active"
    ;;
  *) echo "unexpected systemctl invocation: $*" >&2; exit 1 ;;
esac
SH
cat > "$tmp/bin/podman" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
[[ $1 == inspect && $2 == t3code ]] || { echo "unexpected podman invocation: $*" >&2; exit 1; }
printf '%s %s %s\n' "${PODMAN_RUNNING:-true}" "${PODMAN_IMAGE:?}" "${PODMAN_HEALTH:-healthy}"
SH
cat > "$tmp/bin/hostname" <<'SH'
#!/usr/bin/env bash
printf 'test-host\n'
SH
cat > "$tmp/bin/deploy-status" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
[[ ${DEPLOY_STATUS_STATE:-coherent} == coherent ]] || { echo '{"state":"unknown"}'; exit 77; }
printf '{"state":"coherent","deployment":"%s","image":"%s"}\n' "${STUB_DEPLOYMENT:?}" "${STUB_IMAGE:?}"
SH
cat > "$tmp/bin/probe-sleep" <<'SH'
#!/usr/bin/env bash
printf 'probe-sleep %s\n' "$1" >> "$CALLS/probe"
SH
chmod +x "$tmp"/bin/*

export CALLS=$tmp/calls tmp build image deployment_id image_id baked
export GHOSTSHIP_CURRENT_SYSTEM=$tmp/current-system
export GHOSTSHIP_SYSTEM_PROFILE=$tmp/system-profile
export FAKE_SWITCH_TARGET=$build
export DEPLOY_STATUS=$tmp/bin/deploy-status
export STUB_DEPLOYMENT=$deployment_id
export STUB_IMAGE="sha256:$image_id"
export PODMAN_IMAGE="sha256:$image_id"
export SYSTEMD=$tmp/systemd
export DEPLOY_PROBE_SLEEP=$tmp/bin/probe-sleep
export DEPLOY_PROBE_INTERVAL=1
export DEPLOY_TIMEOUT_SECONDS=30
export NIX_BIN=$tmp/bin/nix NIX_STORE_BIN=$tmp/bin/nix-store JQ_BIN=jq
export SYSTEMCTL_BIN=$tmp/bin/systemctl PODMAN_BIN=$tmp/bin/podman
export HOSTNAME_BIN=$tmp/bin/hostname FLOCK_BIN=flock
export PATH="$tmp/bin:$PATH"
export HOME=$tmp/home
mkdir -p "$HOME"

run() {
  set +e
  bash "$deploy" "$@" > "$tmp/out.log" 2>&1
  rc=$?
  set -e
}

reset_calls() {
  rm -rf "$tmp/calls"; mkdir -p "$tmp/calls"
  rm -f "$GHOSTSHIP_CURRENT_SYSTEM" "$GHOSTSHIP_SYSTEM_PROFILE"
  printf 'inactive\n' > "$SYSTEMD/active"
  printf 'success\n' > "$SYSTEMD/result"
  rm -rf "$tmp/state"; mkdir -p "$tmp/state/attempts"
}

fail() {
  echo "FAIL: $*" >&2
  cat "$tmp/out.log" >&2
  exit 1
}

# --- 1. --no-deploy builds and tests without touching the host ---------------
reset_calls
run --no-deploy --flake "$root" --system chill-penguin
[[ $rc == 0 ]] || fail "--no-deploy exited $rc"
[[ -s $CALLS/nix ]] || fail '--no-deploy did not build'
grep -q 't3code-deploy-closure' "$CALLS/nix" || fail '--no-deploy did not build the deployment closure'
grep -q 'system.build.toplevel' "$CALLS/nix" && fail '--no-deploy built the whole host toplevel'
grep -q 'deployment-wrappers' "$CALLS/nix" || fail '--no-deploy did not test the deployment wrappers'
grep -q 'baked app 0.1.5' "$tmp/out.log" || fail '--no-deploy did not test the baked identity'
[[ ! -e $CALLS/systemctl ]] || fail '--no-deploy started or inspected a unit'
[[ ! -e $GHOSTSHIP_CURRENT_SYSTEM ]] || fail '--no-deploy switched the host'
echo 'No-deploy proof: built, wrappers and baked identity tested, host untouched.'

# --- 2. verify-only reports the deployed and running identity ----------------
reset_calls
run --verify-only --state "$tmp/state"
[[ $rc == 0 ]] || fail "--verify-only exited $rc"
grep -q "deployment $deployment_id serves sha256:$image_id and is healthy" "$tmp/out.log" \
  || fail '--verify-only did not report the coherent tuple'
other_image="sha256:$(printf 'other' | sha256sum | cut -d ' ' -f 1)"
export PODMAN_IMAGE=$other_image
run --verify-only --state "$tmp/state"
[[ $rc != 0 ]] || fail '--verify-only accepted a different running image'
export PODMAN_IMAGE="sha256:$image_id"
echo 'Verify proof: coherent tuple passes; a different running image fails.'

# --- 3. a full deploy records the generation and starts the unit -------------
reset_calls
run --flake "$root" --system chill-penguin
[[ $rc == 0 ]] || fail "full deploy exited $rc"
[[ $(readlink -f "$GHOSTSHIP_SYSTEM_PROFILE") == "$build" ]] || fail 'the system profile was not set to the build'
[[ $(readlink -f "$GHOSTSHIP_CURRENT_SYSTEM") == "$build" ]] || fail 'the running system is not the build'
[[ $(grep -c '^start ' "$CALLS/systemctl") == 1 ]] || fail 'the deployer was not started exactly once'
grep -q 'system.build.toplevel' "$CALLS/nix" || fail 'the full deploy did not build the host toplevel'
grep -q 'switch switch' "$CALLS/switch" || fail 'the built switch-to-configuration was not used'
grep -q 'complete for ' "$tmp/out.log" || fail 'the deploy did not report completion'
echo 'Deploy proof: profile set, built switch used, deployer started once, verified.'

# --- 4. an activation-started deployer is not started again ------------------
reset_calls
jq -cn --arg id "$deployment_id" '{deployment_id:$id,exit_code:0}' > "$tmp/state/attempts/$deployment_id.json"
printf 'activating\n' > "$SYSTEMD/active"
run --flake "$root" --system chill-penguin
[[ $rc == 0 ]] || fail "already-applied deploy exited $rc"
[[ ! -e $CALLS/systemctl ]] || fail 'the already-applied path started the deployer again'
grep -q 'already applied' "$tmp/out.log" || fail 'the already-applied path did not say so'
[[ -s $CALLS/probe ]] || fail 'the in-flight activation start was not observed'
echo 'Already-applied proof: the in-flight activation start is awaited, no second start.'

# --- 5. a switch that does not become the running system is a refusal --------
reset_calls
export FAKE_SWITCH_TARGET=$tmp/elsewhere
mkdir -p "$tmp/elsewhere/bin"
run --flake "$root" --system chill-penguin
[[ $rc != 0 ]] || fail 'a mismatched current-system was accepted'
grep -Eq 'does not match the system profile|not the build' "$tmp/out.log" || fail 'the mismatch was not named'
[[ ! -e $CALLS/systemctl ]] || fail 'a mismatched switch started the deployer'
export FAKE_SWITCH_TARGET=$build
echo 'Mismatch proof: a switch that does not become the running system is refused before any start.'

# --- 6. an attempt without an outcome is UNKNOWN, never replayed -------------
reset_calls
jq -cn --arg id "$deployment_id" '{deployment_id:$id,status:"running"}' > "$tmp/state/attempts/$deployment_id.json"
run --flake "$root" --system chill-penguin
[[ $rc != 0 ]] || fail 'an uncertain attempt was replayed'
grep -q 'never recorded an outcome' "$tmp/out.log" || fail 'the uncertain attempt was not named'
[[ ! -e $CALLS/systemctl ]] || fail 'an uncertain attempt started the deployer'
echo 'Uncertain-attempt proof: no outcome means no replay.'

# --- 7. a failed deployer result fails the deploy ----------------------------
reset_calls
export SYSTEMCTL_START_RESULT=failed
run --flake "$root" --system chill-penguin
[[ $rc != 0 ]] || fail 'a failed deployer result was accepted'
unset SYSTEMCTL_START_RESULT
grep -q 'Result=failed' "$tmp/out.log" || fail 'the failed result was not named'
echo 'Failed-result proof: the deploy fails when the deployer reports failure.'

# --- 8. an artifact for another host is refused before any effect ------------
reset_calls
run --flake "$root" --system chill-penguin --host other-host
[[ $rc != 0 ]] || fail 'an artifact for another host was deployed'
grep -q 'the artifact is for test-host' "$tmp/out.log" || fail 'the host mismatch was not named'
[[ ! -e $CALLS/switch ]] || fail 'a foreign artifact was switched to'
echo 'Host proof: an artifact built for another host is refused before any effect.'

# --- 9. a dirty-checkout artifact is refused unless explicitly allowed -------
reset_calls
jq '.dirty = true' "$build/etc/ghostship/t3code-deploy-identity.json" > "$tmp/identity.dirty"
cp "$tmp/identity.dirty" "$build/etc/ghostship/t3code-deploy-identity.json"
run --flake "$root" --system chill-penguin
[[ $rc != 0 ]] || fail 'a dirty-checkout artifact was deployed'
grep -q 'dirty checkout' "$tmp/out.log" || fail 'the dirty artifact was not named'
[[ ! -e $CALLS/switch ]] || fail 'a dirty-checkout artifact was switched to'
# The explicit flag is the only way through, and it still deploys the artifact.
run --flake "$root" --system chill-penguin --allow-dirty
[[ $rc == 0 ]] || fail "--allow-dirty exited $rc"
grep -q 'dirty true' "$tmp/out.log" || fail 'the dirty flag was not recorded'
cp "$build/etc/ghostship/t3code-deploy-identity.json" "$tmp/identity.restore"
jq '.dirty = false' "$tmp/identity.restore" > "$build/etc/ghostship/t3code-deploy-identity.json"
cp "$build/etc/ghostship/t3code-deploy-identity.json" "$tmp/closure/deploy-identity.json"
echo 'Dirty proof: a dirty-checkout artifact is refused before any effect; --allow-dirty deploys it.'

echo 'Deploy script fixture passed.'
