#!/usr/bin/env bash
# end-unknown must accept the live window's shape: start succeeded, the switch
# ran, and candidate acceptance then failed as unknown. Each scenario gets its
# own root so no marker state leaks between them.
set -euo pipefail
repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
JQ=$(command -v jq)

setup() {
  local root=$1 desired=$2
  mkdir -p "$root/evidence/win" "$root/run/t3code-tool-update" "$root/state/attempts" "$root/home" "$root/bin" \
    "$root/home/.local/state/t3code-tool-update" "$root/home/.local/state/t3code-shared-agents" \
    "$root/home/.local/share/t3code-tools/t3" "$root/system"
  : > "$root/evidence/window.lock"
  : > "$root/evidence/win/complete.lock"
  : > "$root/evidence/win/complete.started"
  printf '%s\n' win > "$root/evidence/active-window"
  : > "$root/state/deploy.lock"
  : > "$root/candidate.lock"; : > "$root/hardening.lock"
  : > "$root/home/.local/state/t3code-tool-update/tool-update.lock"
  : > "$root/home/.local/state/t3code-shared-agents/refresh.lock"
  : > "$root/home/.local/share/t3code-tools/t3/update.lock"
  : > "$root/hold"
  printf '%s\n' "$root/evidence" > "$root/config"
  printf 'fixture-secret\n' > "$root/secrets"
  printf '%s\n' "$desired" > "$root/state/desired"
  printf '%s\n' "$desired" > "$root/state/applied"
  ln -sfn "$root/system" "$root/profile"
  mkdir -p "$root/current-system"

  # The holder expired but left valid evidence, which is what the live window has.
  printf '%s\n' 2 > "$root/evidence/win/holder.ready"
  printf '%064d sha256:%s started\n' 1 "$(printf '%064d' 2)" > "$root/evidence/win/serving.before"
  printf '4242 99\n' >> "$root/evidence/win/serving.before"
  {
    printf 'started=2026-10-31T04:02:32Z start_ms=%s acquired_by=%s\n' "$(date +%s%3N)" 1
    printf 'holder_pid=%s held_at=2026-10-31T04:02:32Z\n' 2
    cat "$root/evidence/win/serving.before"
  } > "$root/evidence/win/window.start"

  cat > "$root/bin/systemctl" <<SH
#!/usr/bin/env bash
if [[ \$1 == start && \$2 == podman-t3code.service ]]; then rm -f "$root/container-stopped"; exit 0; fi
if [[ \$1 == show ]]; then
  if [[ \$2 == ghostship-t3code-deploy.service && \$3 == -p && \$4 == Result ]]; then echo success; exit; fi
  case \$2 in
    t3code-recovery.service) echo active ;;
    podman-t3code.service) [[ -e $root/container-stopped ]] && echo inactive || echo active ;;
    *) echo inactive ;;
  esac
  exit
fi
exit 0
SH
  cat > "$root/bin/podman" <<SH
#!/usr/bin/env bash
if [[ \$1 == exec && \$3 == sh && \${4:-} == -c ]]; then
  # Run the script the tool actually passes, with the container path remapped
  # onto the fixture root. Reimplementing the check here would test the stub
  # rather than the tool.
  sc=\$5; shift 6
  remapped=()
  for a in "\$@"; do remapped+=("\${a//\/run\/t3code-tool-update/$root\/run\/t3code-tool-update}"); done
  exec sh -c "\$sc" _ "\${remapped[@]}"
fi
if [[ \$1 == exec && \$3 == systemctl ]]; then
  case "\$*" in
    *MainPID*) echo 4242; exit ;;
    *ActiveEnterTimestampMonotonic*) echo 99; exit ;;
  esac
fi
if [[ \$1 == image && \$2 == inspect ]]; then printf 'sha256:%s\n' "\$(printf '%064d' 2)"; exit 0; fi
case "\$1 \$3 \${4:-}" in
  'inspect --format {{.State.Running}}') [[ -e $root/container-stopped ]] && echo false || echo true ;;
  'inspect --format {{.Id}} {{.Image}} {{.State.StartedAt}}') printf '%064d sha256:%s started\n' 1 "$(printf '%064d' 2)" ;;
  'inspect --format {{.Image}}') printf 'sha256:%s\n' "$(printf '%064d' 2)" ;;
  'inspect --format {{.State.Health.Status}}') echo healthy ;;
  'exec /usr/share/t3code/served-identity.sh ') printf '{"served":{"source":"persisted","version":"1.0.0","digest":""},"baked":{"version":"0.1.5","digest":"%064d"}}\n' 0 ;;
  'exec readlink -f')
    case "\$*" in
      *ghostship-t3-tools/current*) printf '%s\n' "$root/tooling" ;;
      *t3code-tools/t3/current*) printf '%s\n' "$root/home/.local/share/t3code-tools/t3/releases/1.0.0" ;;
      *) exit 1 ;;
    esac ;;
  'exec cat '*) printf '{"revision":"fixture"}\n' ;;
  'exec stat -Lc') stat -Lc '%i' "$root/secrets" ;;
  'exec sha256sum '*) sha256sum "$root/secrets" ;;
  'exec systemctl is-active'|'exec curl -fsS') exit 0 ;;
  *) exit 1 ;;
