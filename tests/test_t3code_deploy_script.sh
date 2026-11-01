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
printf 'provider=fixture\n' > "$tmp/provider.env"
mkdir -p "$tmp/tooling"
mkdir -p "$tmp/bin" "$tmp/build/bin" "$tmp/build/etc/systemd/system" "$tmp/build/etc/ghostship"
mkdir -p "$tmp/store/layered-baked-t3code-baked-app" "$tmp/state" "$tmp/calls" "$tmp/systemd"
# The real artifact is a tarball file, never a directory.
: > "$tmp/image"

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
 "image_archive":"$image","image_metadata":"$tmp/closure/image",
 "provider_secrets_file":"$tmp/provider.env",
 "tree":"test-rev","dirty":false,"agent_dirty":false}
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
printf '%s\n' "$tmp/store/identity.json" "$tmp/store/layered-baked-t3code-baked-app" "$tmp/tooling" "$tmp/image"
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
cat > "$tmp/bin/nixos-rebuild" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
[[ $1 == --rollback && $2 == switch ]] || { echo "unexpected nixos-rebuild: $*" >&2; exit 1; }
printf 'rollback\n' >> "$CALLS/nixos-rebuild"
ln -sfn "$PREVIOUS_SYSTEM" "${GHOSTSHIP_SYSTEM_PROFILE:?}"
ln -sfn "$PREVIOUS_SYSTEM" "${GHOSTSHIP_CURRENT_SYSTEM:?}"
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
export NIX_BIN=$tmp/bin/nix NIX_STORE_BIN=$tmp/bin/nix-store JQ_BIN=jq
export IDENTITY_STORE_ROOT=$tmp/store
export SYSTEMCTL_BIN=$tmp/bin/systemctl PODMAN_BIN=$tmp/bin/podman
export HOSTNAME_BIN=$tmp/bin/hostname FLOCK_BIN=flock NIXOS_REBUILD_BIN=$tmp/bin/nixos-rebuild
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

# --- 1b. the etc identity symlink is accepted only from the store ------------
# environment.etc installs the identity as a symlink into a store path; the
# toplevel never carries a regular file there. Accept exactly that form.
reset_calls
cp "$build/etc/ghostship/t3code-deploy-identity.json" "$tmp/store/identity.json"
rm -f "$build/etc/ghostship/t3code-deploy-identity.json"
ln -s "$tmp/store/identity.json" "$build/etc/ghostship/t3code-deploy-identity.json"
run --build-only --flake "$root" --system chill-penguin
[[ $rc == 0 ]] || fail "--build-only refused the store identity symlink"
grep -q "deployment $deployment_id" "$tmp/out.log" || fail 'symlinked identity was not read'
ln -sfn "$tmp/outside.json" "$build/etc/ghostship/t3code-deploy-identity.json"
cp "$tmp/store/identity.json" "$tmp/outside.json"
run --build-only --flake "$root" --system chill-penguin
[[ $rc != 0 ]] || fail "an identity symlink outside the store was accepted"
cp "$tmp/store/identity.json" "$tmp/store/not-in-closure.json"
ln -sfn "$tmp/store/not-in-closure.json" "$build/etc/ghostship/t3code-deploy-identity.json"
run --build-only --flake "$root" --system chill-penguin
[[ $rc != 0 ]] || fail "an identity symlink outside the built closure was accepted"
rm -f "$build/etc/ghostship/t3code-deploy-identity.json"
cp "$tmp/store/identity.json" "$build/etc/ghostship/t3code-deploy-identity.json"
echo 'Symlink proof: closure store identity read; outside-store and outside-closure identities refused.'

# --- 1c. --test-artifact runs the real-artifact TEST without deploying ------
reset_calls
run --test-artifact --flake "$root" --system chill-penguin
[[ $rc == 0 ]] || fail "--test-artifact exited $rc"
grep -q 'full artifact built and tested; deployment skipped' "$tmp/out.log" \
  || fail '--test-artifact did not report the full test'
grep -q 'deployment wrappers built and shellchecked' "$tmp/out.log" \
  || fail '--test-artifact did not test the wrappers'
