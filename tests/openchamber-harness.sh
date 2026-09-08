#!/usr/bin/env bash
set -Eeuo pipefail
trap 'printf "OpenChamber test failed at %s:%s: %s\n" "$0" "$LINENO" "$BASH_COMMAND" >&2' ERR

repo_root="$(git rev-parse --show-toplevel)"
module="$repo_root/modules/self-hosted/openchamber.nix"
install_body="$(sed -n '/^    sandbox_install() {$/,/^    }$/p' "$module")"
lifecycle_body="$(sed -n '/^    sandbox_run_lifecycle() {$/,/^    }$/p' "$module")"
cli_body="$(sed -n '/^    sandbox_validate_clis() {$/,/^    }$/p' "$module")"
server_body="$(sed -n '/^    sandbox_validate_server() {$/,/^    }$/p' "$module")"
scheduler_body="$(sed -n '/^    sandbox_validate_scheduler() {$/,/^    NODE$/p' "$module")"
first_generation_body="$(sed -n '/^    ensure_first_generation() {$/,/^    }$/p' "$module")"

rg -q 'npm view @openchamber/web@latest version' "$module"
rg -q 'npm view opencode-ai@latest version' "$module"
rg -q 'OPENCHAMBER_TOOL_ENV_SANITIZED' "$module"
rg -q 'sandbox_install' "$module"
rg -q 'sandbox_run_lifecycle' "$module"
rg -q 'sandbox_validate_clis' "$module"
rg -q 'sandbox_validate_server' "$module"
rg -q 'sandbox_validate_scheduler' "$module"
rg -q -- '--ignore-scripts' "$module"
rg -q 'npm rebuild -g --prefix /candidate --offline' "$module"
rg -q -- '--unshare-all' <<< "$install_body"
rg -q -- '--share-net' <<< "$install_body"
rg -q -- '--unshare-all' <<< "$lifecycle_body"
if rg -q -- '--share-net' <<< "$lifecycle_body"; then
  printf 'lifecycle sandbox unexpectedly shares the production network\n' >&2
  exit 1
fi
rg -q -- '--unshare-all' <<< "$cli_body"
if rg -q -- '--share-net' <<< "$cli_body"; then
  printf 'candidate CLI sandbox unexpectedly shares the production network\n' >&2
  exit 1
fi
rg -q -- '--unshare-all' <<< "$server_body"
if rg -q -- '--share-net' <<< "$server_body"; then
  printf 'candidate server sandbox unexpectedly shares the production network\n' >&2
  exit 1
