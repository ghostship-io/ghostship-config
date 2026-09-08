#!/usr/bin/env bash
set -euo pipefail

host_source="$(cat "$1")"
fixture_root="$(mktemp -d -t openchamber-host-state.XXXXXX)"
fixture_parent="${TMPDIR:-/tmp}"
fixture_parent="${fixture_parent%/}"
case "$fixture_root" in
  "$fixture_parent"/openchamber-host-state.*) ;;
  *) exit 1 ;;
esac
trap 'rm -rf -- "$fixture_root"' EXIT INT TERM
mkdir -p "$fixture_root/control"

extract_function() {
  name="$1"
  printf '%s\n' "$host_source" | sed -n "/^$name() {\$/,/^}\$/p"
}

rewrite_host_paths() {
  sed -E \
    -e 's#/nix/store/[^ ]+-util-linux-[^ ]+/bin/flock#flock#g' \
    -e 's#/nix/store/[^ ]+-podman-[^ ]+/bin/podman#podman#g' \
    -e 's#/nix/store/[^ ]+-systemd-[^ ]+/bin/systemctl#systemctl#g' \
    -e 's#/nix/store/[^ ]+-coreutils-[^ ]+/bin/rm#rm#g' \
    -e "s#/srv/apps/openchamber/tool-update-control#$fixture_root/control#g"
}

imageName=localhost/ghostship-openchamber
imageTag=openchamber-runtime
eval "$(extract_function clear_host_opencode_network_gate | rewrite_host_paths)"
eval "$(extract_function clear_rollback_override | rewrite_host_paths)"
eval "$(extract_function clear_rollback_state | rewrite_host_paths)"
eval "$(extract_function persist_rollback_state | rewrite_host_paths)"
eval "$(extract_function disarm_host_gate | rewrite_host_paths)"
eval "$(extract_function arm_host_opencode_network_gate | rewrite_host_paths)"
eval "$(extract_function quiesce_active_container | rewrite_host_paths)"
eval "$(extract_function quiesce_failed_replacement | rewrite_host_paths)"
eval "$(extract_function stop_quiesced_container | rewrite_host_paths)"
eval "$(extract_function start_replacement_container | rewrite_host_paths)"
eval "$(extract_function restore_previous_container | rewrite_host_paths)"
eval "$(extract_function restore_previous_when_safe | rewrite_host_paths)"

desired=test-deployment
rollback_image_file="$fixture_root/rollback-image"
rollback_desired_file="$fixture_root/rollback-desired"
gate_file="$fixture_root/control/admission.lock"
promotion_file="$fixture_root/control/promotion.tsv"
host_gate_armed=0
host_opencode_gate_armed=0
event_log="$fixture_root/events"
drain_mode=ready
drain_calls=0
direct_calls=0
connection_drain_calls=0
systemctl_mode=success
systemctl_start_calls=0
flock_mode=success
opencode_mode=present
web_state=active

log_info() { printf 'log %s\n' "$1" >> "$event_log"; }
is_live_idle() { return 0; }
maintenance_drained() {
  drain_calls=$((drain_calls + 1))
  [ "$drain_mode" = ready ]
}
maintenance_supported() {
  drain_calls=$((drain_calls + 1))
  [ "$drain_mode" = ready ]
}
managed_opencode_probe() {
  printf 'managed-opencode-probe %s\n' "$*" >> "$event_log"
  case "${1:-}" in
    --print-port)
      [ "$opencode_mode" = present ] || return 1
      printf '4096\n'
      ;;
    --connections-drained) connection_drain_calls=$((connection_drain_calls + 1)) ;;
    *) direct_calls=$((direct_calls + 1)) ;;
  esac
}
managed_opencode_root_probe() {
  printf 'managed-opencode-root-probe %s\n' "$*" >> "$event_log"
  direct_calls=$((direct_calls + 1))
}
managed_opencode_process_present() { [ "$opencode_mode" = present ]; }
managed_opencode_quiesced_or_absent() {
  [ "$opencode_mode" = absent ] \
    || { managed_opencode_probe --connections-drained && managed_opencode_root_probe; }
}
podman() {
  printf 'podman %s\n' "$*" >> "$event_log"
  case "$*" in
    'inspect openchamber --format {{.Image}}')
      printf 'sha256:previous-image\n'
      ;;
    'inspect openchamber --format {{.State.Health.Status}}')
      printf 'healthy\n'
      ;;
    'exec openchamber systemctl show openchamber-web.service -p ActiveState --value')
      printf '%s\n' "$web_state"
      ;;
    *iptables*-C*)
      return 1
      ;;
  esac
  return 0
}
flock() {
  printf 'flock %s\n' "$*" >> "$event_log"
  if [ "${1:-}" = -n ] && [ "$flock_mode" = failure ]; then
    return 1
  fi
  return 0
}
sleep() { :; }
mark_failed() { : > "$fixture_root/failed"; }
systemctl() {
  printf 'systemctl %s\n' "$*" >> "$event_log"
  if [ "$systemctl_mode" = start-once-failure ] \
    && [ "$1" = start ] \
    && [ "$2" = podman-openchamber.service ]; then
    systemctl_start_calls=$((systemctl_start_calls + 1))
    [ "$systemctl_start_calls" -gt 1 ]
    return
  fi
  if [ "$systemctl_mode" = start-once-failure ]; then
    return 0
  fi
  [ "$systemctl_mode" = success ]
}

