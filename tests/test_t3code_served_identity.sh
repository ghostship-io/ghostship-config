#!/usr/bin/env bash
# The served-identity selector must agree with monotonic max(baked, persisted).
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
selector="$root/packages/t3code/served-identity.sh"
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT

home="$tmp/home/t3code"
t3="$home/.local/share/t3code-tools/t3"
mkdir -p "$tmp/usr/share/t3code-app" "$t3/releases"
bake() { printf '%s\n' "$1" > "$tmp/usr/share/t3code-app/VERSION"; printf '%064d\n' "${2:-0}" > "$tmp/usr/share/t3code-app/DIGEST"; }
persist() {
  mkdir -p "$t3/releases/$1"
  ln -sfn "$t3/releases/$1" "$t3/current"
}

run() { "$selector" --root "$tmp" 2>/dev/null; }

# 1. Baked only: a fresh container serves the app the image shipped.
bake 0.1.5 111
[[ $(run) == '{"source":"baked","version":"0.1.5","digest":"'$(printf '%064d' 111)'"}' ]]

# 2. Persisted newer than baked is served.
persist 0.1.6
[[ $(run) == '{"source":"persisted","version":"0.1.6","digest":""}' ]]

# 3. A persisted release older than baked must never displace it.
rm -f "$t3/current"
persist 0.1.4
[[ $(run) == '{"source":"baked","version":"0.1.5","digest":"'$(printf '%064d' 111)'"}' ]]

# 4. Same version: the persisted release wins because it carries a digest.
rm -f "$t3/current"
persist "0.1.5-$(printf '%064d' 222)"
[[ $(run) == '{"source":"persisted","version":"0.1.5","digest":"'$(printf '%064d' 222)'"}' ]]

# 5. Nothing anywhere is unknown, not a guess.
rm -f "$t3/current" "$tmp/usr/share/t3code-app/VERSION" "$tmp/usr/share/t3code-app/DIGEST"
if run >/dev/null; then echo 'identity reported with nothing installed' >&2; exit 1; fi

# 6. A persisted current that escapes releases/ is refused.
bake 0.1.5 111
mkdir -p "$tmp/elsewhere"; ln -sfn "$tmp/elsewhere" "$t3/current"
if run >/dev/null; then echo 'accepted escaped persisted current' >&2; exit 1; fi
rm -f "$t3/current"

# 7. A baked release without a digest is refused rather than reported bare.
rm -f "$tmp/usr/share/t3code-app/DIGEST"
if run >/dev/null; then echo 'accepted baked app without digest' >&2; exit 1; fi

echo 'Served identity proof: baked, persisted, monotonic max, and refuse-on-unknown.'
