"""Manual isolated cross-generation proof; all host state is disposable.

Requires the caller to supply a trusted legacy executor and its fixture harness.
Run as an unprivileged user with user namespaces available. External services,
acceptance records and a server restart are simulated by fixture stubs.
"""
from pathlib import Path
import argparse
import tempfile, subprocess, os, hashlib, signal, shutil
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--legacy-executor', type=Path, required=True)
parser.add_argument('--legacy-fixture', type=Path, required=True)
parser.add_argument('--expected-sha256', required=True)
parser.add_argument('--legacy-generation', type=int, required=True)
args = parser.parse_args()
if args.legacy_generation <= 0:
 raise SystemExit('legacy generation must be positive')
repo=Path(__file__).resolve().parents[1]
old=args.legacy_executor.read_bytes()
if hashlib.sha256(old).hexdigest() != args.expected_sha256:
 raise SystemExit('legacy executor SHA-256 mismatch')
head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()
subprocess.run(['git','merge-base','--is-ancestor','4aa7fe283169ce61f9ffb91adadb9e457776b316',head],cwd=repo,check=True)
with tempfile.TemporaryDirectory(prefix='gs-cross-gen-') as tmp:
 d=Path(tmp); (d/'old.sh').write_bytes(old)
 for name in ['release-window.sh','window-intent.sh','window-bootstrap.sh','activate-deployment.sh']:
  (d/('fixture-activate-writer' if name == 'activate-deployment.sh' else 'fixture-'+name.removesuffix('.sh'))).write_bytes(subprocess.check_output(['git','show',head+':packages/t3code/'+name],cwd=repo))
 test=subprocess.check_output(['git','show',head+':tests/test_t3code_release_window.sh'],cwd=repo,text=True)
 for name in ['systemctl','podman','systemd-run']:
  body=test.split('cat > "$tmp/bin/'+name+'" <<\'SH\'\n',1)[1].split('\nSH\n',1)[0]
  f=d/name; f.write_text(body+'\n');f.chmod(0o755)
 source_text=args.legacy_fixture.read_text()
 if '# ---- the hybrid baseline' not in source_text:
  raise SystemExit('unsupported legacy fixture harness')
 source=source_text.split('# ---- the hybrid baseline')[0]
 extra=r'''
S="$PROOF_DIR/old.sh"; export GENERATION_OLD="$LEGACY_GENERATION"
cleanup_fixture() {
  local file pid world
  for file in "$ROOT"/*/window_pid "$ROOT"/*/holder-pid; do
    [[ -f $file ]] || continue
    read -r pid < "$file" || continue
    [[ $pid =~ ^[1-9][0-9]*$ ]] || continue
    world=$(dirname "$file")
    # Kill only a fixture holder whose open lock is the disposable lock.
    [[ /proc/$pid/fd/7 -ef $world/lock1 ]] || continue
    kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
  rm -rf "$ROOT"
}
trap cleanup_fixture EXIT
run_cross() {
  local mode=$1 rc
  mkworld "$mode"
  ln -sfn "system-$LEGACY_GENERATION-link" "$W/profile"; ln -sfn "$W/sysold" "$W/profile-$LEGACY_GENERATION-link"
  mkdir -p "$W/home/.local/state/t3code-tool-update" "$W/home/.local/state/t3code-shared-agents" "$W/home/.local/share/t3code-tools/t3" "$W/tooling"
  touch "$W/home/.local/state/t3code-tool-update/tool-update.lock" "$W/home/.local/state/t3code-shared-agents/refresh.lock" "$W/home/.local/share/t3code-tools/t3/update.lock"
  echo active > "$W/recovery_state"; go_file
  unset WINDOW_UNIT SERVER_PID
  REAL_WINDOW=1 scenario "legacy-start-$mode" 0 'window held' cmd_window_start
  [[ -f $W/window_pid && -f $W/hold ]] || exit 11
  kill "$(cat "$W/window_pid")" || exit 12
  for _ in {1..100}; do flock -n "$W/lock1" true && flock -n "$W/lock2" true && break; sleep .02; done
  # Simulated elapsed time and prior legacy switch evidence, not host values.
  printf '%s\n' "$(( $(date +%s)-100 ))" > "$W/dir/window.opened"
  printf '%s\n' "$(( $(date +%s)-1 ))" > "$W/dir/window.until"
  : > "$W/dir/complete.lock"; : > "$W/dir/complete.started"
  rm -f "$W/recovery-inactive" "$W/state/receipts/$OLD_DEP.json"
  printf '%s\n' "$W/newroot" > "$W/config"
  export FIXTURE="$W" WINDOW_CONFIG="$W/config" WINDOW_INTENT_HELPER="$PROOF_DIR/fixture-window-intent" WINDOW_BOOTSTRAP="$PROOF_DIR/fixture-window-bootstrap" \
    STATE_DIR="$W/state" SYSTEMCTL_BIN="$PROOF_DIR/systemctl" PODMAN_BIN="$PROOF_DIR/podman" PODMAN_TARGET=fixture WINDOW_UNIT=window \
    HOLD_FILE="$W/hold" LOCK_CANDIDATE="$W/lock1" LOCK_HARDENING="$W/lock2" PROFILE="$W/profile" SYSTEMD_RUN_BIN="$PROOF_DIR/systemd-run" WINDOW_SECONDS=100 \
    LEGACY_DIR="$W/dir" LEGACY_UNIT=legacy HOME_DIR="$W/home" EXPECTED_IMAGE="$IMAGE" EXPECTED_DEPLOYMENT="$NEW_DEP" \
    EXPECTED_AGENT_REVISION=fixture EXPECTED_TOOLING_PATH="$W/tooling" PROVIDER_SECRETS_FILE="$W/secrets/t3code.env" \
    CANDIDATE_HOME_TARGET=/home/fixture ACCEPTED_IMAGE_REF=fixture:accepted CURRENT_SYSTEM="$W/current" EXPECTED_SYSTEM="$W/sysnew" JQ_BIN="$(command -v jq)" \
    DEPLOYMENT_ID="$NEW_DEP" AGENT_REVISION=fixture TOOLING_PATH="$W/tooling"
  printf '%s\n' "$OLD_DEP" > "$STATE_DIR/applied"; printf '%s\n' "$NEW_DEP" > "$STATE_DIR/desired"
  hold_inode=$(stat -c %i "$HOLD_FILE")
  printf '%s PREINSTALL_ROOT: ' "$mode"; [[ ! -e $W/newroot ]] && echo absent || echo present
  output=$(bash "$PROOF_DIR/fixture-release-window" preflight --adopt-inhibit 2>&1); rc=$?; printf '%s PREFLIGHT rc=%s: %s\n' "$mode" "$rc" "$output"; [[ $rc == 0 && ! -e $W/newroot ]] || exit 13
  output=$(bash "$PROOF_DIR/fixture-release-window" start --adopt-inhibit "$mode" 2>&1); rc=$?; printf '%s START rc=%s: %s\n' "$mode" "$rc" "$output"; [[ $rc == 0 && $(stat -c %i "$HOLD_FILE") == "$hold_inode" ]] || exit 14
  output=$(bash "$PROOF_DIR/fixture-release-window" end-no-activation 2>&1); rc=$?; printf '%s NO_ACTIVATION rc=%s: %s\n' "$mode" "$rc" "$output"; [[ $rc == 1 ]] || exit 15
  # Real candidate activation hook under the tracked switch wrapper; the
  # NixOS/systemd side effects and candidate results are fixture stubs.
  if [[ $mode == before ]]; then
    printf '%s SWITCH: not attempted (pre-switch route UNKNOWN)\n' "$mode"
  else
    output=$(bash "$PROOF_DIR/fixture-release-window" switch -- bash -c 'bash "$1"; exit 4' _ "$PROOF_DIR/fixture-activate-writer" 2>&1); rc=$?
    printf '%s SWITCH rc=%s: %s\n' "$mode" "$rc" "$output"; [[ $rc == 4 ]] || exit 16
    [[ -n $(find "$W/newroot/$mode" -name 'effect-intent.activate.*' -print -quit) ]] || exit 17
    printf '%s ACTIVATION_INTENT: active-window\n' "$mode"
  fi
  mkdir -p "$STATE_DIR/attempts"
  if [[ $mode == restart ]]; then
    export SERVER_PID=9999
    ln -sfn "$W/sysnew" "$W/profile"; ln -sfn "$W/sysnew" "$W/current"
    printf '%s\n' "$NEW_DEP" > "$STATE_DIR/applied"
    jq -n --arg d "$NEW_DEP" --argjson n "$(date +%s%3N)" '{deployment_id:$d,started_at_ms:$n,exit_code:0}' > "$STATE_DIR/attempts/$NEW_DEP.json"
    inode=$(stat -Lc %i "$PROVIDER_SECRETS_FILE")
    jq -n --arg d "$NEW_DEP" --arg i "$IMAGE" --arg p "$EXPECTED_TOOLING_PATH" --arg s "$inode" '{deployment_id:$d,image_id:$i,candidate_name:"t3code-candidate-fixture",agent_revision:"fixture",agent_path:$p,provider_secret_inode:$s,live_before:{id:"fixture"},live_after:{id:"fixture"},checks:{app_ready:true,provider_turn:true,agent_cli:true,skills:true,desktop_transport:true}}' > "$STATE_DIR/receipts/$NEW_DEP.json"
    output=$(bash "$PROOF_DIR/fixture-release-window" post 2>&1); rc=$?; printf '%s POST rc=%s: %s\n' "$mode" "$rc" "$output"; [[ $rc == 0 ]] || exit 23
    output=$(bash "$PROOF_DIR/fixture-release-window" end-post "$mode" 2>&1); rc=$?; printf '%s END_POST rc=%s: %s\n' "$mode" "$rc" "$output"; [[ $rc == 0 && ! -e $HOLD_FILE ]] || exit 24
    printf '%s SERVER: fixture PID changed; exact synthetic receipt verified\n' "$mode"
    return
  elif [[ $mode == route || $mode == before ]]; then
    jq -n --arg d "$NEW_DEP" --argjson n "$(date +%s%3N)" '{deployment_id:$d,started_at_ms:$n,exit_code:77,outcome:"route_unknown"}' > "$STATE_DIR/attempts/$NEW_DEP.json"
  else
    jq -n --arg d "$NEW_DEP" --argjson n "$(date +%s%3N)" '{deployment_id:$d,started_at_ms:$n,exit_code:1}' > "$STATE_DIR/attempts/$NEW_DEP.json"
    printf '%s %064d\n' "$NEW_DEP" 6 > "$STATE_DIR/failed-candidate"
  fi
  output=$(bash "$PROOF_DIR/fixture-release-window" post 2>&1); rc=$?; printf '%s POST rc=%s: %s\n' "$mode" "$rc" "$output"; [[ $rc == 1 ]] || exit 18
  if [[ $mode == known ]]; then
    inode=$(stat -Lc %i "$PROVIDER_SECRETS_FILE")
    jq -n --arg d "$OLD_DEP" --arg i "$IMAGE" --arg p "$EXPECTED_TOOLING_PATH" --arg s "$inode" '{deployment_id:$d,image_id:$i,candidate_name:"t3code-candidate-fixture",agent_revision:"fixture",agent_path:$p,provider_secret_inode:$s,live_before:{id:"fixture"},live_after:{id:"fixture"},checks:{app_ready:true,provider_turn:true,agent_cli:true,skills:true,desktop_transport:true}}' > "$STATE_DIR/receipts/$OLD_DEP.json"
    output=$(bash "$PROOF_DIR/fixture-release-window" rollback "$mode" 2>&1); rc=$?; printf '%s ROLLBACK rc=%s: %s\n' "$mode" "$rc" "$output"; [[ $rc == 0 && ! -e $HOLD_FILE && -f $STATE_DIR/failed-candidate ]] || exit 25
    [[ $(cat "$STATE_DIR/applied") != "$(cat "$STATE_DIR/desired")" ]] || exit 26
    printf '%s STATE: serving receipt verified; desired/applied remain split; failed marker retained\n' "$mode"
    return
  fi
  if [[ $mode == stopped ]]; then
    touch "$W/container-stopped"
    rm -f "$STATE_DIR"/receipts/*.json
    output=$(bash "$PROOF_DIR/fixture-release-window" rollback "$mode" 2>&1); rc=$?
    printf '%s ROLLBACK_NO_RECEIPT rc=%s: %s\n' "$mode" "$rc" "$output"
    [[ $rc == 1 && -e $HOLD_FILE && -e $W/container-stopped ]] || exit 27
    inode=$(stat -Lc %i "$PROVIDER_SECRETS_FILE")
    jq -n --arg d "$OLD_DEP" --arg i "$IMAGE" --arg p "$EXPECTED_TOOLING_PATH" --arg s "$inode" '{deployment_id:$d,image_id:$i,candidate_name:"t3code-candidate-fixture",agent_revision:"fixture",agent_path:$p,provider_secret_inode:$s,live_before:{id:"fixture"},live_after:{id:"fixture"},checks:{app_ready:true,provider_turn:true,agent_cli:true,skills:true,desktop_transport:true}}' > "$STATE_DIR/receipts/$OLD_DEP.json"
    output=$(bash "$PROOF_DIR/fixture-release-window" rollback "$mode" 2>&1); rc=$?
    printf '%s ROLLBACK_RECOVER rc=%s: %s\n' "$mode" "$rc" "$output"
    [[ $rc == 0 && ! -e $HOLD_FILE && ! -e $W/container-stopped && -f $STATE_DIR/failed-candidate ]] || exit 28
    [[ $(cat "$STATE_DIR/applied") != "$(cat "$STATE_DIR/desired")" ]] || exit 29
    printf '%s RECOVERY: stopped container recovered from receipt; window released\n' "$mode"
    return
  fi
  output=$(bash "$PROOF_DIR/fixture-release-window" rollback 2>&1); rc=$?; printf '%s ROLLBACK rc=%s: %s\n' "$mode" "$rc" "$output"; [[ $rc == 1 ]] || exit 19
  output=$(bash "$PROOF_DIR/fixture-release-window" end-unknown 2>&1); rc=$?; printf '%s END_UNKNOWN rc=%s: %s\n' "$mode" "$rc" "$output"; [[ $rc == 77 && -f $HOLD_FILE && ! -e $W/newroot/active-window ]] || exit 20
  jq -e --arg expected "$([[ $mode == route || $mode == before ]] && echo route_unknown || echo candidate_failed)" '.state=="UNKNOWN" and .reason==$expected and .receipt=="absent" and .recovery_inhibit=="retained"' "$STATE_DIR/recovery-unknown.json" >/dev/null || exit 21
  if [[ $mode == failed ]]; then [[ -f $STATE_DIR/failed-candidate ]] || exit 22; printf '%s FAILED_MARKER: retained\n' "$mode"; fi
  printf '%s SERVING: unchanged; recovery inhibit retained\n' "$mode"
}
run_cross before
run_cross route
run_cross failed
run_cross known
run_cross stopped
run_cross restart
'''
 harness=d/'proof.sh';harness.write_text(source+'\n'+extra)
 unshare_bin = shutil.which('unshare')
 if not unshare_bin:
  for candidate in Path('/nix/store').glob('*util-linux*/bin/unshare'):
   if candidate.is_file() and os.access(candidate, os.X_OK):
    unshare_bin = str(candidate)
    break
 if not unshare_bin:
  raise SystemExit('unshare binary not found')
 path = os.environ['PATH']
 bin_dir = os.path.dirname(unshare_bin)
 if bin_dir not in path.split(':'): path = bin_dir + ':' + path
 env={'PATH':path,'HOME':str(d),'TMPDIR':str(d),'PROOF_DIR':str(d),'S':str(d/'old.sh'),'LEGACY_GENERATION':str(args.legacy_generation)}
 p=subprocess.Popen([unshare_bin,'-Ur','bash',str(harness)],env=env,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
 try:
  stdout,stderr=p.communicate(timeout=180)
 except subprocess.TimeoutExpired:
  os.killpg(p.pid,signal.SIGTERM)
  try:
   p.communicate(timeout=5)
  except subprocess.TimeoutExpired:
   os.killpg(p.pid,signal.SIGKILL)
   p.communicate()
  raise SystemExit('fixture timed out; disposable process group stopped')
 print('legacy sha256',hashlib.sha256(old).hexdigest());print('candidate commit',head,'base 4aa7fe283169ce61f9ffb91adadb9e457776b316');print('fixture exit',p.returncode);print(stdout);print(stderr)
 if p.returncode: raise SystemExit(p.returncode)