[[ ! -e $GHOSTSHIP_CURRENT_SYSTEM ]] || fail '--test-artifact switched the host'
[[ ! -e $CALLS/systemctl ]] || fail '--test-artifact started a unit'
echo 'Test-artifact proof: full artifact TEST ran, host untouched.'

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
[[ "$(cat "$tmp/state/desired")" == "$deployment_id" ]] || fail 'the deployment request was not recorded'
grep -q "agent=agent-rev" "$tmp/state/desired-inputs" || fail 'the deployment inputs were not recorded'
grep -q 'switch switch' "$CALLS/switch" || fail 'the built switch-to-configuration was not used'
grep -q 'complete for ' "$tmp/out.log" || fail 'the deploy did not report completion'
echo 'Deploy proof: profile set, built switch used, deployer started once, verified.'

# --- 4. an activation-started deployer is not started again ------------------
reset_calls
jq -cn --arg id "$deployment_id" '{deployment_id:$id,exit_code:0}' > "$tmp/state/attempts/$deployment_id.json"
run --flake "$root" --system chill-penguin
[[ $rc == 0 ]] || fail "already-applied deploy exited $rc"
[[ ! -e $CALLS/systemctl ]] || fail 'the already-applied path started the deployer again'
grep -q 'already applied' "$tmp/out.log" || fail 'the already-applied path did not say so'
echo 'Already-applied proof: a recorded success is not replayed.'

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

# --- 10. a dirty pinned input is refused the same way ------------------------
reset_calls
jq '.dirty = false | .agent_dirty = true | .agent_revision = "deadbeef-dirty"' \
  "$build/etc/ghostship/t3code-deploy-identity.json" > "$tmp/identity.agent-dirty"
cp "$tmp/identity.agent-dirty" "$build/etc/ghostship/t3code-deploy-identity.json"
run --flake "$root" --system chill-penguin
[[ $rc != 0 ]] || fail 'an artifact with a dirty pinned input was deployed'
grep -q 'pins a dirty agent input' "$tmp/out.log" || fail 'the dirty pinned input was not named'
[[ ! -e $CALLS/switch ]] || fail 'an artifact with a dirty pinned input was switched to'
run --flake "$root" --system chill-penguin --allow-dirty
[[ $rc == 0 ]] || fail "--allow-dirty with a dirty pin exited $rc"
jq '.dirty = false | .agent_dirty = false | .agent_revision = "agent-rev"' \
  "$build/etc/ghostship/t3code-deploy-identity.json" > "$tmp/identity.clean"
cp "$tmp/identity.clean" "$build/etc/ghostship/t3code-deploy-identity.json"
cp "$build/etc/ghostship/t3code-deploy-identity.json" "$tmp/closure/deploy-identity.json"
echo 'Dirty-pin proof: a dirty pinned input is refused before any effect; --allow-dirty deploys it.'

# --- 11. the installed system and the applied deployment must agree ----------
reset_calls
mkdir -p "$GHOSTSHIP_CURRENT_SYSTEM/etc/ghostship"
jq '.deployment_id = "9999999999999999999999999999999999999999999999999999999999999999"' \
  "$build/etc/ghostship/t3code-deploy-identity.json" \
  > "$GHOSTSHIP_CURRENT_SYSTEM/etc/ghostship/t3code-deploy-identity.json"
run --verify-only --state "$tmp/state"
[[ $rc != 0 ]] || fail 'a plain switch that changed the installed system was reported coherent'
grep -q 'run just deploy' "$tmp/out.log" || fail 'the installed/applied divergence was not named'
rm -rf "$GHOSTSHIP_CURRENT_SYSTEM"
echo 'Installed-system proof: a system change outside deploy.sh is named, not reported as the old tuple.'

