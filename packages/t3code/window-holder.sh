#!/usr/bin/env bash
# Hold a release window open: take both candidate locks, then publish our PID.
#
# This lives in its own packaged script because the PID must be written by the
# process that owns it. When the same shell text was inlined into the
# release-window generator, `$$` reached the built wrapper as a bare `$`, so
# holder.ready recorded "$" instead of a PID and the window never became ready.
set -euo pipefail

if [[ $# -ne 3 ]]; then
  printf 'usage: %s LOCK_CANDIDATE LOCK_HARDENING WINDOW_DIR\n' "${0##*/}" >&2
  exit 2
fi

lock_candidate=$1
lock_hardening=$2
dir=$3

exec 7<>"$lock_candidate" 9<>"$lock_hardening"
flock -w 10 7
flock -w 10 9

printf '%s\n' "$$" > "$dir/holder.ready.tmp"
mv "$dir/holder.ready.tmp" "$dir/holder.ready"
exec sleep infinity