flock_mode=failure
if quiesce_active_container; then
  printf 'lock-losing host updater unexpectedly passed quiescing\n' >&2
  exit 1
fi
disarm_host_gate
if grep -q 'iptables' "$event_log"; then
  printf 'lock-losing host updater removed another updater gate\n' >&2
  exit 1
fi
flock_mode=success
: > "$event_log"

: > "$promotion_file"
: > "$gate_file"
if quiesce_active_container; then
  printf 'host updater unexpectedly overlapped tool recovery\n' >&2
  exit 1
fi
disarm_host_gate
test -e "$gate_file"
grep -q 'tool-promotion-recovery' "$event_log"
if grep -q 'iptables' "$event_log"; then
  printf 'host updater changed a tool recovery network gate\n' >&2
  exit 1
fi
rm -f "$promotion_file" "$gate_file"
: > "$event_log"

drain_mode=legacy
if quiesce_active_container; then
  printf 'legacy runtime unexpectedly passed host quiescing\n' >&2
  exit 1
fi
grep -q 'legacy-runtime-needs-controlled-stop' "$event_log"
test ! -e "$gate_file"

: > "$event_log"
drain_mode=ready
drain_calls=0
direct_calls=0
connection_drain_calls=0
quiesce_active_container
test "$host_gate_armed" -eq 1
test "$host_opencode_gate_armed" -eq 1
test -e "$gate_file"
test "$drain_calls" -eq 3
test "$direct_calls" -eq 2
test "$connection_drain_calls" -eq 1
grep -q 'iptables -I OUTPUT 1 -j OPENCHAMBER_OPENCODE_GATE' "$event_log"

container_was_active=1
systemctl_mode=success
stop_quiesced_container
test "$(cat "$rollback_image_file")" = sha256:previous-image
test "$(cat "$rollback_desired_file")" = "$desired"
test "$host_gate_armed" -eq 0
test "$host_opencode_gate_armed" -eq 0
grep -q '^systemctl stop podman-openchamber.service$' "$event_log"
grep -q '^flock -u 9$' "$event_log"
start_replacement_container
grep -q '^systemctl start podman-openchamber.service$' "$event_log"

: > "$event_log"
previous_image=sha256:previous-image
container_was_active=0
rollback_override_dir="$fixture_root/rollback-unit"
rollback_override="$rollback_override_dir/rollback-image.conf"
systemctl_mode=start-once-failure
systemctl_start_calls=0
if start_replacement_container; then
  printf 'failed replacement start unexpectedly passed\n' >&2
  exit 1
fi
restore_previous_container
grep -q '^podman tag sha256:previous-image localhost/ghostship-openchamber:openchamber-runtime$' "$event_log"
test "$(grep -c '^systemctl start podman-openchamber.service$' "$event_log")" -eq 2
grep -q '^ExecStartPre=$' "$rollback_override"
grep -q '^ExecStartPre=-podman rm -f openchamber$' "$rollback_override"
systemctl_mode=success
clear_rollback_override
test ! -e "$rollback_override"

: > "$event_log"
web_state=failed
opencode_mode=absent
previous_image=sha256:previous-image
container_was_active=1
systemctl_mode=success
restore_previous_when_safe
grep -q 'failed-replacement-gated' "$event_log"
stop_line=$(grep -n '^systemctl stop podman-openchamber.service$' "$event_log" | head -1 | cut -d: -f1)
unlock_line=$(grep -n '^flock -u 9$' "$event_log" | head -1 | cut -d: -f1)
start_line=$(grep -n '^systemctl start podman-openchamber.service$' "$event_log" | head -1 | cut -d: -f1)
test "$stop_line" -lt "$unlock_line"
test "$unlock_line" -lt "$start_line"
grep -q 'managed-opencode-probe --print-port' "$event_log"
grep -q 'iptables -I OUTPUT 1 -j OPENCHAMBER_OPENCODE_GATE' "$event_log"
grep -q '^podman tag sha256:previous-image localhost/ghostship-openchamber:openchamber-runtime$' "$event_log"
opencode_mode=present
web_state=active

host_gate_armed=1
host_opencode_gate_armed=1
container_was_active=1
: > "$gate_file"
systemctl_mode=failure
if stop_quiesced_container; then
  printf 'failed container stop unexpectedly passed\n' >&2
  exit 1
fi
test ! -e "$rollback_image_file"
test ! -e "$rollback_desired_file"
test "$host_gate_armed" -eq 1
disarm_host_gate
test ! -e "$gate_file"
test "$host_opencode_gate_armed" -eq 0
grep -q 'iptables -D OUTPUT -j OPENCHAMBER_OPENCODE_GATE' "$event_log"
