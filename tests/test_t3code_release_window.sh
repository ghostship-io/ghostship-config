#!/usr/bin/env bash
set -euo pipefail
repo=$(cd "$(dirname "$0")/.." && pwd)
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/evidence" "$tmp/state" "$tmp/bin"
printf '%s\n' "$tmp/evidence" > "$tmp/config"
touch "$tmp/evidence/window.lock" "$tmp/state/deploy.lock" "$tmp/candidate.lock" "$tmp/hardening.lock"
printf 'old\n' > "$tmp/state/applied"; cp "$tmp/state/applied" "$tmp/state/desired"
ln -s system-1-link "$tmp/profile"
cat > "$tmp/bin/systemctl" <<'SH'
#!/usr/bin/env bash
if [[ $1 == show ]]; then
  case $2 in window.service) [[ -e $FIXTURE/window-active ]] && echo active || echo inactive ;; t3code-recovery.service) [[ -e $FIXTURE/recovery-inactive ]] && echo inactive || echo active ;; *) echo inactive ;; esac
elif [[ $1 == stop && $2 == t3code-recovery.service ]]; then touch "$FIXTURE/recovery-inactive"
elif [[ $1 == start && $2 == t3code-recovery.service ]]; then rm -f "$FIXTURE/recovery-inactive"
elif [[ $1 == stop && $2 == window.service ]]; then rm -f "$FIXTURE/window-active"
else exit 1; fi
SH
cat > "$tmp/bin/podman" <<'SH'
#!/usr/bin/env bash
printf 'healthy\n'
SH
cat > "$tmp/bin/systemd-run" <<'SH'
#!/usr/bin/env bash
touch "$FIXTURE/window-active"
SH
chmod +x "$tmp/bin/"*
export FIXTURE="$tmp" WINDOW_CONFIG="$tmp/config" WINDOW_INTENT_HELPER="$repo/packages/t3code/window-intent.sh" STATE_DIR="$tmp/state" SYSTEMCTL_BIN="$tmp/bin/systemctl" PODMAN_BIN="$tmp/bin/podman" PODMAN_TARGET=fixture WINDOW_UNIT=window HOLD_FILE="$tmp/hold" LOCK_CANDIDATE="$tmp/candidate.lock" LOCK_HARDENING="$tmp/hardening.lock" PROFILE="$tmp/profile" SYSTEMD_RUN_BIN="$tmp/bin/systemd-run" WINDOW_SECONDS=100
cmd=(bash "$repo/packages/t3code/release-window.sh")
"${cmd[@]}" start one
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
"${cmd[@]}" end-no-activation
echo 'Release window refusal and reopen fixture passed.'
