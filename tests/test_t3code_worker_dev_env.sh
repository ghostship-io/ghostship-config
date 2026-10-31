#!/usr/bin/env bash
# The worker shell must get its worktree's devShell automatically, evaluate it
# once, and stay inert everywhere else.
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
mkdir -p "$fake" "$tmp/marker/bin"
printf '#!/bin/sh\necho marker-tool\n' > "$tmp/marker/bin/markertool"
chmod +x "$tmp/marker/bin/markertool"
cat > "$fake/nix" <<'SH'
#!/usr/bin/env bash
[[ ${1:-} == print-dev-env ]] || { echo 'unsupported: fake nix' >&2; exit 1; }
printf '%s\n' "$*" >> "${FAKE_COUNT:?}"
# Model the GC root that --profile creates.
if [[ $2 == --profile ]]; then mkdir -p "$3"; fi
if [[ ${FAKE_NIX_FAIL:-0} == 1 ]]; then echo 'error: cannot evaluate the flake' >&2; exit 1; fi
printf 'export PATH=%s/marker/bin:$PATH\nexport IN_NIX_SHELL=impure\n' "${FAKE_ROOT:?}"
SH
chmod +x "$fake/nix"
export FAKE_COUNT=$tmp/nix.calls
: > "$FAKE_COUNT"

# A real linked worktree under the fixed root, which is what the launcher makes.
mkdir -p "$tmp/origin"
git -C "$tmp/origin" init -q
git -C "$tmp/origin" remote add origin https://github.com/ghostship-io/ghostship-config.git
printf '{}\n' > "$tmp/origin/flake.nix"
git -C "$tmp/origin" add flake.nix
git -C "$tmp/origin" -c user.email=t@t -c user.name=t -c core.hooksPath=/dev/null commit -qm init
wt=$tmp/repo
git -C "$tmp/origin" worktree add -q "$wt" -b test

run() {
  local cwd=$1; shift
  ( cd "$cwd" && env -i HOME="$HOME" PATH="$fake:$base_path" BASH_ENV="$hook" FAKE_ROOT="$tmp" FAKE_COUNT="$FAKE_COUNT" "$@" )
}

# 1. A linked worktree under the fixed root loads the devShell from one evaluation.
out=$(run "$wt" bash -c 'echo "shell=${IN_NIX_SHELL:-none}"; markertool')
[[ $out == *'shell=impure'* && $out == *marker-tool* ]] || { echo "A: not loaded: $out" >&2; exit 1; }
[[ $(wc -l < "$FAKE_COUNT") == 1 ]] || { echo "A: evaluated $(wc -l < "$FAKE_COUNT") times" >&2; exit 1; }
compgen -G "$HOME/.cache/ghostship/worker-dev-env/*.profile" >/dev/null || { echo 'A: no GC root profile' >&2; exit 1; }

# 2. A second shell reuses the stored environment and does not evaluate again.
out=$(run "$wt" bash -c 'markertool')
[[ $out == *marker-tool* ]] || { echo "B: cached load failed: $out" >&2; exit 1; }
[[ $(wc -l < "$FAKE_COUNT") == 1 ]] || { echo "B: cached shell re-evaluated" >&2; exit 1; }

# 3. A committed flake change invalidates the cache.
printf '{}\n# changed\n' > "$wt/flake.nix"
git -C "$wt" -c user.email=t@t -c user.name=t -c core.hooksPath=/dev/null commit -qam change
out=$(run "$wt" bash -c 'markertool')
[[ $out == *marker-tool* ]] || { echo "C: change did not reload: $out" >&2; exit 1; }
[[ $(wc -l < "$FAKE_COUNT") == 2 ]] || { echo "C: change did not re-evaluate" >&2; exit 1; }

# 4. Already inside a Nix shell: inert.
out=$(run "$wt" IN_NIX_SHELL=pure bash -c 'command -v markertool || echo absent')
[[ $out != *marker-tool* ]] || { echo "D: hook re-entered a Nix shell" >&2; exit 1; }

# 5. A linked worktree outside the fixed root is ignored.
outside=$(mktemp -d); trap 'rm -rf "$tmp" "$outside"' EXIT
git -C "$tmp/origin" worktree add -q "$outside/wt" -b outside
out=$(run "$outside/wt" bash -c 'command -v markertool || echo absent')
[[ $out != *marker-tool* ]] || { echo "E: evaluated outside the fixed root" >&2; exit 1; }

