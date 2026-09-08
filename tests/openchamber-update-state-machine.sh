#!/usr/bin/env bash
set -Eeuo pipefail
trap 'printf "OpenChamber test failed at %s:%s: %s\n" "$0" "$LINENO" "$BASH_COMMAND" >&2' ERR

module="$1"
restart_script="$2"
restart_source="$(cat "$restart_script")"
fixture_root="$(mktemp -d -t openchamber-update-state.XXXXXX)"
fixture_parent="${TMPDIR:-/tmp}"
fixture_parent="${fixture_parent%/}"
case "$fixture_root" in
  "$fixture_parent"/openchamber-update-state.*) ;;
  *) exit 1 ;;
esac
trap 'rm -rf -- "$fixture_root"' EXIT INT TERM

# Execute the exact offline-candidate activation body from the Nix source with
# a registry stub that always fails. This proves first migration consumes the
# immutable prestage rather than returning to npm after the old service stops.
bootstrap_body="$(sed -n '/bootstrap-candidate \]; then$/,/^    fi$/p' "$module" \
  | sed '1d;$d;s/^    //')"
test -n "$bootstrap_body"

extract_function() {
  name="$1"
  sed -n "/^    $name() {\$/,/^    }\$/p" "$module" \
    | sed 's/^    //'
}

rewrite_validation_paths() {
  sed \
    -e 's#\${pkgs.coreutils}/bin/timeout#timeout#g' \
    -e 's#\${pkgs.bubblewrap}/bin/bwrap#bwrap#g' \
    -e 's#\${pkgs.bash}/bin/bash#bash#g'
}

openchamberPath=
harness_revision="$(sed -n 's/^  openchamberHarnessRevision = "\([^"]*\)";$/\1/p' "$module")"
test -n "$harness_revision"
openchamberHarnessRevision="$harness_revision"
for command_name in bash python3 node curl jq ip sleep seq; do
  command_dir="$(dirname "$(readlink -f "$(command -v "$command_name")")")"
  case ":$openchamberPath:" in
    *":$command_dir:"*) ;;
    *) openchamberPath="${openchamberPath:+$openchamberPath:}$command_dir" ;;
  esac
done
eval "$(extract_function package_version)"
eval "$(extract_function sandbox_validate_clis | rewrite_validation_paths)"
eval "$(extract_function sandbox_validate_server | rewrite_validation_paths)"
eval "$(extract_function validate_generation)"
sandbox_validate_scheduler() { :; }

tools_root="$fixture_root/tools"
generations_dir="$tools_root/generations"
update_state="$fixture_root/state"
candidate_file="$update_state/candidate.tsv"
release_id=openchamber-9.9.9--opencode-8.8.8
candidate="$generations_dir/$release_id"
mkdir -p "$candidate/bin" "$update_state" "$fixture_root/shims"
mkdir -p \
  "$candidate/lib/node_modules/@openchamber/web/server/lib/opencode" \
  "$candidate/lib/node_modules/@openchamber/web/server/lib/session-goal" \
  "$candidate/lib/node_modules/@openchamber/web/server/lib/scheduled-tasks" \
  "$candidate/lib/node_modules/@openchamber/web/server/lib/terminal" \
  "$candidate/lib/node_modules/@openchamber/web/bin/lib" \
  "$candidate/lib/node_modules/opencode-linux-x64"
printf '{"version":"9.9.9"}\n' \
  > "$candidate/lib/node_modules/@openchamber/web/package.json"
printf '{"version":"8.8.8"}\n' \
  > "$candidate/lib/node_modules/opencode-linux-x64/package.json"
printf '%s\n' "$harness_revision" > "$candidate/.openchamber-harness-revision"
for javascript in \
  "$candidate/lib/node_modules/@openchamber/web/server/index.js" \
  "$candidate/lib/node_modules/@openchamber/web/server/lib/opencode/openchamber-routes.js" \
  "$candidate/lib/node_modules/@openchamber/web/server/lib/opencode/routes.js" \
  "$candidate/lib/node_modules/@openchamber/web/server/lib/opencode/proxy.js" \
  "$candidate/lib/node_modules/@openchamber/web/server/lib/session-goal/runtime.js" \
  "$candidate/lib/node_modules/@openchamber/web/server/lib/scheduled-tasks/runtime.js" \
  "$candidate/lib/node_modules/@openchamber/web/server/lib/terminal/runtime.js" \
  "$candidate/lib/node_modules/@openchamber/web/bin/lib/commands-update.js"; do
  printf 'export {};\n' > "$javascript"
done
cat > "$candidate/bin/openchamber" <<'EOF'
#!/usr/bin/env bash
set -eu
if [ "${1:-}" = --version ]; then
  printf '9.9.9\n'
  exit 0
fi
if [ "${1:-}" = serve ]; then
  exec python3 -c '
import http.server
import json
import os

class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        gate = os.environ.get("OPENCHAMBER_MAINTENANCE_GATE", "")
        if gate and os.path.exists(gate) and self.headers.get("Upgrade"):
            self.send_response(503)
            self.end_headers()
            return
        if self.path == "/api/session-activity":
            payload = {}
        elif self.path == "/api/opencode/health":
            payload = {"healthy": True}
        elif self.path == "/api/openchamber/maintenance-drain":
            payload = {
                "inFlightMutations": 0,
                "activeTerminalSessions": 0,
                "activeOpenCodeSessions": 0,
                "activeScheduledTasks": 0,
                "activeGoalWork": 0,
                "observerPaused": bool(gate and os.path.exists(gate)),
                "schedulerPaused": bool(gate and os.path.exists(gate)),
            }
        else:
            self.send_response(404)
            self.end_headers()
            return
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        gate = os.environ.get("OPENCHAMBER_MAINTENANCE_GATE", "")
        self.send_response(503 if gate and os.path.exists(gate) else 404)
        self.end_headers()

    def log_message(self, *_args):
        pass

