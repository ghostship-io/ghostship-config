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

print_kv() {
  printf '%s=%s\n' "$1" "$2"
}

print_list() {
  local key="$1"
  shift
  local item=""
  for item in "$@"; do
    print_kv "$key" "$item"
  done
}

current_branch() {
  git -C "$1" symbolic-ref --quiet --short HEAD 2>/dev/null || true
}

current_head() {
  git -C "$1" rev-parse HEAD
}

conflict_paths() {
  git -C "$1" diff --name-only --diff-filter=U
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
  git -C "$1" diff --name-only "$2...HEAD"
}

incoming_commits() {
  git -C "$1" log --format='%H %s' --reverse "$2..HEAD"
}

collect_lines() {
  local -n out="$1"
  shift
  local line=""

  out=()
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    out+=("$line")
  done < <("$@")
}

collect_sorted_unique_lines() {
  local -n out="$1"
  shift
  local line=""

  out=()
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    out+=("$line")
  done < <("$@" | sort -u)
}

collect_overlapping_paths() {
  local -n left="$1"
  local -n right="$2"
  local -n out="$3"
  local item=""
  declare -A left_lookup=()
  declare -A overlap_lookup=()

  out=()
  for item in "${left[@]}"; do
    left_lookup["$item"]=1
  done

  for item in "${right[@]}"; do
    if [ "${left_lookup[$item]+yes}" = "yes" ] && [ "${overlap_lookup[$item]+yes}" != "yes" ]; then
      out+=("$item")
      overlap_lookup["$item"]=1
    fi
  done
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

collect_preflight() {
  target_ref="refs/heads/$target_branch"
  source_head=$(current_head "$source_worktree")
  target_head=$(git -C "$source_worktree" rev-parse "$target_ref")
  merge_base=$(git -C "$source_worktree" merge-base HEAD "$target_ref")

  read -r source_ahead_count source_behind_count < <(
    git -C "$source_worktree" rev-list --left-right --count "HEAD...$target_ref"
  )

  collect_sorted_unique_lines source_conflict_path_list conflict_paths "$source_worktree"
  collect_sorted_unique_lines main_conflict_path_list conflict_paths "$main_worktree"
  collect_sorted_unique_lines source_dirty_path_list dirty_paths "$source_worktree"
  collect_sorted_unique_lines main_dirty_path_list dirty_paths "$main_worktree"
  collect_sorted_unique_lines incoming_path_list incoming_paths "$source_worktree" "$target_ref"
  collect_lines incoming_commit_list incoming_commits "$source_worktree" "$target_ref"
  collect_overlapping_paths main_dirty_path_list incoming_path_list overlap_path_list

  source_conflicts="no"
  if [ "${#source_conflict_path_list[@]}" -gt 0 ]; then
    source_conflicts="yes"
  fi

  main_conflicts="no"
  if [ "${#main_conflict_path_list[@]}" -gt 0 ]; then
    main_conflicts="yes"
  fi

  source_clean="yes"
  if [ "${#source_dirty_path_list[@]}" -gt 0 ]; then
    source_clean="no"
  fi

  source_is_target_worktree="no"
  if [ "$source_worktree" = "$main_worktree" ]; then
    source_is_target_worktree="yes"
  fi

  source_on_target_branch="no"
  if [ -n "$source_branch" ] && [ "$source_branch" = "$target_branch" ]; then
    source_on_target_branch="yes"
  fi

  needs_main_merge="no"
  can_fast_forward_main="yes"
  if [ "$merge_base" != "$target_head" ]; then
    needs_main_merge="yes"
    can_fast_forward_main="no"
  fi

  blocking_reason_list=()
  if [ "$source_is_target_worktree" = "yes" ]; then
    blocking_reason_list+=("source_is_target_worktree")
  fi
  if [ "$source_on_target_branch" = "yes" ]; then
    blocking_reason_list+=("source_on_target_branch")
  fi
  if [ "$source_conflicts" = "yes" ]; then
    blocking_reason_list+=("source_has_conflicts")
  fi
  if [ "$source_clean" = "no" ]; then
    blocking_reason_list+=("source_worktree_not_clean")
  fi
  if [ "$main_conflicts" = "yes" ]; then
    blocking_reason_list+=("target_has_conflicts")
  fi
  if [ "${#overlap_path_list[@]}" -gt 0 ]; then
    blocking_reason_list+=("target_dirty_overlap")
  fi

  can_finish_now="yes"
  if [ "${#blocking_reason_list[@]}" -gt 0 ]; then
    can_finish_now="no"
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
fi

collect_preflight

if [ "$subcommand" = "inspect" ]; then
  print_kv source_worktree "$source_worktree"
  print_kv main_worktree "$main_worktree"
  print_kv current_branch "${source_branch:-DETACHED}"
  print_kv source_head "$source_head"
  print_kv target_ref "$target_ref"
  print_kv target_head "$target_head"
  print_kv merge_base "$merge_base"
  print_kv detached_head "$detached"
  print_kv needs_temp_branch "$needs_temp_branch"
  print_kv source_is_target_worktree "$source_is_target_worktree"
  print_kv source_on_target_branch "$source_on_target_branch"
  print_kv source_clean "$source_clean"
  print_kv source_conflicts "$source_conflicts"
  print_kv main_conflicts "$main_conflicts"
  print_kv source_ahead_count "$source_ahead_count"
  print_kv source_behind_count "$source_behind_count"
  print_kv needs_main_merge "$needs_main_merge"
  print_kv can_fast_forward_main "$can_fast_forward_main"
  print_kv can_finish_now "$can_finish_now"
  print_list incoming_commit "${incoming_commit_list[@]}"
  print_list source_conflict_path "${source_conflict_path_list[@]}"
  print_list target_conflict_path "${main_conflict_path_list[@]}"
  print_list source_dirty_path "${source_dirty_path_list[@]}"
  print_list main_dirty_path "${main_dirty_path_list[@]}"
  print_list incoming_path "${incoming_path_list[@]}"
  print_list overlap_path "${overlap_path_list[@]}"
  print_list blocking_reason "${blocking_reason_list[@]}"
  exit 0
fi

[ "$source_worktree" != "$main_worktree" ] || die "refusing to run from the '$target_branch' worktree"

if [ -n "$source_branch" ] && [ "$source_branch" = "$target_branch" ]; then
  die "refusing to finish a source worktree already attached to '$target_branch'"
fi

if [ "$source_conflicts" = "yes" ]; then
  die "source worktree has unresolved merge conflicts; resolve them in the source worktree, commit, and rerun finish"
fi

if [ "$source_clean" = "no" ]; then
  die "source worktree is not clean; commit or remove outstanding changes first"
fi

if [ "$main_conflicts" = "yes" ]; then
  die "target '$target_branch' worktree has unresolved merge conflicts"
fi

if [ "$needs_main_merge" = "yes" ]; then
  if ! git -C "$source_worktree" merge --no-edit "$target_ref"; then
    die "merging local '$target_branch' into the source worktree conflicted; resolve the conflicts in the source worktree, commit, and rerun finish"
  fi
fi

if [ -n "$(conflict_paths "$source_worktree")" ]; then
  die "source worktree still has unresolved merge conflicts after merging '$target_branch'; resolve them in the source worktree, commit, and rerun finish"
fi

collect_sorted_unique_lines main_dirty_path_list dirty_paths "$main_worktree"
collect_sorted_unique_lines incoming_path_list incoming_paths "$source_worktree" "$target_ref"
collect_overlapping_paths main_dirty_path_list incoming_path_list overlap_path_list

if [ "${#overlap_path_list[@]}" -gt 0 ]; then
  overlap_csv=$(IFS=,; printf '%s' "${overlap_path_list[*]}")
  die "target '$target_branch' worktree has dirty files that conflict with incoming changes: $overlap_csv"
fi

integration_commit=$(current_head "$source_worktree")

if ! git -C "$main_worktree" merge --ff-only "$integration_commit"; then
  die "fast-forwarding '$target_branch' to '$integration_commit' failed"
fi

printf 'source_worktree=%s\n' "$source_worktree"
printf 'main_worktree=%s\n' "$main_worktree"
printf 'integration_commit=%s\n' "$integration_commit"
printf 'source_worktree_removed=no\n'
printf 'temporary_branch_created=no\n'
printf 'status=merged\n'
