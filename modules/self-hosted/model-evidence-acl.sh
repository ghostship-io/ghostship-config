#!/bin/sh
# Keep the Go coordinator uid's read access effective on the model evidence
# ledger.
# The recorder creates each ledger 0600, and a 0600 create resets the inherited
# ACL mask to none, cancelling the named read entry. Apply the entry and its
# mask to whichever file the ledger path currently names.
# Re-applying an ACL that is already effective changes the file, which can look
# like another trigger to the path unit, so a correct ledger is left untouched.
# The check is shell-only: the service PATH has no external parser.
set -eu
evidence=${1:?model evidence ledger path is required}
setfacl=${2:?setfacl path is required}
getfacl=${3:?getfacl path is required}
uid=${4:-62033}
[ -f "$evidence" ] || exit 0
# Numeric ids: the host resolves the coordinator uid to a user name otherwise.
if acl=$("$getfacl" -c -n --absolute-names "$evidence" 2>/dev/null); then
  entry=""
  mask=""
  while IFS=: read -r kind id perms; do
    case "$kind" in
      user) case "$id" in "$uid") entry=$perms ;; esac ;;
      mask) mask=$perms ;;
    esac
  done <<EOF
$acl
EOF
  case "$entry" in
    *r*)
      case "$mask" in
        *r*) exit 0 ;;
      esac
      ;;
  esac
fi
exec "$setfacl" -m "u:${uid}:r,m::r" "$evidence"