fi
rg -q -- '--cap-add CAP_NET_ADMIN' <<< "$server_body"
rg -q 'ip link set lo up' <<< "$server_body"
rg -q -- '--unshare-all' <<< "$scheduler_body"
rg -q 'paused scheduler dispatched overdue work' <<< "$scheduler_body"
rg -q 'persisted overdue occurrences were duplicated or lost' <<< "$scheduler_body"
rg -q 'generations_dir=.*tools_root/generations' "$module"
rg -q 'staging=.*\.staging-' "$module"
rg -q 'validate_generation' "$module"
rg -q 'harden_generation' "$module"
rg -q 'candidate symlink escapes or dangles' "$module"
rg -q 'relative_to\(candidate_root\)' "$module"
rg -q 'chmod -R a-w' "$module"
rg -q 'mv -Tf .*active.next.*active' "$module"
rg -q 'active_is_usable' "$module"
rg -q 'OPENCHAMBER_MAINTENANCE_GATE' "$module"
rg -q 'maintenanceGatePath' "$module"
rg -q 'maintenanceObserverPaused' "$module"
rg -q 'globalMessageStreamHub.stop' "$module"
rg -q 'openCodeWatcherRuntime.stop' "$module"
rg -q 'maintenanceActiveMutations' "$module"
rg -q 'maintenance-drain' "$module"
rg -q 'activeTerminalSessions' "$module"
rg -q 'activeScheduledTasks' "$module"
rg -q 'queuedScheduledTasks' "$module"
rg -q 'const activeScheduledTasks = scheduledTaskStatus.runningScheduledTasksCount' "$module"
rg -q 'maintenanceGateActive && !maintenanceSchedulerPaused' "$module"
rg -q 'runningScheduledTasksCount' "$module"
rg -q 'queuedScheduledTasksCount' "$module"
rg -q 'getActiveSessionCount' "$module"
rg -Fq 'pendingSessionCreates.size + [...sessions.values()]' "$module"
rg -q 'maintenanceSchedulerPaused' "$module"
rg -q 'pauseForMaintenance' "$module"
rg -q 'resumeAfterMaintenance' "$module"
rg -q 'persistedNextRunAt' "$module"
rg -q 'maintenancePaused' "$module"
rg -q 'OPENCHAMBER_OPENCODE_GATE' "$module"
rg -q -- '--uid-owner 0' "$module"
rg -q -- '--ctstate NEW' "$module"
rg -q -- '--connections-drained' "$module"
rg -q 'allow-absent' "$module"
rg -q 'openchamberHarnessRevision' "$module"
rg -q '\.openchamber-harness-revision' "$module"
rg -q -- '--user 3000:3000' "$module"
rg -q -- '--env PATH=/bin:/usr/bin' "$module"
rg -q '/bin/bash -s' "$module"
rg -q 'managed_opencode_root_probe' "$module"
rg -q 'maintenanceObserverResumePromise' "$module"
rg -q 'openchamberToolControl = "/srv/apps/openchamber/tool-update-control"' "$module"
rg -q 'openchamberToolControl.*:/var/lib/openchamber-tool-update:rw' "$module"
rg -q 'promotion.tsv' "$module"
rg -q 'tool-promotion-recovery' "$module"
test "$(rg -c 'promotion\.tsv' "$module")" -ge 5
rg -q 'container kill deferred' "$module"
rg -q 'recovering interrupted promotion' "$module"
rg -q 'recovery_pending=1' "$module"
rg -q 'restored runtime is healthy' "$module"
rg -q 'install_user_shims' "$module"
rg -q 'prune_generations' "$module"
rg -q 'generation_dir.*active_generation' "$module"
rg -Fq 'chmod -R u+w "$generation_dir"' "$module"
rg -q 'prestage-first-generation' "$module"
rg -q 'first-generation-prestage-failed' "$module"
rg -q 'readlink -f' <<< "$first_generation_body"
rg -q 'openchamber-tools/generations/\*' <<< "$first_generation_body"
rg -q 'bootstrap-candidate' "$module"
rg -q 'without registry access' "$module"
if rg -q 'bootstrap' <<< "$first_generation_body"; then
  printf 'first-generation prestaging unexpectedly promotes the candidate\n' >&2
  exit 1
