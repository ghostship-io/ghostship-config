#!/usr/bin/env bash
# The pin recipe changes only the agent URL revs and the lock nodes, opens the
# ordinary PR, and commits with no attribution. A pin is not a special landing
# rule: it lands like any config PR.
set -euo pipefail
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
script="$root/scripts/pin-agent"
[[ -x $script ]] || { echo "pin-agent is not executable: $script" >&2; exit 1; }

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
repo="$tmp/repo"
mkdir -p "$repo/scripts" "$repo/bin"
cp "$script" "$repo/scripts/pin-agent"

old=9b0dfdc1ddf0e504ad17fdf216b07ccf5ae0097d
new=0123456789abcdef0123456789abcdef01234567
cat > "$repo/flake.nix" <<EOF
{
  inputs = {
    ghostship-private-agent.url = "github:ghostship-io/ghostship-agent/$old";
    ghostship-native-agent = {
      url = "github:ghostship-io/ghostship-agent/$old";
      flake = false;
    };
    ghostship-agent-policy = {
      url = "github:ghostship-io/ghostship-agent/130ebc86bb9242875f2ff8363fb3426ff4ddc682";
      flake = false;
    };
  };
}
EOF
jq -n --arg rev "$old" '{nodes:{"ghostship-private-agent":{locked:{rev:$rev,narHash:"sha256-old",lastModified:1}},
  "ghostship-native-agent":{locked:{rev:$rev,narHash:"sha256-old",lastModified:1}},
  "ghostship-agent-policy":{locked:{rev:"130ebc86bb9242875f2ff8363fb3426ff4ddc682",narHash:"sha256-policy",lastModified:2}}}}' \
  > "$repo/flake.lock"

# nix would refresh the two lock nodes from the new URL rev.
cat > "$repo/bin/nix" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
[[ $1 == flake && $2 == lock ]] || { echo "unexpected nix: $*" >&2; exit 1; }
jq --arg rev "$PIN_REV" '
  .nodes["ghostship-private-agent"].locked = {rev:$rev,narHash:"sha256-new",lastModified:3}
  | .nodes["ghostship-native-agent"].locked = {rev:$rev,narHash:"sha256-new",lastModified:3}
' "$PIN_REPO/flake.lock" > "$PIN_REPO/flake.lock.tmp"
mv -f "$PIN_REPO/flake.lock.tmp" "$PIN_REPO/flake.lock"
SH
cat > "$repo/bin/gh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "$PIN_GH_CALLS"
SH
chmod +x "$repo/bin/nix" "$repo/bin/gh"

cd "$repo"
git init -q -b main
git config user.name Fixture
git config user.email fixture
git add -A
git commit -qm base

export NIX_BIN="$repo/bin/nix" GH_BIN="$repo/bin/gh" PIN_REV="$new" PIN_REPO="$repo"
export PIN_GH_CALLS="$tmp/gh-calls"
git init -q --bare "$tmp/origin.git"
git remote add origin "$tmp/origin.git"

fail() {
  echo "FAIL: $*" >&2
  git -C "$repo" log --oneline --stat | head -20 >&2
  exit 1
}

# A malformed revision is refused before anything changes.
if "$repo/scripts/pin-agent" 1234 >/dev/null 2>&1; then fail 'a short revision was accepted'; fi
[[ -z $(git status --porcelain) ]] || fail 'a refused pin left the tree dirty'

# A dirty checkout is refused.
printf 'x\n' > "$repo/dirty"; if "$repo/scripts/pin-agent" "$new" >/dev/null 2>&1; then fail 'a dirty checkout was pinned'; fi
rm -f "$repo/dirty"

"$repo/scripts/pin-agent" "$new" >/dev/null

# 1. Only the pin files changed.
changed=$(git diff --name-only HEAD~1)
[[ $changed == $'flake.lock\nflake.nix' ]] || fail "the pin touched more than the pin files: $changed"

# 2. flake.nix changed only the two agent URL revs; the policy pin is untouched.
nix_diff=$(git diff -U0 HEAD~1 -- flake.nix | grep -E '^[-+][^-+]' || true)
[[ $(grep -c "$new" <<< "$nix_diff") == 2 ]] || fail "flake.nix did not move both agent revs: $nix_diff"
grep -q 'ghostship-agent-policy' <<< "$nix_diff" && fail 'the policy pin moved with the agent pin'
! grep -v "ghostship-io/ghostship-agent/$new" <<< "$nix_diff" | grep -qv "ghostship-io/ghostship-agent/$old" \
  || fail "flake.nix changed more than the revs: $nix_diff"

# 3. The lock moved only the two nodes' rev and hash.
lock_diff=$(git diff -U0 HEAD~1 -- flake.lock | grep -E '^[-+][^-+]' || true)
grep -q 'sha256-new' <<< "$lock_diff" || fail 'the lock hash did not move'
grep -q "$new" <<< "$lock_diff" || fail 'the lock rev did not move'
if grep -E 'sha256-policy|130ebc86' <<< "$lock_diff" >/dev/null; then fail 'the policy lock node moved'; fi

# 4. The commit carries no attribution.
message=$(git log -1 --format=%B)
for trailer in 'Co-authored-by' 'Generated with' 'Claude' 'Signed-off-by'; do
  grep -qi "$trailer" <<< "$message" && fail "the pin commit carries $trailer"
done

# 5. The PR is an ordinary config PR against main.
grep -q -- '--base main' "$PIN_GH_CALLS" || fail 'the pin PR was not opened against main'
grep -q 'pr create' "$PIN_GH_CALLS" || fail 'no PR was opened'

echo 'Pin recipe fixture passed: only the revs and lock nodes move, the PR targets main, and the commit carries no attribution.'