esac
SH
  printf '#!/usr/bin/env bash\nexit 0\n' > "$root/bin/systemd-run"
  printf '#!/usr/bin/env bash\nshift\nexec "$@"\n' > "$root/bin/su-exec"
  chmod +x "$root/bin/"*
}

run_cmd() {
  local root=$1; shift
  env FIXTURE="$root" \
  WINDOW_CONFIG="$root/config" WINDOW_INTENT_HELPER="$repo/packages/t3code/window-intent.sh" \
  WINDOW_BOOTSTRAP="$repo/packages/t3code/window-bootstrap.sh" \
  STATE_DIR="$root/state" SYSTEMCTL_BIN="$root/bin/systemctl" PODMAN_BIN="$root/bin/podman" \
  PODMAN_TARGET=fixture WINDOW_UNIT=window HOLD_FILE="$root/hold" \
  LOCK_CANDIDATE="$root/candidate.lock" LOCK_HARDENING="$root/hardening.lock" \
  PROFILE="$root/profile" SYSTEMD_RUN_BIN="$root/bin/systemd-run" WINDOW_SECONDS=100 \
  WINDOW_HOLDER_BIN="$repo/packages/t3code/window-holder.sh" \
  HOME_DIR="$root/home" JQ_BIN="$JQ" CANDIDATE_HOME_TARGET=/home/fixture \
  ACCEPTED_IMAGE_REF=fixture:accepted PROVIDER_SECRETS_FILE="$root/secrets" \
  CURRENT_SYSTEM="$root/current-system" EXPECTED_SYSTEM="$root/system" \
  EXPECTED_IMAGE="$(printf '%064d' 2)" EXPECTED_DEPLOYMENT="$(printf '%064d' 3)" \
  EXPECTED_AGENT_REVISION=fixture EXPECTED_TOOLING_PATH="$root/tooling" \
  "$@"
}

attempt() {
  printf '{"deployment_id":"%s","exit_code":77,"outcome":"%s","started_at_ms":%s}\n' \
    "$2" "$3" "$4" > "$1/state/attempts/$2.json"
}

# A receipt matching what the stubs report for agent revision, tooling path and
# secret inode, so known_good_receipt can succeed without inventing one.
write_receipt() {
  local root=$1 desired=$2 image inode
  image=$(printf '%064d' 2)
  inode=$(stat -Lc %i "$root/secrets")
  mkdir -p "$root/state/receipts"
  printf '{"deployment_id":"%s","image_id":"%s","candidate_name":"t3code-candidate-fixture","agent_revision":"fixture","agent_path":"%s","provider_secret_inode":"%s","live_before":{"id":"fixture"},"live_after":{"id":"fixture"},"checks":{"app_ready":true,"provider_turn":true,"agent_cli":true,"skills":true,"desktop_transport":true}}\n' \
    "$desired" "$image" "$root/tooling" "$inode" > "$root/state/receipts/$desired.json"
}

scenario_a() {
# A: the live shape — switch ran, acceptance_unknown, deferral markers present.
a=$(mktemp -d); trap 'rm -rf "$a"' EXIT
desired=$(printf '%064d' 11)
setup "$a" "$desired"
attempt "$a" "$desired" acceptance_unknown "$(date +%s%3N)"
: > "$a/run/t3code-tool-update/update-deferred.pending"
: > "$a/home/.local/state/t3code-tool-update/update-deferred.pending"
set +e
run_cmd "$a" bash "$repo/packages/t3code/release-window.sh" end-unknown > "$a/out.log" 2>&1
a_rc=$?
set -e
[[ $a_rc == 77 ]] || { echo "A: rc=$a_rc" >&2; cat "$a/out.log" >&2; exit 1; }
"$JQ" -e '.reason == "acceptance_unknown" and .recovery_inhibit == "retained"' "$a/state/recovery-unknown.json" >/dev/null
[[ -e $a/hold ]] || { echo 'A: inhibit cleared' >&2; exit 1; }
[[ ! -e $a/evidence/active-window ]] || { echo 'A: window not released' >&2; exit 1; }
set +e
run_cmd "$a" bash "$repo/packages/t3code/release-window.sh" end-unknown > "$a/retry.log" 2>&1
retry_rc=$?
set -e
[[ $retry_rc == 77 ]] || { echo "A: released retry rc=$retry_rc" >&2; tail -3 "$a/retry.log" >&2; exit 1; }
rm -rf "$a"
}