http.server.ThreadingHTTPServer(("127.0.0.1", 33119), Handler).serve_forever()
'
fi
exit 2
EOF
cat > "$candidate/bin/opencode" <<'EOF'
#!/usr/bin/env bash
set -eu
case "${1:-}" in
  --version) printf '8.8.8\n' ;;
  debug) test "${2:-}" = config; printf '{}\n' ;;
  *) exit 2 ;;
esac
EOF
chmod 0755 "$candidate/bin/openchamber" "$candidate/bin/opencode"
printf '%s\t9.9.9\t8.8.8\t%s\n' "$candidate" "$release_id" > "$candidate_file"

(
  platform_package=opencode-linux-x64
  npm() {
    printf 'offline bootstrap unexpectedly called npm\n' >&2
    return 99
  }
  install_user_shims() {
    : > "$fixture_root/shims/installed"
  }
  log_info() { :; }
  eval "$bootstrap_body"
)
test "$(readlink -f "$tools_root/active")" = "$candidate"
test -f "$fixture_root/shims/installed"
test ! -e "$candidate_file"

# Execute the generated interrupted-promotion branch twice. Failed health must
# retain the transaction, candidate, and gate; successful recovery may clear
# them and latch the failed candidate release.
recovery_block="$(printf '%s\n' "$restart_source" \
  | sed -n '/^if \[ -f "$transaction_file" \]; then$/,/^fi$/p' \
  | sed -E 's#/nix/store/[^ ]+-su-exec-[^ ]+/bin/su-exec openchamber:openchamber ##g')"
test -n "$recovery_block"

run_recovery_fixture() {
  expected_health="$1"
  case_root="$fixture_root/recovery-$expected_health"
  tools_root="$case_root/tools"
  old_generation="$tools_root/generations/old"
  candidate_generation="$tools_root/generations/candidate"
  candidate_file="$case_root/candidate.tsv"
  transaction_file="$case_root/promotion.tsv"
  gate_file="$case_root/admission.lock"
  failed_file="$case_root/failed-release"
  mkdir -p "$old_generation/bin" "$candidate_generation/bin"
  ln -s "$candidate_generation" "$tools_root/active"
  : > "$candidate_file"
  : > "$gate_file"
  printf '%s\t%s\trelease-under-test\n' \
    "$old_generation" "$candidate_generation" > "$transaction_file"
  systemctl() { return 0; }
  sleep() { :; }
  maintenance_drained() { return 0; }
  is_openchamber_idle() { return 0; }
  managed_opencode_connections_drained() { return 0; }
  managed_opencode_idle() { return 0; }
  managed_opencode_quiesced_or_absent() { return 0; }
  arm_opencode_network_gate() {
    printf 'arm %s\n' "$*" >> "$case_root/events"
    opencode_gate_armed=1
    return 0
  }
  clear_opencode_network_gate() {
    opencode_gate_armed=0
    return 0
  }
  gate_armed=0
  opencode_gate_armed=0
  wait_runtime_healthy() { test "$expected_health" = healthy; }
  log_info() { :; }
  audit_restart() { :; }
  set +e
  (
    eval "$recovery_block"
  )
  result=$?
  set -e
  test "$result" -eq 1
  grep -q '^arm allow-absent$' "$case_root/events"
  test "$(readlink -f "$tools_root/active")" = "$old_generation"
  if [ "$expected_health" = healthy ]; then
    test ! -e "$transaction_file"
    test ! -e "$candidate_file"
    test ! -e "$gate_file"
    test "$(cat "$failed_file")" = release-under-test
  else
    test -e "$transaction_file"
    test -e "$candidate_file"
    test -e "$gate_file"
    test ! -e "$failed_file"
  fi
}

run_recovery_fixture unhealthy
run_recovery_fixture healthy

health_recovery_block="$(printf '%s\n' "$restart_source" | sed -n '
  /^if \[ -f "\$health_restart_file" \] && \[ ! -f "\$candidate_file" \]; then$/,/^fi$/p
')"
test -n "$health_recovery_block"

run_health_recovery_fixture() (
  expected_health="$1"
  case_root="$fixture_root/health-$expected_health"
  mkdir -p "$case_root"
  health_restart_file="$case_root/health-restart.pending"
  candidate_file="$case_root/candidate.tsv"
  gate_file="$case_root/admission.lock"
  event_log="$case_root/events"
  : > "$health_restart_file"
  : > "$gate_file"
  restart_ok=1
  gate_armed=1
  log_info() { printf 'log %s\n' "$1" >> "$event_log"; }
  systemctl() { printf 'systemctl %s\n' "$*" >> "$event_log"; }
  clear_opencode_network_gate() { printf 'clear-network-gate\n' >> "$event_log"; }
  wait_runtime_healthy() { [ "$expected_health" = healthy ]; }
  audit_restart() { printf 'audit %s %s\n' "$1" "$2" >> "$event_log"; }

  set +e
  (
    eval "$health_recovery_block"
  )
  result=$?
  set -e
  if [ "$expected_health" = healthy ]; then
    test "$result" -eq 0
    test ! -e "$health_restart_file"
    test ! -e "$gate_file"
    grep -q '^audit health-recover current$' "$event_log"
  else
    test "$result" -eq 1
    test -e "$health_restart_file"
    grep -q '^audit health-recover-pending current$' "$event_log"
  fi
  grep -q '^systemctl restart openchamber-web.service$' "$event_log"
)

run_health_recovery_fixture unhealthy
run_health_recovery_fixture healthy