fi
rg -q 'openchamberManagedOpenCodeIdle' "$module"
rg -q -- '--print-port' "$module"
rg -q 'legacy-runtime-needs-controlled-stop' "$module"
rg -q 'action=admissions-gated' "$module"
rg -q 'stop-quiesced-container' "$module"
rg -q 'flock -u 9' "$module"
rg -q 'action=start-container' "$module"
rg -q 'update-install.*status\(403\)' "$module"
rg -q 'opencode/upgrade.*status\(403\)' "$module"
rg -q "req.path === '/global/upgrade'" "$module"
rg -q 'commands-update.js' "$module"
rg -q '/api/opencode/health' "$module"
rg -q 'is_openchamber_idle || return 1' "$module"
rg -q 'TimeoutStartSec=20m' "$module"
rg -q 'TimeoutStartSec=30m' "$module"
rg -q 'container_age_seconds=3600' "$module"
rg -q 'seq 1 360' "$module"
rg -q 'TimeoutStartSec = "70m"' "$module"
rg -q 'validate-candidate' "$module"
rg -q 'chown -R root:root "\$candidate"' "$module"
validate_line="$(rg -n '= validate-candidate \]; then' "$module" | head -n1 | cut -d: -f1)"
maintenance_flock_line="$(rg -n '\$\{pkgs.util-linux\}/bin/flock 9' "$module" | head -n1 | cut -d: -f1)"
test -n "$validate_line"
test -n "$maintenance_flock_line"
test "$validate_line" -lt "$maintenance_flock_line"
rg -q 'health-restart.pending' "$module"
rg -q 'queue-restart' "$module"
rg -q 'restore_previous_container' "$module"
rg -q 'rollback-image.conf' "$module"
rg -q 'rollback_image_file=.*rollback-image' "$module"
rg -q 'rollback_desired_file=.*rollback-desired' "$module"
rg -q 'rollback-pending' "$module"
rg -q 'restore_previous_when_safe' "$module"
rg -q 'rollback_container_healthy || restore_previous_when_safe' "$module"
rg -q 'arm_opencode_network_gate allow-absent' "$module"
rg -q 'managed_opencode_quiesced_or_absent' "$module"
rg -q 'openchamberManagedOpenCodePresentPortable' "$module"
rg -q 'quiesce_failed_replacement' "$module"
rg -q 'failed-replacement-gated' "$module"
test "$(rg -c 'MemoryMax=4G' "$module")" -ge 3
test "$(rg -c 'TasksMax=512' "$module")" -ge 3
rg -q -- '--memory=4g' "$module"
rg -q -- '--memory-reservation=2g' "$module"
rg -q -- '--pids-limit=512' "$module"
rg -q 'external OpenCode is active; coordinated recovery owns its admission gate' "$module"
rg -q 'action=rollback-complete superseded=' "$module"
worker_rollback_line="$(rg -n 'if \[ -f "\$rollback_image_file" \] && \[ -f "\$rollback_desired_file" \]; then' "$module" | head -n1 | cut -d: -f1)"
worker_applied_line="$(rg -n 'if \[ "\$desired" = "\$applied" \]; then' "$module" | head -n1 | cut -d: -f1)"
activation_rollback_line="$(rg -n 'if \[ -f "\$rollback_image_file" \] && \[ -f "\$rollback_desired_file" \]; then' "$module" | tail -n1 | cut -d: -f1)"
activation_applied_line="$(rg -n 'elif \[ "\$applied" = "\$desired" \]; then' "$module" | tail -n1 | cut -d: -f1)"
test "$worker_rollback_line" -lt "$worker_applied_line"
test "$activation_rollback_line" -lt "$activation_applied_line"
rg -q 'ExecStartPost=+.*openchamber-harden-active-generation' "$module"
if rg -q 'chown -R openchamber:openchamber.*openchamber-tools' "$module"; then
  printf 'container setup recursively returns immutable generations to the runtime user\n' >&2
  exit 1
fi
rg -q 'promotion is queued behind the continuous-idle gate' "$module"
rg -q 'failed promotion; waiting for a newer latest release' "$module"
rg -q 'restoring previous generation' "$module"
rg -q 'preserving promotion recovery state' "$module"
rg -q 'sleep 30' "$module"
rg -q 'sleep 1' "$module"
rg -q 'maintenance_drained' "$module"
test "$(rg -c 'tool-update.lock' "$module")" -ge 3
rg -q 'touch .*tool-update.lock' "$module"
if rg -q 'install .*tool-update.lock' "$module"; then
  printf 'shared update lock inode is replaced during setup\n' >&2
  exit 1
fi
if rg -n 'openchamberCompatibility|openchamberWebPackage|openCodePackage|manual-canary-required' "$module"; then
  printf 'static OpenChamber/OpenCode version ownership found\n' >&2
  exit 1
