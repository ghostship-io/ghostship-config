#!/bin/sh
# Keep the Go coordinator uid's read access effective on the model evidence
# ledger.
# The recorder creates each ledger 0600, and a 0600 create resets the inherited
# ACL mask to none, cancelling the named read entry. Apply the entry and its
# mask to whichever file the ledger path currently names.
# Re-applying an ACL that is already effective changes the file, which can look
# like another trigger to the path unit, so a correct ledger is left untouched.
set -eu
evidence=${1:?model evidence ledger path is required}
setfacl=${2:?setfacl path is required}
getfacl=${3:?getfacl path is required}
[ -f "$evidence" ] || exit 0
if acl=$("$getfacl" -c --absolute-names "$evidence" 2>/dev/null); then
  entry=$(printf '%s\n' "$acl" | awk -F: '$1 == "user" && $2 == "62033" { print $3; exit }')
  mask=$(printf '%s\n' "$acl" | awk -F: '$1 == "mask" { print $3; exit }')
  case "$entry" in
    *r*)
      case "$mask" in
        *r*) exit 0 ;;
      esac
      ;;
  esac
fi
exec "$setfacl" -m u:62033:r,m::r "$evidence"