# --- 12. rollback returns the system and the T3 deployment together ----------
reset_calls
previous=$tmp/previous-system
mkdir -p "$previous/bin" "$previous/etc/ghostship" "$previous/etc/systemd/system"
printf '#!/usr/bin/env bash\nexit 0\n' > "$previous/bin/switch-to-configuration"
chmod +x "$previous/bin/switch-to-configuration"
previous_id=$(printf 'previous-artifact' | sha256sum | cut -d ' ' -f 1)
previous_image=$(printf 'previous-image' | sha256sum | cut -d ' ' -f 1)
jq -n --arg d "$previous_id" --arg i "$tmp/image" --arg s "$tmp/state" --arg p "$tmp/provider.env" \
  --arg m "$tmp/closure/image" \
  '{host:"test-host",unit:"ghostship-t3code-deploy.service",state_dir:$s,deployment_id:$d,
    agent_revision:"agent-rev",tooling_path:"/tmp/tooling",image_archive:$i,image_metadata:$m,
    provider_secrets_file:$p,tree:"test-rev",dirty:false,agent_dirty:false}' \
  > "$previous/etc/ghostship/t3code-deploy-identity.json"
printf 'Environment="DEPLOYMENT_ID=%s" "IMAGE_ARCHIVE=%s"\n' "$previous_id" "$tmp/image" \
  > "$previous/etc/systemd/system/ghostship-t3code-deploy.service"
ln -sfn "$previous" "$tmp/system-profile-1-link"
ln -sfn "$build" "$tmp/system-profile-2-link"
export PREVIOUS_SYSTEM=$previous STUB_DEPLOYMENT=$previous_id STUB_IMAGE="sha256:$previous_image"
export PODMAN_IMAGE="sha256:$previous_image"
run --rollback
[[ $rc == 0 ]] || fail "rollback exited $rc"
[[ $(readlink -f "$GHOSTSHIP_CURRENT_SYSTEM") == "$previous" ]] || fail 'rollback did not switch the system'
[[ "$(readlink -f "$GHOSTSHIP_SYSTEM_PROFILE")" == "$previous" ]] || fail 'rollback did not record the generation'
[[ "$(cat "$tmp/state/desired")" == "$previous_id" ]] || fail 'rollback did not request the previous deployment'
[[ $(grep -c '^start ' "$CALLS/systemctl") == 1 ]] || fail 'rollback did not start the deployer once'
echo 'Rollback proof: the previous generation is switched and its deployment reconciled and verified.'
export STUB_DEPLOYMENT=$deployment_id STUB_IMAGE="sha256:$image_id" PODMAN_IMAGE="sha256:$image_id"

# --- 13. rollback refuses before the switch when the old image is gone --------
reset_calls
previous=$tmp/pruned-system
mkdir -p "$previous/bin" "$previous/etc/ghostship" "$previous/etc/systemd/system"
printf '#!/usr/bin/env bash\nexit 0\n' > "$previous/bin/switch-to-configuration"
chmod +x "$previous/bin/switch-to-configuration"
jq -n --arg d "$previous_id" --arg i "$tmp/pruned-image.tar.gz" --arg s "$tmp/state" --arg p "$tmp/provider.env" \
  --arg m "$tmp/closure/image" \
  '{host:"test-host",unit:"ghostship-t3code-deploy.service",state_dir:$s,deployment_id:$d,
    agent_revision:"agent-rev",tooling_path:"/tmp/tooling",image_archive:$i,image_metadata:$m,
    provider_secrets_file:$p,tree:"test-rev",dirty:false,agent_dirty:false}' \
  > "$previous/etc/ghostship/t3code-deploy-identity.json"
printf 'Environment="DEPLOYMENT_ID=%s" "IMAGE_ARCHIVE=%s"\n' "$previous_id" "$tmp/pruned-image.tar.gz" \
  > "$previous/etc/systemd/system/ghostship-t3code-deploy.service"
ln -sfn "$previous" "$tmp/system-profile-1-link"
ln -sfn "$build" "$tmp/system-profile-2-link"
export PREVIOUS_SYSTEM=$previous
run --rollback
[[ $rc != 0 ]] || fail 'rollback switched to a generation whose image archive is gone'
grep -q "image archive is gone" "$tmp/out.log" || fail 'the missing archive was not named'
[[ ! -e $CALLS/nixos-rebuild ]] || fail 'rollback switched the system before refusing'
echo 'Rollback guard proof: a pruned previous image is refused before the system switch.'

echo 'Deploy script fixture passed.'
