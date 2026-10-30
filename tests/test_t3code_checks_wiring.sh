#!/usr/bin/env bash
# Every T3 deployment shell proof in tests/ must be wired into the config-tests
# derivation. An unwired proof still passes when run by hand, so the gap is
# invisible: test_t3code_window_lock.sh shipped in #716 and #721 without ever
# running in CI or in the sandbox build, and only a manual invocation caught it.
#
# This guard reads checks.nix and fails on any tests/test_t3code_*.sh that the
# derivation does not invoke. It deliberately does not execute the other
# proofs; it only proves they are wired.
set -euo pipefail
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
checks="$root/checks.nix"
[[ -f $checks ]] || { echo "missing checks.nix: $checks" >&2; exit 1; }

shopt -s nullglob
unwired=()
for script in "$root"/tests/test_t3code_*.sh; do
  name="tests/${script##*/}"
  # Require the path as a whole token on a line that is not a comment, so a
  # longer name that merely contains it, or a commented-out invocation, cannot
  # satisfy the guard.
  if ! grep -vE '^[[:space:]]*#' "$checks" \
    | grep -qE "(^|[[:space:]])${name//./\\.}([[:space:]]|\$)"; then
    unwired+=("$name")
  fi
done

if (( ${#unwired[@]} > 0 )); then
  printf 'unwired T3 deployment proof(s) in checks.nix:\n' >&2
  printf '  %s\n' "${unwired[@]}" >&2
  echo 'Add each to the config-tests derivation in checks.nix.' >&2
  exit 1
fi

echo "All T3 deployment shell proofs are wired into checks.nix."
