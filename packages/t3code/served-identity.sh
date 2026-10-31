#!/bin/sh
# Report which standalone T3 app release the container actually serves.
#
# One implementation shared by every reader (candidate acceptance, deploy-image,
# release-window), because three copies of "which app is this" is how they drift
# apart. The image bakes a release and the persisted tree may hold a newer one,
# so the answer is the monotonic maximum of the two.
#
#   usage: served-identity.sh [--root PREFIX]
#
# Prints one JSON object and exits 0, or prints nothing and exits non-zero when
# the identity is unknown. Unknown must never be reported as baked or persisted
# with a guessed version: callers refuse on non-zero.
set -eu

root=""
while [ $# -gt 0 ]; do
  case $1 in
    --root) root=${2:?--root needs a prefix}; shift 2 ;;
    --root=*) root=${1#--root=}; shift ;;
    *) echo "usage: served-identity.sh [--root PREFIX]" >&2; exit 2 ;;
  esac
done

baked_dir="$root/usr/share/t3code-app"
home_dir="${T3CODE_HOME_PREFIX:-$root/home/t3code}"
current="$home_dir/.local/share/t3code-tools/t3/current"
releases="$home_dir/.local/share/t3code-tools/t3/releases"

version_pattern='^[0-9]+\.[0-9]+\.[0-9]+$'
digest_pattern='^[0-9a-f]{64}$'

# --- baked -------------------------------------------------------------------
baked_version="" baked_digest=""
if [ -f "$baked_dir/VERSION" ] && [ ! -L "$baked_dir/VERSION" ]; then
  baked_version=$(tr -d '[:space:]' < "$baked_dir/VERSION")
  printf '%s\n' "$baked_version" | grep -Eq "$version_pattern" || baked_version=""
fi
if [ -f "$baked_dir/DIGEST" ] && [ ! -L "$baked_dir/DIGEST" ]; then
  baked_digest=$(tr -d '[:space:]' < "$baked_dir/DIGEST")
  printf '%s\n' "$baked_digest" | grep -Eq "$digest_pattern" || baked_digest=""
fi
if [ -n "$baked_version" ] && [ -z "$baked_digest" ]; then
  echo 'served-identity: baked app has no usable digest' >&2; exit 1
fi

# --- persisted ---------------------------------------------------------------
persisted_version="" persisted_digest="" persisted_leaf=""
if [ -L "$current" ]; then
  target=$(readlink -f "$current" 2>/dev/null || true)
  case $target in
    "$releases"/*) persisted_leaf=${target##*/} ;;
    *) echo 'served-identity: persisted current points outside releases' >&2; exit 1 ;;
  esac
  # A promoted identity is "<version>" or "<version>-<sha256>".
  case $persisted_leaf in
    *-[0-9a-f][0-9a-f]*) persisted_digest=${persisted_leaf##*-} ;;
  esac
  persisted_version=${persisted_leaf%%-*}
  printf '%s\n' "$persisted_version" | grep -Eq "$version_pattern" || {
    echo 'served-identity: persisted release has no stable version' >&2; exit 1;
  }
  [ -z "$persisted_digest" ] || printf '%s\n' "$persisted_digest" | grep -Eq "$digest_pattern" || {
    echo 'served-identity: persisted release has a malformed digest' >&2; exit 1;
  }
fi

# --- selection: monotonic max(baked, persisted) ------------------------------
# A persisted release is served only when it is at least the baked one, so a
# stale persisted tree can never displace the app the image shipped.
if [ -n "$persisted_version" ]; then
  newest=$(printf '%s\n%s\n' "$baked_version" "$persisted_version" | sort -V | tail -n 1)
  if [ -n "$baked_version" ] && [ "$newest" = "$baked_version" ] && [ "$persisted_version" != "$baked_version" ]; then
    printf '{"source":"baked","version":"%s","digest":"%s"}\n' "$baked_version" "$baked_digest"
    exit 0
  fi
  if [ -n "$baked_version" ] && [ "$persisted_version" = "$baked_version" ]; then
    # Same version: prefer the persisted one, which carries a verified digest.
    :
  fi
  printf '{"source":"persisted","version":"%s","digest":"%s"}\n' "$persisted_version" "${persisted_digest:-}"
  exit 0
fi

if [ -n "$baked_version" ]; then
  printf '{"source":"baked","version":"%s","digest":"%s"}\n' "$baked_version" "$baked_digest"
  exit 0
fi

echo 'served-identity: no baked release and no persisted release' >&2
exit 1