# 6a. A linked worktree whose flake is only a drop-in is ignored.
mkdir -p "$tmp/noflake"
git -C "$tmp/noflake" init -q
git -C "$tmp/noflake" remote add origin https://github.com/ghostship-io/ghostship-config.git
printf 'x\n' > "$tmp/noflake/README"
git -C "$tmp/noflake" add README
git -C "$tmp/noflake" -c user.email=t@t -c user.name=t -c core.hooksPath=/dev/null commit -qm init
git -C "$tmp/noflake" worktree add -q "$tmp/evil" -b evil
printf '{}\n' > "$tmp/evil/flake.nix"   # untracked drop-in
out=$(run "$tmp/evil" bash -c 'command -v markertool || echo absent')
[[ $out != *marker-tool* ]] || { echo "F2: evaluated an untracked flake" >&2; exit 1; }

# 6a2. A modified (uncommitted) flake is not committed content.
printf '{}\n# dirty\n' > "$wt/flake.nix"
out=$(run "$wt" bash -c 'command -v markertool || echo absent')
[[ $out != *marker-tool* ]] || { echo "F2c: evaluated a modified flake" >&2; exit 1; }
git -C "$wt" checkout -q -- flake.nix

# 6b0. Traversal and encoded origins are rejected; scp and ssh forms accepted.
for bad in 'https://github.com/ghostship-io/../evil' 'https://github.com/ghostship-io/%2e%2e/repo' 'https://github.com/ghostship-io/repo?x=1'; do
  git -C "$tmp/origin" remote set-url origin "$bad"
  out=$(run "$wt" bash -c 'command -v markertool || echo absent')
  [[ $out != *marker-tool* ]] || { echo "F2d: accepted $bad" >&2; exit 1; }
done
for good in 'git@github.com:ghostship-io/ghostship-config.git' 'ssh://git@github.com/ghostship-io/ghostship-config'; do
  git -C "$tmp/origin" remote set-url origin "$good"
  out=$(run "$wt" bash -c 'markertool || echo absent')
  [[ $out == *marker-tool* ]] || { echo "F2e: rejected $good" >&2; exit 1; }
done
git -C "$tmp/origin" remote set-url origin https://github.com/ghostship-io/ghostship-config.git

# 6b. A linked worktree of a foreign repository is ignored.
foreign=$(mktemp -d); trap 'rm -rf "$tmp" "$outside" "$foreign"' EXIT
mkdir -p "$foreign/src"; git -C "$foreign/src" init -q
git -C "$foreign/src" remote add origin https://example.com/elsewhere.git
printf '{}\n' > "$foreign/src/flake.nix"; git -C "$foreign/src" add flake.nix
git -C "$foreign/src" -c user.email=t@t -c user.name=t -c core.hooksPath=/dev/null commit -qm init
git -C "$foreign/src" worktree add -q "$foreign/wt" -b foreign
out=$(run "$foreign/wt" bash -c 'command -v markertool || echo absent')
[[ $out != *marker-tool* ]] || { echo "F3: evaluated a foreign repository" >&2; exit 1; }

# 6. A plain directory with a flake, not a linked worktree, is ignored.
plain=$tmp/plain; mkdir -p "$plain"; printf '{}\n' > "$plain/flake.nix"
git -C "$plain" init -q
out=$(run "$plain" bash -c 'command -v markertool || echo absent')
[[ $out != *marker-tool* ]] || { echo "F: evaluated a non-worktree" >&2; exit 1; }

# 7. An unavailable environment fails the command explicitly; no host fallback.
# A fresh fingerprint forces evaluation instead of reusing the cache.
printf '{}\n# fail\n' > "$wt/flake.nix"
git -C "$wt" -c user.email=t@t -c user.name=t -c core.hooksPath=/dev/null commit -qam fail
if run "$wt" FAKE_NIX_FAIL=1 bash -c 'markertool' >"$tmp/fail.out" 2>"$tmp/fail.err"; then
  echo "G: fell back to host tools" >&2; exit 1
fi
grep -q 'worker-dev-env: ' "$tmp/fail.err" || { echo 'G: no explicit error' >&2; cat "$tmp/fail.err" >&2; exit 1; }
grep -q 'marker-tool' "$tmp/fail.out" && { echo 'G: command ran anyway' >&2; exit 1; }

echo 'Worker dev environment: one evaluation per worktree, inert elsewhere, fails closed.'
