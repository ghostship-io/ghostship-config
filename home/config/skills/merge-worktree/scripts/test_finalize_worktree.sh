#!/usr/bin/env bash
set -euo pipefail

script_dir=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
script_path="$script_dir/finalize_worktree.sh"

tmp_root=$(mktemp -d)
cleanup() {
  rm -rf "$tmp_root"
}
trap cleanup EXIT

scenario_count=0

fail() {
  printf 'FAIL: %s\n' "$*" >&2
  exit 1
}

assert_contains() {
  local haystack="$1"
  local needle="$2"
  if ! grep -F -- "$needle" <<<"$haystack" >/dev/null; then
    fail "expected to find '$needle'"
  fi
}

assert_not_contains() {
  local haystack="$1"
  local needle="$2"
  if grep -F -- "$needle" <<<"$haystack" >/dev/null; then
    fail "did not expect to find '$needle'"
  fi
}

new_repo() {
  local name="$1"
  local repo="$tmp_root/$name"

  git init -b main "$repo" >/dev/null
  git -C "$repo" config user.name "Test User"
  git -C "$repo" config user.email "test@example.com"

  printf 'base\n' > "$repo/shared.txt"
  git -C "$repo" add shared.txt
  git -C "$repo" commit -m "base" >/dev/null

  printf '%s\n' "$repo"
}

run_inspect() {
  local worktree="$1"
  (
    cd "$worktree"
    "$script_path" inspect --target-branch main
  )
}

scenario_detached_no_unique_commits() {
  local repo
  repo=$(new_repo detached-clean)
  local source="$tmp_root/detached-clean-source"

  git -C "$repo" worktree add --detach "$source" HEAD >/dev/null

  local output
  output=$(run_inspect "$source")

  assert_contains "$output" "current_branch=DETACHED"
  assert_contains "$output" "source_ahead_count=0"
  assert_contains "$output" "source_behind_count=0"
  assert_contains "$output" "needs_main_merge=no"
  assert_contains "$output" "can_fast_forward_main=yes"
  assert_contains "$output" "can_finish_now=yes"
  assert_not_contains "$output" "incoming_commit="
}

scenario_branch_ahead_of_main() {
  local repo
  repo=$(new_repo branch-ahead)
  local source="$tmp_root/branch-ahead-source"

  git -C "$repo" worktree add -b feature "$source" >/dev/null
  printf 'feature\n' > "$source/feature.txt"
  git -C "$source" add feature.txt
  git -C "$source" commit -m "feature commit" >/dev/null

  local output
  output=$(run_inspect "$source")

  assert_contains "$output" "current_branch=feature"
  assert_contains "$output" "source_ahead_count=1"
  assert_contains "$output" "source_behind_count=0"
  assert_contains "$output" "needs_main_merge=no"
  assert_contains "$output" "can_fast_forward_main=yes"
  assert_contains "$output" "can_finish_now=yes"
  assert_contains "$output" "incoming_commit="
  assert_contains "$output" "incoming_path=feature.txt"
}

scenario_source_not_clean() {
  local repo
  repo=$(new_repo source-dirty)
  local source="$tmp_root/source-dirty-source"

  git -C "$repo" worktree add -b feature "$source" >/dev/null
  printf 'dirty\n' > "$source/untracked.txt"

  local output
  output=$(run_inspect "$source")

  assert_contains "$output" "source_clean=no"
  assert_contains "$output" "source_dirty_path=untracked.txt"
  assert_contains "$output" "blocking_reason=source_worktree_not_clean"
  assert_contains "$output" "can_finish_now=no"
}

scenario_source_conflicts() {
  local repo
  repo=$(new_repo source-conflicts)
  local source="$tmp_root/source-conflicts-source"

  git -C "$repo" worktree add -b feature "$source" >/dev/null
  printf 'feature\n' > "$source/shared.txt"
  git -C "$source" add shared.txt
  git -C "$source" commit -m "feature edit" >/dev/null

  printf 'main\n' > "$repo/shared.txt"
  git -C "$repo" add shared.txt
  git -C "$repo" commit -m "main edit" >/dev/null

  if git -C "$source" merge --no-edit main >/dev/null 2>&1; then
    fail "expected merge conflict in source_conflicts scenario"
  fi

  local output
  output=$(run_inspect "$source")

  assert_contains "$output" "source_conflicts=yes"
  assert_contains "$output" "source_conflict_path=shared.txt"
  assert_contains "$output" "blocking_reason=source_has_conflicts"
  assert_contains "$output" "can_finish_now=no"
}

scenario_main_dirty_without_overlap() {
  local repo
  repo=$(new_repo main-dirty-no-overlap)
  local source="$tmp_root/main-dirty-no-overlap-source"

  git -C "$repo" worktree add -b feature "$source" >/dev/null
  printf 'feature\n' > "$source/feature.txt"
  git -C "$source" add feature.txt
  git -C "$source" commit -m "feature commit" >/dev/null

  printf 'main dirty\n' > "$repo/local-only.txt"

  local output
  output=$(run_inspect "$source")

  assert_contains "$output" "main_dirty_path=local-only.txt"
  assert_not_contains "$output" "overlap_path="
  assert_not_contains "$output" "blocking_reason=target_dirty_overlap"
  assert_contains "$output" "can_finish_now=yes"
}

scenario_main_dirty_with_overlap() {
  local repo
  repo=$(new_repo main-dirty-overlap)
  local source="$tmp_root/main-dirty-overlap-source"

  git -C "$repo" worktree add -b feature "$source" >/dev/null
  printf 'feature\n' > "$source/shared.txt"
  git -C "$source" add shared.txt
  git -C "$source" commit -m "feature edit" >/dev/null

  printf 'main dirty\n' > "$repo/shared.txt"

  local output
  output=$(run_inspect "$source")

  assert_contains "$output" "main_dirty_path=shared.txt"
  assert_contains "$output" "incoming_path=shared.txt"
  assert_contains "$output" "overlap_path=shared.txt"
  assert_contains "$output" "blocking_reason=target_dirty_overlap"
  assert_contains "$output" "can_finish_now=no"
}

scenario_needs_main_merge() {
  local repo
  repo=$(new_repo needs-main-merge)
  local source="$tmp_root/needs-main-merge-source"

  git -C "$repo" worktree add -b feature "$source" >/dev/null
  printf 'feature\n' > "$source/feature.txt"
  git -C "$source" add feature.txt
  git -C "$source" commit -m "feature commit" >/dev/null

  printf 'main update\n' > "$repo/shared.txt"
  git -C "$repo" add shared.txt
  git -C "$repo" commit -m "main update" >/dev/null

  local output
  output=$(run_inspect "$source")

  assert_contains "$output" "source_ahead_count=1"
  assert_contains "$output" "source_behind_count=1"
  assert_contains "$output" "needs_main_merge=yes"
  assert_contains "$output" "can_fast_forward_main=no"
  assert_contains "$output" "can_finish_now=yes"
}

run_scenario() {
  local name="$1"
  shift
  "$@"
  scenario_count=$((scenario_count + 1))
  printf 'ok %s\n' "$name"
}

run_scenario detached_no_unique_commits scenario_detached_no_unique_commits
run_scenario branch_ahead_of_main scenario_branch_ahead_of_main
run_scenario source_not_clean scenario_source_not_clean
run_scenario source_conflicts scenario_source_conflicts
run_scenario main_dirty_without_overlap scenario_main_dirty_without_overlap
run_scenario main_dirty_with_overlap scenario_main_dirty_with_overlap
run_scenario needs_main_merge scenario_needs_main_merge

printf 'PASS: %s scenarios\n' "$scenario_count"
