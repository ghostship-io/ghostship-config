#!/usr/bin/env bash
# Shared by the container image and the host-published service override.
set -eu
workspace="$1"
installer="$2"
shift 2

if [ ! -f "$workspace/ghostship-agent/flake.nix" ]; then
  printf 'ghostship-agent project is absent; installation deferred\n'
  exit 0
fi
state_dir="$XDG_STATE_HOME/t3code-ghostship-agent"
mkdir -p "$state_dir"
exec 8>"$state_dir/install.lock"
flock 8

# Fast-forward the shared source checkouts so GitHub merges reach the
# container. Never touch a checkout that is off main, has tracked edits,
# is mid-merge or rebase, or has diverged; the next sync retries.
sync_checkout() {
  repo="$1"
  git_dir="$repo/.git"
  [ -d "$git_dir" ] || return 0
  branch="$(git -C "$repo" branch --show-current 2>/dev/null || true)"
  if [ "$branch" != main ]; then
    printf 'source sync: %s is on %s; skipped\n' "$repo" "${branch:-a detached HEAD}"
    return 0
  fi
  for marker in MERGE_HEAD CHERRY_PICK_HEAD REVERT_HEAD rebase-merge rebase-apply; do
    if [ -e "$git_dir/$marker" ]; then
      printf 'source sync: %s has an operation in progress; skipped\n' "$repo"
      return 0
    fi
  done
  if [ -n "$(git -C "$repo" status --porcelain --untracked-files=no)" ]; then
    printf 'source sync: %s has uncommitted changes; skipped\n' "$repo"
    return 0
  fi
  if ! GIT_TERMINAL_PROMPT=0 \
    GIT_SSH_COMMAND="ssh -o BatchMode=yes -o ConnectTimeout=15" \
    timeout 60 git -C "$repo" fetch --quiet origin main; then
    printf 'warning: source sync: fetching %s failed\n' "$repo" >&2
    return 0
  fi
  if ! git -C "$repo" merge --ff-only --quiet refs/remotes/origin/main; then
    printf 'warning: source sync: %s cannot fast-forward to origin/main\n' "$repo" >&2
  fi
}

# Container boot and server starts skip the network so recovery is never
# delayed by GitHub; the sync timer catches up after boot.
case "${T3CODE_HOOK_SET:-}" in
  bootstrap.d|before-t3code.d) skip_sync=1 ;;
  *) skip_sync=0 ;;
esac
if [ "$skip_sync" -eq 0 ]; then
  sync_checkout "$workspace/ghostship-agent"
  sync_checkout "$workspace/nixos-config"
fi

# The host owns the current installer/package pin, including in an older image.
managed_installer="$HOME/.local/state/t3code-shared-agents/managed-installer"
if [ -x "$managed_installer" ]; then
  installer="$managed_installer"
fi
exec "$installer" "$@"
