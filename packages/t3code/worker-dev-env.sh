# Sourced by bash for every non-interactive shell (BASH_ENV). When the shell
# starts inside the launcher's worktree root, it loads that repository's default
# devShell so commands get the repository environment without per-command
# wrapping, absolute store paths, or hand-set markers.
#
# Quiet on success. Fails closed with one clear line when the environment cannot
# be established: a command never silently runs against host-ambient tools.
# The hook never sets IN_NIX_SHELL itself; it comes from Nix. A command that
# exports IN_NIX_SHELL (or NIX_BUILD_TOP) can still skip the hook, so that is a
# convention, not an enforcement boundary.
#
# Trust model, stated plainly: the hook runs as the worker's own uid, so it
# cannot tell a launcher-created worktree from one the worker made, and loading
# a flake the worker wrote grants nothing the worker could not run anyway. What
# this does protect against is evaluating a *foreign repository's* flake that
# happens to sit under the worktree root: the origin remote must match the
# root-owned allowlist installed beside this hook.
(return 0 2>/dev/null) || { echo 'worker-dev-env: must be sourced' >&2; exit 1; }
case $- in *i*) return 0 ;; esac
[[ -n ${IN_NIX_SHELL:-} ]] && return 0
[[ -z ${NIX_BUILD_TOP:-} ]] || return 0
[[ -n ${PWD:-} && -d ${PWD:-} ]] || return 0

die() { printf 'worker-dev-env: %s\n' "$*" >&2; exit 1; }