scenario_b() {
# B: a real queued container restart still refuses.
b=$(mktemp -d); trap 'rm -rf "$b"' EXIT
desired=$(printf '%064d' 12)
setup "$b" "$desired"
attempt "$b" "$desired" acceptance_unknown "$(date +%s%3N)"
: > "$b/run/t3code-tool-update/update-deferred.pending"
: > "$b/run/t3code-tool-update/restart.pending"
if run_cmd "$b" bash "$repo/packages/t3code/release-window.sh" end-unknown > "$b/out.log" 2>&1; then
  echo 'B: accepted a queued container restart' >&2; exit 1
fi
grep -q 'container maintenance state unknown or pending' "$b/out.log" || { echo 'B: unexpected outcome:' >&2; cat "$b/out.log" >&2; exit 1; }
[[ -e $b/evidence/active-window && -e $b/hold ]] || { echo 'B: window changed' >&2; exit 1; }
rm -rf "$b"
}

scenario_c() {
# C: a stale attempt is not accepted as acceptance_unknown evidence. The window
# still ends, correctly, through the switch marker it really has.
c=$(mktemp -d); trap 'rm -rf "$c"' EXIT
desired=$(printf '%064d' 13)
setup "$c" "$desired"
attempt "$c" "$desired" acceptance_unknown 1
set +e
run_cmd "$c" bash "$repo/packages/t3code/release-window.sh" end-unknown > "$c/out.log" 2>&1
c_rc=$?
set -e
[[ $c_rc == 77 ]] || { echo "C: rc=$c_rc" >&2; cat "$c/out.log" >&2; exit 1; }
"$JQ" -e '.reason == "switch_unknown"' "$c/state/recovery-unknown.json" >/dev/null \
  || { echo 'C: a stale attempt was taken as acceptance_unknown' >&2; exit 1; }
rm -rf "$c"
}

scenario_d() {
# D: an attempt naming another deployment is not accepted either; the window
# still ends through its switch marker.
d=$(mktemp -d); trap 'rm -rf "$d"' EXIT
desired=$(printf '%064d' 14)
setup "$d" "$desired"
printf '{"deployment_id":"%s","exit_code":77,"outcome":"acceptance_unknown","started_at_ms":%s}\n' \
  "$(printf '%064d' 99)" "$(date +%s%3N)" > "$d/state/attempts/$desired.json"
set +e
run_cmd "$d" bash "$repo/packages/t3code/release-window.sh" end-unknown > "$d/out.log" 2>&1
d_rc=$?
set -e
[[ $d_rc == 77 ]] || { echo "D: rc=$d_rc" >&2; cat "$d/out.log" >&2; exit 1; }
"$JQ" -e '.reason == "switch_unknown"' "$d/state/recovery-unknown.json" >/dev/null \
  || { echo 'D: another deployment attempt was taken as acceptance_unknown' >&2; exit 1; }
rm -rf "$d"
}

