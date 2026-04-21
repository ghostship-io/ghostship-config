#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  finalize_worktree.sh inspect --target-branch <branch>
  finalize_worktree.sh finish --target-branch <branch>
EOF
}

die() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

sanitize_name() {
  local name
  name=$(printf '%s' "$1" | tr -cs 'A-Za-z0-9._-' '-')
  name=${name#-}
  name=${name%-}
  if [ -z "$name" ]; then
    name="worktree"
  fi
  printf '%s\n' "$name"
}

current_branch() {
  git -C "$1" symbolic-ref --quiet --short HEAD 2>/dev/null || true
}

conflict_paths() {
  git -C "$1" diff --name-only --diff-filter=U
}

status_porcelain() {
  git -C "$1" status --porcelain --untracked-files=normal
}

dirty_paths() {
  git -C "$1" status --porcelain --untracked-files=normal | while IFS= read -r line; do
    [ -n "$line" ] || continue
    line=${line#?? }
    case "$line" in
      *" -> "*)
        printf '%s\n' "${line##* -> }"
        ;;
      *)
        printf '%s\n' "$line"
        ;;
    esac
  done
}

incoming_paths() {
  git -C "$1" diff --name-only "$2..HEAD"
}

overlapping_paths() {
  local left_file="$1"
  local right_file="$2"

  if [ ! -s "$left_file" ] || [ ! -s "$right_file" ]; then
    return 0
  fi

  comm -12 "$left_file" "$right_file"
}

main_worktree_for_branch() {
  local target_ref="refs/heads/$1"
  local worktree=""
  local branch=""
  local line=""

  while IFS= read -r line; do
    case "$line" in
      "worktree "*)
        if [ -n "$worktree" ] && [ "$branch" = "$target_ref" ]; then
          printf '%s\n' "$worktree"
          return 0
        fi
        worktree=${line#worktree }
        branch=""
        ;;
      "branch "*)
        branch=${line#branch }
        ;;
      "")
        if [ -n "$worktree" ] && [ "$branch" = "$target_ref" ]; then
          printf '%s\n' "$worktree"
          return 0
        fi
        worktree=""
        branch=""
        ;;
    esac
  done < <(git worktree list --porcelain)

  if [ -n "$worktree" ] && [ "$branch" = "$target_ref" ]; then
    printf '%s\n' "$worktree"
  fi
}

subcommand=""
target_branch="main"

while [ "$#" -gt 0 ]; do
  case "$1" in
    inspect|finish)
      if [ -n "$subcommand" ]; then
        die "subcommand already set to '$subcommand'"
      fi
      subcommand="$1"
      shift
      ;;
    --target-branch)
      shift
      [ "$#" -gt 0 ] || die "--target-branch requires a value"
      target_branch="$1"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage >&2
      die "unknown argument '$1'"
      ;;
  esac
done

[ -n "$subcommand" ] || {
  usage >&2
  die "missing subcommand"
}

source_worktree=$(git rev-parse --show-toplevel 2>/dev/null) || die "run this script from inside a git worktree"
main_worktree=$(main_worktree_for_branch "$target_branch")
[ -n "$main_worktree" ] || die "could not find a worktree for local '$target_branch'"

source_branch=$(current_branch "$source_worktree")
detached="no"
needs_temp_branch="no"
if [ -z "$source_branch" ]; then
  detached="yes"
  needs_temp_branch="yes"
fi

if [ "$subcommand" = "inspect" ]; then
  printf 'source_worktree=%s\n' "$source_worktree"
  printf 'main_worktree=%s\n' "$main_worktree"
  printf 'current_branch=%s\n' "${source_branch:-DETACHED}"
  printf 'detached_head=%s\n' "$detached"
  printf 'needs_temp_branch=%s\n' "$needs_temp_branch"
  exit 0
fi

[ "$source_worktree" != "$main_worktree" ] || die "refusing to run from the '$target_branch' worktree"

if [ -n "$source_branch" ] && [ "$source_branch" = "$target_branch" ]; then
  die "refusing to finish a source worktree already attached to '$target_branch'"
fi

if [ -n "$(conflict_paths "$source_worktree")" ]; then
  die "source worktree has unresolved merge conflicts"
fi

if [ -n "$(status_porcelain "$source_worktree")" ]; then
  die "source worktree is not clean; commit or remove outstanding changes first"
fi

if [ -n "$(conflict_paths "$main_worktree")" ]; then
  die "target '$target_branch' worktree has unresolved merge conflicts"
fi

temp_branch=""
integration_branch="$source_branch"
if [ -z "$integration_branch" ]; then
  temp_branch="codex/finalize-$(sanitize_name "$(basename "$source_worktree")")-$(date -u +%Y%m%d%H%M%S)"
  git -C "$source_worktree" switch -c "$temp_branch" >/dev/null
  integration_branch="$temp_branch"
fi

target_ref="refs/heads/$target_branch"
target_head=$(git -C "$source_worktree" rev-parse "$target_ref")
merge_base=$(git -C "$source_worktree" merge-base HEAD "$target_ref")

if [ "$merge_base" != "$target_head" ]; then
  if ! git -C "$source_worktree" merge --no-edit "$target_ref"; then
    die "merging local '$target_branch' into the source worktree conflicted"
  fi
fi

if [ -n "$(conflict_paths "$source_worktree")" ]; then
  die "source worktree has unresolved merge conflicts after merging '$target_branch'"
fi

target_dirty_paths_file=$(mktemp)
incoming_paths_file=$(mktemp)
overlap_paths_file=$(mktemp)
cleanup_paths() {
  rm -f "$target_dirty_paths_file" "$incoming_paths_file" "$overlap_paths_file"
}
trap cleanup_paths EXIT

dirty_paths "$main_worktree" | sort -u > "$target_dirty_paths_file"
incoming_paths "$source_worktree" "$target_ref" | sort -u > "$incoming_paths_file"
overlapping_paths "$target_dirty_paths_file" "$incoming_paths_file" > "$overlap_paths_file"

if [ -s "$overlap_paths_file" ]; then
  overlap_csv=$(paste -sd, "$overlap_paths_file")
  die "target '$target_branch' worktree has dirty files that conflict with incoming changes: $overlap_csv"
fi

if ! git -C "$main_worktree" merge --ff-only "$integration_branch"; then
  die "fast-forwarding '$target_branch' to '$integration_branch' failed"
fi

cd "$main_worktree"
git worktree remove "$source_worktree"

if [ -n "$temp_branch" ]; then
  git branch -D "$temp_branch" >/dev/null
fi

printf 'source_worktree=%s\n' "$source_worktree"
printf 'main_worktree=%s\n' "$main_worktree"
printf 'integration_branch=%s\n' "$integration_branch"
printf 'temporary_branch_created=%s\n' "$( [ -n "$temp_branch" ] && printf yes || printf no )"
printf 'status=finished\n'
