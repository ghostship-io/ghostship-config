# Sourced by bash for every non-interactive shell (BASH_ENV). When the shell
# starts inside a trusted worktree with a flake, it loads that flake's default
# devShell so commands get the repository environment without per-command
# wrapping, absolute store paths, or hand-set markers.
#
# Quiet on success. Fails closed with one clear line when the environment cannot
# be established: a command never silently runs against host-ambient tools.
# IN_NIX_SHELL is only ever set by Nix itself.
(return 0 2>/dev/null) || { echo 'worker-dev-env: must be sourced' >&2; exit 1; }
case $- in *i*) return 0 ;; esac
[[ -n ${IN_NIX_SHELL:-} ]] && return 0
[[ -z ${NIX_BUILD_TOP:-} ]] || return 0
[[ -n ${PWD:-} && -d ${PWD:-} ]] || return 0

die() { printf 'worker-dev-env: %s\n' "$*" >&2; exit 1; }

root=$(git -C "$PWD" rev-parse --show-toplevel 2>/dev/null) || return 0
[[ -f $root/flake.nix ]] || return 0
# Only the trusted roots: never evaluate a flake from anywhere else.
case $root in
  /workspace/*|"${HOME:-/nonexistent}"/.t3/worktrees/*) ;;
  *) return 0 ;;
esac
# A child shell (including the evaluator itself) that already has this repo's
# environment returns immediately; a child in another repo still loads its own.
[[ ${WORKER_DEV_ENV_ROOT:-} == "$root" ]] && return 0
export WORKER_DEV_ENV_ROOT=$root
[[ -n ${HOME:-} ]] || die 'HOME is unset; cannot locate the dev environment cache'

cache=${XDG_CACHE_HOME:-$HOME/.cache}/ghostship/worker-dev-env
key=$(
  {
    sha256sum "$root/flake.nix" 2>/dev/null
    sha256sum "$root/flake.lock" 2>/dev/null
    uname -m
  } | sha256sum | cut -d' ' -f1
)
[[ -n $key ]] || die "cannot fingerprint the flake in $root"
profile=$cache/$key
if [[ ! -e $profile ]]; then
  mkdir -p "$cache" || die "cannot create $cache"
  if ! nix print-dev-env --profile "$profile" "$root" >/dev/null 2>"$cache/$key.err"; then
    reason=$(head -n1 "$cache/$key.err" 2>/dev/null)
    die "cannot evaluate the devShell for $root${reason:+: $reason}"
  fi
fi
if ! env_script=$(nix print-dev-env --profile "$profile" "$root" 2>"$cache/$key.err"); then
  reason=$(head -n1 "$cache/$key.err" 2>/dev/null)
  die "cannot load the devShell for $root${reason:+: $reason}"
fi
eval "$env_script" || die "cannot apply the devShell environment for $root"
[[ -n ${IN_NIX_SHELL:-} ]] || die "the devShell for $root did not establish a Nix environment"
