#!/usr/bin/env bash
# Direct regression for the tooling pointer advance.
#
# Covers the four behaviours the deployment acceptance depends on: a stale
# pointer advances to the exact declared target, a fresh path is created, a
# repeated apply is a no-op, and a failure preserves the previous usable target.
# It also proves the replacement is atomic by reading the link continuously
# while it is replaced, so it is never observed absent.
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
script=$root/packages/t3code/tooling-pointer.sh
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }

old=$tmp/tooling-old
new=$tmp/tooling-new
mkdir -p "$old" "$new"
link=$tmp/state/ghostship-t3-tools/current
mkdir -p "$(dirname "$link")"

# 1. A stale pointer advances to the exact declared target.
ln -s "$old" "$link"
bash "$script" "$new" "$link"
[[ $(readlink "$link") == "$new" ]] || fail "stale pointer did not advance to the declared target"

# 2. A fresh/absent path is created.
fresh=$tmp/state/fresh/current
mkdir -p "$(dirname "$fresh")"
bash "$script" "$new" "$fresh"
[[ $(readlink "$fresh") == "$new" ]] || fail "absent path was not created"

# 3. A repeated apply is a no-op: the link is not rewritten at all.
before=$(stat -c '%i' "$link")
bash "$script" "$new" "$link"
after=$(stat -c '%i' "$link")
[[ $before == "$after" ]] || fail "repeated apply rewrote an already-correct link"
[[ $(readlink "$link") == "$new" ]] || fail "repeated apply changed the target"

# 4. A failure preserves the previous usable target.
if bash "$script" "$tmp/does-not-exist" "$link" 2>/dev/null; then
  fail "a missing target was accepted"
fi
[[ $(readlink "$link") == "$new" ]] || fail "a failed advance destroyed the previous target"
[[ -d $(readlink "$link") ]] || fail "the preserved target is not usable"

# 4b. A file target is refused the same way a missing one is.
touch "$tmp/not-a-dir"
if bash "$script" "$tmp/not-a-dir" "$link" 2>/dev/null; then
  fail "a non-directory target was accepted"
fi
[[ $(readlink "$link") == "$new" ]] || fail "a refused non-directory target changed the pointer"

# 5. Ownership and symlink semantics: the link is still a symlink to a
# directory, and replacing it did not touch the target itself.
[[ -L $link ]] || fail "the pointer is no longer a symlink"
[[ $(stat -c '%h' "$new") -ge 1 ]] || fail "the target directory disappeared"
[[ $(stat -c '%u:%g' "$link") == "$(id -u):$(id -g)" ]] || fail "the replacement did not keep the writer's ownership"

# 6. Atomicity: while the link is repeatedly replaced, a concurrent reader must
# never observe it absent. A remove-then-create would surface ENOENT here.
tick=$tmp/tick
: > "$tick"
(
  # Bounded reader: sample continuously until the tick file disappears.
  while [[ -e $tick ]]; do
    readlink "$link" >/dev/null 2>&1 || { printf 'absent\n' >> "$tmp/absent"; }
  done
) &
reader=$!
for _ in $(seq 1 400); do
  bash "$script" "$old" "$link"
  bash "$script" "$new" "$link"
done
rm -f "$tick"
wait "$reader" || true
[[ ! -s $tmp/absent ]] || fail "the link was observed absent during replacement, so the swap is not atomic"
[[ $(readlink "$link") == "$new" ]] || fail "final target is not the last applied target"

printf 'PASS: tooling pointer advance covers stale, fresh, no-op, failure, ownership and atomic swap\n'