# The trusted root is fixed by the image beside this hook: /etc/ghostship is
# root-owned, so neither HOME nor the command line can move it. The root file
# must belong to the same owner as the hook itself.
self=$(readlink -f "${BASH_SOURCE[0]}" 2>/dev/null) || return 0
root_file=$(dirname "$self")/worker-dev-env.root
[[ -f $root_file && ! -L $root_file ]] || return 0
[[ $(stat -c %u "$root_file" 2>/dev/null) == "$(stat -c %u "$self" 2>/dev/null)" ]] || return 0
worktree_root=$(head -n1 "$root_file" 2>/dev/null)
[[ -n $worktree_root && $worktree_root == /* && -d $worktree_root ]] || return 0

# Only shells that start inside that root; nothing else is ever evaluated.
case $PWD/ in
  "$worktree_root"/*) ;;
  *) return 0 ;;
esac
root=$(git -C "$PWD" rev-parse --show-toplevel 2>/dev/null) || return 0
case $root/ in
  "$worktree_root"/*) ;;
  *) return 0 ;;
esac
# The launcher creates linked worktrees there; a plain directory carrying a
# flake is not an assigned worktree and is left alone.
[[ -f $root/.git ]] || return 0
[[ -f $root/flake.nix ]] || return 0
# The flake must be committed content at this worktree's HEAD and unmodified:
# a dropped-in file, a staged one, or an edited one is not repository content.
git -C "$root" cat-file -e HEAD:flake.nix 2>/dev/null || return 0
git -C "$root" diff --quiet HEAD -- flake.nix 2>/dev/null || return 0
if [[ -e $root/flake.lock ]]; then
  git -C "$root" cat-file -e HEAD:flake.lock 2>/dev/null || return 0
  git -C "$root" diff --quiet HEAD -- flake.lock 2>/dev/null || return 0
fi
# Only the allowed repository origins: an external clone placed under the root
# is not evaluated. The origin is parsed, not prefix-matched, so traversal,
# encoded separators, query/fragment and userinfo forms are all rejected.
origins_file=$(dirname "$self")/worker-dev-env.origins
[[ -f $origins_file && ! -L $origins_file ]] || return 0
[[ $(stat -c %u "$origins_file" 2>/dev/null) == "$(stat -c %u "$self" 2>/dev/null)" ]] || return 0
parse_origin() {
  local origin=$1 host org repo
  case $origin in
    https://*|http://*|ssh://*) origin=${origin#*://} ;;
    git@*) origin=${origin#git@} ;;
    *) return 1 ;;
  esac
  origin=${origin#git@}
  [[ $origin != *@* ]] || return 1
  if [[ $origin =~ ^([A-Za-z0-9.-]+)(:[0-9]+)?/([A-Za-z0-9._-]+)/([A-Za-z0-9._-]+)$ ]]; then
    host=${BASH_REMATCH[1]}; org=${BASH_REMATCH[3]}; repo=${BASH_REMATCH[4]}
  elif [[ $origin =~ ^([A-Za-z0-9.-]+):([A-Za-z0-9._-]+)/([A-Za-z0-9._-]+)$ ]]; then
    host=${BASH_REMATCH[1]}; org=${BASH_REMATCH[2]}; repo=${BASH_REMATCH[3]}
  else
    return 1
  fi
  repo=${repo%.git}
  [[ $host == github.com ]] || return 1
  [[ $org != . && $org != .. && $repo != . && $repo != .. ]] || return 1
  [[ $org != *..* && $repo != *..* ]] || return 1
  printf '%s/%s\n' "$host" "$org"
}
origin=$(git -C "$root" remote get-url origin 2>/dev/null) || return 0
parsed=$(parse_origin "$origin") || return 0
allowed=0
while IFS= read -r entry; do
  [[ -n $entry ]] || continue
  [[ $parsed == "$entry" ]] && { allowed=1; break; }
done < "$origins_file"
(( allowed )) || return 0

# A child shell (including the evaluator itself) that already has this repo's
# environment returns immediately; a child in another worktree loads its own.
[[ ${WORKER_DEV_ENV_ROOT:-} == "$root" ]] && return 0
export WORKER_DEV_ENV_ROOT=$root

cache=${XDG_CACHE_HOME:-$HOME/.cache}/ghostship/worker-dev-env
key=$(
  {
    sha256sum "$root/flake.nix" 2>/dev/null
    sha256sum "$root/flake.lock" 2>/dev/null
    uname -m
  } | sha256sum | cut -d' ' -f1
)
[[ -n $key ]] || die "cannot fingerprint the flake in $root"
env_file=$cache/$key.env
repo_file=$cache/$key.repo
lock_file=$cache/$key.lock
lock_hash=$(sha256sum "$root/flake.lock" 2>/dev/null | cut -d' ' -f1)
lock_hash=${lock_hash:-none}
if [[ ! -f $env_file ]]; then
  [[ -n ${HOME:-} ]] || die 'HOME is unset; cannot locate the dev environment cache'
  mkdir -p "$cache" || die "cannot create $cache"
  chmod 0700 "$cache" 2>/dev/null || true
  # A cache miss must not build or evaluate. Entering this repository's devShell
  # builds the coordinator from source and runs its Go test suite: minutes per
  # new key, and a hard failure on a test that needs git, so every worktree with
  # a new key lost its shell. Reuse only an environment resolved for this
  # repository under the same locked inputs (same flake.lock digest): that is
  # the same toolchain, unlike the newest unrelated entry. With no such entry
  # the command runs on the image's locked toolchain; `nix develop` builds this
  # worktree's exact environment on request, and WORKER_DEV_ENV_RESOLVE=1
  # resolves and records it once.
  resolved=
  while IFS= read -r candidate; do
    [[ -n $candidate && -f $candidate && ! -L $candidate ]] || continue
    [[ ${candidate##*/} != "$key.env" ]] || continue
    [[ $(cat "${candidate%.env}.repo" 2>/dev/null) == "$parsed" ]] || continue
    [[ $(cat "${candidate%.env}.lock" 2>/dev/null) == "$lock_hash" ]] || continue
    resolved=$candidate
    break
  done < <(ls -1t "$cache"/*.env 2>/dev/null)
  if [[ -n $resolved ]]; then
    cp -- "$resolved" "$env_file.tmp.$$" || die "cannot store the reused devShell for $root"
    chmod 0600 "$env_file.tmp.$$" 2>/dev/null || true
    mv "$env_file.tmp.$$" "$env_file" || die "cannot store the reused devShell for $root"
    printf '%s\n' "${resolved##*/}" > "$cache/$key.reused" 2>/dev/null || true
    printf '%s\n' "$parsed" > "$repo_file" 2>/dev/null || true
    printf '%s\n' "$lock_hash" > "$lock_file" 2>/dev/null || true
    printf 'worker-dev-env: reusing the resolved devShell %s for %s; run nix develop for this worktree\n' \
      "${resolved##*/}" "$root" >&2
  elif [[ ${WORKER_DEV_ENV_RESOLVE:-} == 1 ]]; then
    err_file=$(mktemp "$cache/.err.XXXXXX") || die "cannot create an error file in $cache"
    # --profile keeps the devShell closure as a GC root, so the store paths the
    # cached environment exports cannot be collected underneath us.
    if ! nix print-dev-env --profile "$cache/$key.profile" "$root" > "$env_file.tmp.$$" 2>"$err_file"; then
      reason=$(head -n1 "$err_file" 2>/dev/null)
      rm -f "$env_file.tmp.$$" "$err_file"
      die "cannot evaluate the devShell for $root${reason:+: $reason}"
    fi
    rm -f "$err_file"
    chmod 0600 "$env_file.tmp.$$" 2>/dev/null || true
    mv "$env_file.tmp.$$" "$env_file" || die "cannot store the devShell for $root"
    printf '%s\n' "$parsed" > "$repo_file" 2>/dev/null || true
    printf '%s\n' "$lock_hash" > "$lock_file" 2>/dev/null || true
  else
    # No resolved entry for these locked inputs: never build or evaluate on an
    # ordinary command. The image's toolchain is the one this release ships.
    # Say so once per key; repeats stay quiet and fast.
    if [[ ! -f $cache/$key.miss ]]; then
      printf '%s\n' "$parsed" > "$cache/$key.miss" 2>/dev/null || true
      printf 'worker-dev-env: no resolved devShell for lock %s in %s; using the image toolchain (nix develop for this worktree)\n' \
        "$lock_hash" "$root" >&2
    fi
    return 0
  fi
fi
env_script=$(cat "$env_file") || die "cannot read the stored devShell for $root"
eval "$env_script" || die "cannot apply the devShell environment for $root"
[[ -n ${IN_NIX_SHELL:-} ]] || die "the devShell for $root did not establish a Nix environment"
