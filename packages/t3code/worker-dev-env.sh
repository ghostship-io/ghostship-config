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
if [[ ! -f $env_file ]]; then
  [[ -n ${HOME:-} ]] || die 'HOME is unset; cannot locate the dev environment cache'
  mkdir -p "$cache" || die "cannot create $cache"
  chmod 0700 "$cache" 2>/dev/null || true
  err_file=$(mktemp "$cache/.err.XXXXXX") || die "cannot create an error file in $cache"
  if ! nix print-dev-env "$root" > "$env_file.tmp.$$" 2>"$err_file"; then
    reason=$(head -n1 "$err_file" 2>/dev/null)
    rm -f "$env_file.tmp.$$" "$err_file"
    die "cannot evaluate the devShell for $root${reason:+: $reason}"
  fi
  rm -f "$err_file"
  chmod 0600 "$env_file.tmp.$$" 2>/dev/null || true
  mv "$env_file.tmp.$$" "$env_file" || die "cannot store the devShell for $root"
fi
env_script=$(cat "$env_file") || die "cannot read the stored devShell for $root"
eval "$env_script" || die "cannot apply the devShell environment for $root"
[[ -n ${IN_NIX_SHELL:-} ]] || die "the devShell for $root did not establish a Nix environment"