fi
rg -q 'OPENCODE_EXPERIMENTAL_NATIVE_LLM=1' "$module"
rg -q 'exec opencode serve --hostname 127\.0\.0\.1 --port 4096' "$module"
rg -q 'export OPENCODE_SKIP_START=true' "$module"
rg -q 'export OPENCODE_PORT=4096' "$module"
rg -q 'http://127\.0\.0\.1:4096/global/health' "$module"
rg -q 'Slice=openchamber-runtime\.slice' "$module"
rg -q 'MemoryMax=40G' "$module"
rg -q 'systemctl restart opencode\.service' "$module"
rg -q 'systemctl restart openchamber-web\.service' "$module"
rg -q '/api/session-activity' "$module"
rg -q 'openchamber-retry-guard' "$module"
rg -q 'openchamber-reconcile-interrupted-tools' "$module"
rg -q 'openchamber-snapshot-config' "$module"
rg -q 'openchamber-apply-config' "$module"
rg -q 'openchamber-container-health' "$module"
rg -q 'openchamber-cache-cleanup.timer' "$module"
rg -q 'managed_opencode_root=/workspace/ghostship-agent/config/opencode' "$module"
rg -q 'openchamber-tool-maintenance bootstrap' "$module"
rg -q 'updates are staged automatically and promoted only while idle' "$module"
rg -q 'stdenv.cc.bintools.dynamicLinker' "$module"
if rg -q '\*-glibc-\*' "$module"; then
  printf 'OpenCode wrapper still discovers an arbitrary glibc loader\n' >&2
  exit 1
fi

nix-instantiate --parse "$module" >/dev/null
nix-instantiate --parse "$repo_root/modules/self-hosted/openchamber-options.nix" >/dev/null

image_drv="$(nix eval --raw \
  "$repo_root#nixosConfigurations.chill-penguin.config.virtualisation.oci-containers.containers.openchamber.imageFile.drvPath")"
for script_name in openchamber-tool-maintenance openchamber-container-setup openchamber-runtime-metadata openchamber-managed-opencode-idle; do
  script_drv="$(nix-store -q --requisites "$image_drv" | rg "/[^/]*-$script_name\\.drv$" | head -n1)"
  test -n "$script_drv"
  script_source="$(nix derivation show "$script_drv" | jq -r 'to_entries[0].value.env.text')"
  printf '%s\n' "$script_source" | bash -n
  if [ "$script_name" = openchamber-tool-maintenance ]; then
    for mode in validate-candidate bootstrap-candidate bootstrap; do
      condition="$(printf '%s\n' "$script_source" | sed -n "s/^[[:space:]]*if \(\[.*= $mode \]\); then$/\1/p" | head -n1)"
      if [ -z "$condition" ]; then
        printf 'Missing generated mode guard: %s\n' "$mode" >&2
        printf '%s\n' "$script_source" | rg 'validate-candidate|bootstrap-candidate| = bootstrap' >&2
        exit 1
      fi
      bash -c 'set -- "$1"; eval "$2"' mode-check "$mode" "$condition"
    done
  fi
done

restart_drv="$(nix-store -q --requisites "$image_drv" \
  | rg '/[^/]*-openchamber-tool-update-restart\.drv$' | head -n1)"
test -n "$restart_drv"
bash "$repo_root/tests/openchamber-update-state-machine.sh" \
  "$module" \
  <(nix derivation show "$restart_drv" | jq -r 'to_entries[0].value.env.text')

system_drv="$(nix eval --raw \
  "$repo_root#nixosConfigurations.chill-penguin.config.system.build.toplevel.drvPath")"
host_drv="$(nix-store -q --requisites "$system_drv" \
  | rg '/[^/]*-openchamber-deploy-when-idle\.drv$' | head -n1)"
test -n "$host_drv"
bash "$repo_root/tests/openchamber-host-deploy-state-machine.sh" \
  <(nix derivation show "$host_drv" | jq -r 'to_entries[0].value.env.text')
