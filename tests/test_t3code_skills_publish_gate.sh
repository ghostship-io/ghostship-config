#!/usr/bin/env bash
# Activation installs host skills without an upload; the ChatGPT publish and
# the consumer verify run only when the operator marker exists.
set -euo pipefail
repo=$(cd "$(dirname "$0")/.." && pwd)
gate=$repo/packages/t3code/skills-publish-gate.sh
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
log=$tmp/calls.log
: > "$log"
stub() { printf '#!/bin/sh\necho "%s $*" >> %s\n' "$1" "$log" > "$2"; chmod +x "$2"; }
stub rollout "$tmp/rollout"
stub skills "$tmp/skills"
stub verify "$tmp/verify"
marker=$tmp/publish-requested
run() { GHOSTSHIP_SKILLS_PUBLISH_MARKER=$marker "$@"; }

# No marker: the host skills install runs, the publisher never does.
run "$gate" install "$tmp/rollout" "$tmp/skills" /src abc 1 /state bridge 2>/dev/null
grep -qx "skills --repo /src --source-sha abc install-t3" "$log" || { echo 'install path did not run' >&2; cat "$log" >&2; exit 1; }
if grep -q "rollout" "$log"; then echo 'publisher ran without the marker' >&2; cat "$log" >&2; exit 1; fi
# No marker: the consumer verify (which needs a publication) is skipped.
run "$gate" verify "$tmp/verify" 2>/dev/null
if grep -q "verify" "$log"; then echo 'consumer verify ran without the marker' >&2; cat "$log" >&2; exit 1; fi

# Marker present: exactly the publish path runs, no direct install.
: > "$log"; : > "$marker"
run "$gate" install "$tmp/rollout" "$tmp/skills" /src abc 1 /state bridge 2>/dev/null
grep -qx "rollout activate --skills-cli $tmp/skills --repo /src --source-sha abc --app-id 1 --state /state --bridge bridge" "$log" || { echo 'publish path did not run with the marker' >&2; cat "$log" >&2; exit 1; }
if grep -q "install-t3" "$log"; then echo 'install path ran with the marker' >&2; cat "$log" >&2; exit 1; fi
run "$gate" verify "$tmp/verify" 2>/dev/null
grep -q "^verify" "$log" || { echo 'consumer verify did not run with the marker' >&2; cat "$log" >&2; exit 1; }

echo 'skills publish gate: host install always, ChatGPT publish only with the marker.'
