#!/usr/bin/env bash
# Point the container's tooling link at the declared accepted target.
#
# The link lives in container-writable home state, so it can outlive the
# closure that created it. Seeding it only when absent left a stale pointer in
# place after the tooling derivation changed, and the deployment acceptance gate
# then correctly refused the restart: the loaded agent was not the accepted one.
#
# The replacement is a same-directory rename: a staged link is created beside
# the live one and renamed over it. A concurrent reader therefore observes
# either the previous target or the new target, never an absent link. A target
# that is not a usable directory is refused before anything is staged, so a bad
# input leaves the previous usable pointer in place.
set -euo pipefail

if [[ $# -ne 2 ]]; then
  printf 'usage: %s TARGET LINK\n' "${0##*/}" >&2
  exit 2
fi

target=$1
link=$2

# Refuse an unusable target first: the running container keeps working on the
# tooling it already has.
if [[ ! -d $target ]]; then
  printf 'tooling target is not a directory: %s\n' "$target" >&2
  exit 1
fi

# Already pointing at the accepted target: nothing to do, and nothing is
# rewritten, so a repeated activation is a no-op.
if [[ -L $link ]] && [[ $(readlink -- "$link") == "$target" ]]; then
  exit 0
fi

staged="$link.new.$$"
trap 'rm -f -- "$staged"' EXIT
ln -sfn -- "$target" "$staged"
mv -Tf -- "$staged" "$link"
trap - EXIT
