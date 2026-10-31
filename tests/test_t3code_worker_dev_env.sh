#!/usr/bin/env bash
# The worker shell must get its repository's flake devShell automatically, fail
# closed when it cannot, and stay inert everywhere else.
set -euo pipefail
repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
hook=$repo/packages/t3code/worker-dev-env.sh
git_bin=$(command -v git)
base_path=$(dirname "$git_bin"):/usr/bin:/bin

workroot=${HOME:?}/.t3/worktrees
mkdir -p "$workroot"
tmp=$(mktemp -d "$workroot/dev-env-test.XXXXXX")
trap 'rm -rf "$tmp"' EXIT
fake=$tmp/fakebin
mkdir -p "$fake" "$tmp/marker/bin" "$tmp/repo"
printf '#!/bin/sh\necho marker-tool\n' > "$tmp/marker/bin/markertool"
chmod +x "$tmp/marker/bin/markertool"
cat > "$fake/nix" <<'SH'
#!/usr/bin/env bash
[[ ${1:-} == print-dev-env ]] || { echo 'unsupported: fake nix' >&2; exit 1; }
if [[ ${FAKE_NIX_FAIL:-0} == 1 ]]; then echo 'error: cannot evaluate the flake' >&2; exit 1; fi
printf 'export PATH=%s/marker/bin:$PATH\nexport IN_NIX_SHELL=impure\n' "${FAKE_ROOT:?}"
SH
chmod +x "$fake/nix"
printf '{}\n' > "$tmp/repo/flake.nix"
git -C "$tmp/repo" init -q

# run HOOK_CWD ENV... -- command
run() {
  local cwd=$1; shift
  ( cd "$cwd" && env -i HOME="$HOME" PATH="$fake:$base_path" BASH_ENV="$hook" FAKE_ROOT="$tmp" "$@" )
}

# 1. A trusted worktree with a flake loads the devShell, and the marker is true.
out=$(run "$tmp/repo" bash -c 'echo "shell=${IN_NIX_SHELL:-none}"; markertool')
[[ $out == *'shell=impure'* && $out == *marker-tool* ]] || { echo "A: not loaded: $out" >&2; exit 1; }

# 2. The cache is per flake fingerprint: a second shell reuses it.
out=$(run "$tmp/repo" bash -c 'markertool')
[[ $out == *marker-tool* ]] || { echo "B: cached load failed: $out" >&2; exit 1; }

# 3. Already inside a Nix shell: inert, no second evaluation.
out=$(run "$tmp/repo" IN_NIX_SHELL=pure bash -c 'command -v markertool || echo absent')
[[ $out != *marker-tool* ]] || { echo "C: hook re-entered a Nix shell" >&2; exit 1; }

# 4. Outside the trusted roots, even a flake is ignored.
outside=$(mktemp -d); trap 'rm -rf "$tmp" "$outside"' EXIT
printf '{}\n' > "$outside/flake.nix"; git -C "$outside" init -q
out=$(run "$outside" bash -c 'command -v markertool || echo absent')
[[ $out != *marker-tool* ]] || { echo "D: evaluated a flake outside the trusted roots" >&2; exit 1; }

# 5. A trusted directory without a flake is ignored.
plain=$tmp/plain; mkdir -p "$plain"; git -C "$plain" init -q
out=$(run "$plain" bash -c 'command -v markertool || echo absent')
[[ $out != *marker-tool* ]] || { echo "E: evaluated a directory without a flake" >&2; exit 1; }

# 6. An unavailable environment fails the command explicitly; no host fallback.
if run "$tmp/repo" FAKE_NIX_FAIL=1 bash -c 'markertool' >"$tmp/fail.out" 2>"$tmp/fail.err"; then
  echo "F: fell back to host tools" >&2; exit 1
fi
grep -q 'worker-dev-env: ' "$tmp/fail.err" || { echo 'F: no explicit error' >&2; cat "$tmp/fail.err" >&2; exit 1; }
grep -q 'marker-tool' "$tmp/fail.out" && { echo 'F: command ran anyway' >&2; exit 1; }

echo 'Worker dev environment: loaded in trusted flake worktrees, inert elsewhere, fails closed.'