scenario_e() {
# E: the live sequence. end-unknown releases with reason acceptance_unknown and
# the container's deferral is still queued; resolve-unknown must still clear the
# inhibit. A queued restart stays a refusal, and the stopped-container recovery
# path of the same command must tolerate the deferral as well.
e=$(mktemp -d); trap 'rm -rf "$e"' EXIT
desired=$(printf '%064d' 15)
setup "$e" "$desired"
attempt "$e" "$desired" acceptance_unknown "$(date +%s%3N)"
: > "$e/run/t3code-tool-update/update-deferred.pending"
: > "$e/home/.local/state/t3code-tool-update/update-deferred.pending"
set +e
run_cmd "$e" bash "$repo/packages/t3code/release-window.sh" end-unknown > "$e/end.log" 2>&1
e_end_rc=$?
set -e
[[ $e_end_rc == 77 ]] || { echo "E: end rc=$e_end_rc" >&2; cat "$e/end.log" >&2; exit 1; }
"$JQ" -e '.reason == "acceptance_unknown"' "$e/state/recovery-unknown.json" >/dev/null
# The receipt is what investigation produces afterwards; end-unknown ran without one.
write_receipt "$e" "$desired"

: > "$e/run/t3code-tool-update/restart.pending"
if run_cmd "$e" bash "$repo/packages/t3code/release-window.sh" resolve-unknown > "$e/refuse.log" 2>&1; then
  echo 'E: resolve-unknown accepted a queued restart' >&2; exit 1
fi
grep -q 'container maintenance state unknown or pending' "$e/refuse.log" \
  || { echo 'E: unexpected refusal:' >&2; cat "$e/refuse.log" >&2; exit 1; }
[[ -e $e/hold && -e $e/state/recovery-unknown.json ]] || { echo 'E: refusal changed state' >&2; exit 1; }
rm "$e/run/t3code-tool-update/restart.pending"

run_cmd "$e" bash "$repo/packages/t3code/release-window.sh" resolve-unknown > "$e/out.log" 2>&1 \
  || { echo 'E: ordinary resolve-unknown refused the queued deferral:' >&2; cat "$e/out.log" >&2; exit 1; }
[[ ! -e $e/hold && ! -e $e/state/recovery-unknown.json ]] || { echo 'E: inhibit not cleared' >&2; exit 1; }
grep -q 'PASS UNKNOWN resolved' "$e/out.log"

# The same command with the container stopped restores it and proves the new
# serving, which is the other place the deferral is still queued.
g=$(mktemp -d); trap 'rm -rf "$g"' EXIT
desired=$(printf '%064d' 16)
setup "$g" "$desired"
attempt "$g" "$desired" acceptance_unknown "$(date +%s%3N)"
: > "$g/run/t3code-tool-update/update-deferred.pending"
: > "$g/home/.local/state/t3code-tool-update/update-deferred.pending"
set +e
run_cmd "$g" bash "$repo/packages/t3code/release-window.sh" end-unknown > "$g/end.log" 2>&1
g_end_rc=$?
set -e
[[ $g_end_rc == 77 ]] || { echo "E: stopped end rc=$g_end_rc" >&2; cat "$g/end.log" >&2; exit 1; }
write_receipt "$g" "$desired"
: > "$g/container-stopped"
run_cmd "$g" bash "$repo/packages/t3code/release-window.sh" resolve-unknown > "$g/out.log" 2>&1 \
  || { echo 'E: stopped resolve-unknown refused the queued deferral:' >&2; cat "$g/out.log" >&2; exit 1; }
grep -q 'container recovered and recovery inhibit cleared' "$g/out.log"
[[ ! -e $g/hold && ! -e $g/state/recovery-unknown.json ]] || { echo 'E: stopped inhibit not cleared' >&2; exit 1; }
rm -rf "$g"
rm -rf "$e"
}

scenario_f() {
# F: rollback's released retry has no active window, so it must ask for the
# tolerance too; a queued restart still refuses.
f=$(mktemp -d); trap 'rm -rf "$f"' EXIT
desired=$(printf '%064d' 17)
setup "$f" "$desired"
write_receipt "$f" "$desired"
rm -f "$f/evidence/active-window" "$f/hold"
printf '{}\n' > "$f/evidence/win/known-good.json"
: > "$f/run/t3code-tool-update/update-deferred.pending"
: > "$f/home/.local/state/t3code-tool-update/update-deferred.pending"
: > "$f/run/t3code-tool-update/restart.pending"
if run_cmd "$f" bash "$repo/packages/t3code/release-window.sh" rollback win > "$f/refuse.log" 2>&1; then
  echo 'F: released rollback accepted a queued restart' >&2; exit 1
fi
grep -q 'container maintenance state unknown or pending' "$f/refuse.log" \
  || { echo 'F: unexpected refusal:' >&2; cat "$f/refuse.log" >&2; exit 1; }
rm "$f/run/t3code-tool-update/restart.pending"
run_cmd "$f" bash "$repo/packages/t3code/release-window.sh" rollback win > "$f/out.log" 2>&1 \
  || { echo 'F: released rollback refused the queued deferral:' >&2; cat "$f/out.log" >&2; exit 1; }
grep -q 'window already released' "$f/out.log"
rm -rf "$f"
}

