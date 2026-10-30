#!/usr/bin/env bash
set -euo pipefail
repo=$(cd "$(dirname "$0")/.." && pwd)
tmp=$(mktemp -d); trap '[[ ! -f $tmp/holder-pid ]] || kill "$(cat "$tmp/holder-pid")" 2>/dev/null || true; rm -rf "$tmp"' EXIT
mkdir -p "$tmp/evidence" "$tmp/state" "$tmp/bin"
printf '%s\n' "$tmp/evidence" > "$tmp/config"
touch "$tmp/evidence/window.lock" "$tmp/state/deploy.lock" "$tmp/candidate.lock" "$tmp/hardening.lock"
printf 'old\n' > "$tmp/state/applied"; cp "$tmp/state/applied" "$tmp/state/desired"
ln -s system-1-link "$tmp/profile"
cat > "$tmp/bin/systemctl" <<'SH'
#!/usr/bin/env bash
if [[ $1 == show ]]; then
  if [[ $2 == window.service && $3 == -p && $4 == MainPID ]]; then cat "$FIXTURE/holder-pid"; exit; fi
  case $2 in window.service) [[ -f $FIXTURE/holder-pid ]] && kill -0 "$(cat "$FIXTURE/holder-pid")" 2>/dev/null && echo active || echo inactive ;; t3code-recovery.service) [[ -e $FIXTURE/recovery-inactive ]] && echo inactive || echo active ;; *) echo inactive ;; esac
elif [[ $1 == stop && $2 == t3code-recovery.service ]]; then touch "$FIXTURE/recovery-inactive"
elif [[ $1 == start && $2 == t3code-recovery.service ]]; then rm -f "$FIXTURE/recovery-inactive"
elif [[ $1 == stop && $2 == window.service ]]; then kill "$(cat "$FIXTURE/holder-pid")"; rm -f "$FIXTURE/holder-pid"
else exit 1; fi
SH
cat > "$tmp/bin/podman" <<'SH'
#!/usr/bin/env bash
printf 'healthy\n'
SH
cat > "$tmp/bin/systemd-run" <<'SH'
#!/usr/bin/env bash
while [[ $1 != -- ]]; do shift; done
shift
if [[ ${FIXTURE_NO_HANDSHAKE:-0} == 1 ]]; then
  sleep 8 6<&- 7<&- 8<&- >/dev/null 2>&1 &
else
  "$@" 6<&- 7<&- 8<&- >/dev/null 2>&1 &
fi
printf "%s\n" "$!" > "$FIXTURE/holder-pid"
SH
chmod +x "$tmp/bin/"*
export FIXTURE="$tmp" WINDOW_CONFIG="$tmp/config" WINDOW_INTENT_HELPER="$repo/packages/t3code/window-intent.sh" STATE_DIR="$tmp/state" SYSTEMCTL_BIN="$tmp/bin/systemctl" PODMAN_BIN="$tmp/bin/podman" PODMAN_TARGET=fixture WINDOW_UNIT=window HOLD_FILE="$tmp/hold" LOCK_CANDIDATE="$tmp/candidate.lock" LOCK_HARDENING="$tmp/hardening.lock" PROFILE="$tmp/profile" SYSTEMD_RUN_BIN="$tmp/bin/systemd-run" WINDOW_SECONDS=100
cmd=(bash "$repo/packages/t3code/release-window.sh")
# Preflight reads the actual lock files and ignores unrelated fixture locks.
mkdir -p "$tmp/evidence/old"
: > "$tmp/evidence/old/complete.lock"
for lock in "$tmp/candidate.lock" "$tmp/hardening.lock" "$tmp/state/deploy.lock" "$tmp/evidence/window.lock" "$tmp/evidence/old/complete.lock"; do
  exec 6>"$lock"; flock -x 6
  if "${cmd[@]}" preflight; then echo "accepted held $lock" >&2; exit 1; fi
  flock -u 6; exec 6>&-
done
: > "$tmp/other.lock"; exec 6>"$tmp/other.lock"; flock -x 6
"${cmd[@]}" preflight
flock -u 6; exec 6>&-
# ActiveState without a lock-holding handshake must not stop recovery.
export FIXTURE_NO_HANDSHAKE=1
if "${cmd[@]}" start failed-holder; then echo 'accepted holder without handshake' >&2; exit 1; fi
[[ ! -e $tmp/recovery-inactive && ! -e $tmp/hold ]]
kill "$(cat "$tmp/holder-pid")"; rm -f "$tmp/holder-pid" "$tmp/evidence/active-window"
unset FIXTURE_NO_HANDSHAKE
"${cmd[@]}" start one
[[ $(head -1 "$tmp/evidence/one/window.start") == *acquired_by=* ]]
[[ $(sed -n '2p' "$tmp/evidence/one/window.start") == holder_pid=* ]]
# An announced deploy, including one that crashes, must refuse end.
bash -c 'source "$WINDOW_INTENT_HELPER"; announce_intent deploy; exit 99' || [[ $? == 99 ]]
if "${cmd[@]}" end-no-activation; then echo 'accepted deploy intent' >&2; exit 1; fi
rm "$tmp/evidence/one/"effect-intent.*
touch "$tmp/evidence/one/complete.started"
if "${cmd[@]}" end-no-activation; then echo 'accepted switch intent' >&2; exit 1; fi
rm "$tmp/evidence/one/complete.started"
mv "$tmp/evidence/one/window.start" "$tmp/saved"
if "${cmd[@]}" end-no-activation; then echo 'accepted missing record' >&2; exit 1; fi
mv "$tmp/saved" "$tmp/evidence/one/window.start"
printf 'changed\n' > "$tmp/state/desired"
if "${cmd[@]}" end-no-activation; then echo 'accepted changed state' >&2; exit 1; fi
printf 'old\n' > "$tmp/state/desired"
"${cmd[@]}" end-no-activation
"${cmd[@]}" start two
"${cmd[@]}" switch -- true
if "${cmd[@]}" end-no-activation; then echo 'accepted announced switch' >&2; exit 1; fi
[[ -f "$tmp/evidence/two/complete.started" ]]
compgen -G "$tmp/evidence/two/effect-intent.switch.*" >/dev/null
echo 'Release window refusal and reopen fixture passed.'