scenario_g() {
# G: end-post's already-released retry has no active window either, so the
# post verification it reruns must ask for the tolerance.
g=$(mktemp -d); trap 'rm -rf "$g"' EXIT
desired=$(printf '%064d' 3)
setup "$g" "$desired"
rm -rf "$g/current-system"; ln -s "$g/system" "$g/current-system"
write_receipt "$g" "$desired"
switch_ms=$(date +%s%3N)
printf '2026-10-31T04:02:40Z %s\n' "$switch_ms" > "$g/evidence/win/complete.started"
printf '{"deployment_id":"%s","exit_code":0,"started_at_ms":%s}\n' "$desired" "$switch_ms" > "$g/state/attempts/$desired.json"
rm -f "$g/evidence/active-window" "$g/hold"
printf '{}\n' > "$g/evidence/win/post.verified"
: > "$g/run/t3code-tool-update/update-deferred.pending"
: > "$g/home/.local/state/t3code-tool-update/update-deferred.pending"
: > "$g/run/t3code-tool-update/restart.pending"
if run_cmd "$g" bash "$repo/packages/t3code/release-window.sh" end-post win > "$g/refuse.log" 2>&1; then
  echo 'G: released end-post accepted a queued restart' >&2; exit 1
fi
grep -q 'container maintenance state unknown or pending' "$g/refuse.log" \
  || { echo 'G: unexpected refusal:' >&2; cat "$g/refuse.log" >&2; exit 1; }
rm "$g/run/t3code-tool-update/restart.pending"
run_cmd "$g" bash "$repo/packages/t3code/release-window.sh" end-post win > "$g/out.log" 2>&1 \
  || { echo 'G: released end-post refused the queued deferral:' >&2; cat "$g/out.log" >&2; exit 1; }
grep -q 'window already released' "$g/out.log"
rm -rf "$g"
}

scenario_h() {
# H: end-receipted-failure's already-released retry runs with no active window.
# Run it once against the open window so the tool writes its own UNKNOWN record,
# then retry with the container's deferral still queued.
h=$(mktemp -d); trap 'rm -rf "$h"' EXIT
desired=$(printf '%064d' 4)
setup "$h" "$desired"
write_receipt "$h" "$desired"
switch_ms=$(date +%s%3N)
printf '2026-10-31T04:02:40Z %s\n' "$switch_ms" > "$h/evidence/win/complete.started"
printf '{"deployment_id":"%s","exit_code":1,"started_at_ms":%s}\n' "$desired" "$switch_ms" > "$h/state/attempts/$desired.json"
set +e
run_cmd "$h" bash "$repo/packages/t3code/release-window.sh" end-receipted-failure > "$h/first.log" 2>&1
h_first_rc=$?
set -e
[[ $h_first_rc == 77 ]] || { echo "H: first rc=$h_first_rc" >&2; cat "$h/first.log" >&2; exit 1; }
[[ ! -e $h/evidence/active-window && -e $h/hold && -e $h/state/recovery-unknown.json ]] \
  || { echo 'H: window not released as expected' >&2; exit 1; }
: > "$h/run/t3code-tool-update/update-deferred.pending"
: > "$h/home/.local/state/t3code-tool-update/update-deferred.pending"
: > "$h/run/t3code-tool-update/restart.pending"
set +e
run_cmd "$h" bash "$repo/packages/t3code/release-window.sh" end-receipted-failure > "$h/refuse.log" 2>&1
h_refuse_rc=$?
set -e
[[ $h_refuse_rc == 1 ]] || { echo "H: refused retry rc=$h_refuse_rc" >&2; cat "$h/refuse.log" >&2; exit 1; }
grep -q 'container maintenance state unknown or pending' "$h/refuse.log" \
  || { echo 'H: unexpected refusal:' >&2; cat "$h/refuse.log" >&2; exit 1; }
rm "$h/run/t3code-tool-update/restart.pending"
set +e
run_cmd "$h" bash "$repo/packages/t3code/release-window.sh" end-receipted-failure > "$h/out.log" 2>&1
h_retry_rc=$?
set -e
[[ $h_retry_rc == 77 ]] || { echo "H: released retry rc=$h_retry_rc" >&2; cat "$h/out.log" >&2; exit 1; }
grep -q 'window released' "$h/out.log"
rm -rf "$h"
}

only=${1:-all}
for key in A B C D E F G H; do
  if [[ $only == all || $only == "$key" ]]; then
    "scenario_$(printf '%s' "$key" | tr 'A-Z' 'a-z')"
  fi
done

echo 'UNKNOWN ending proof: acceptance_unknown ends the window, every released command tolerates the queued deferral, a queued restart refuses, and a stale or foreign attempt is never taken as acceptance evidence.'
