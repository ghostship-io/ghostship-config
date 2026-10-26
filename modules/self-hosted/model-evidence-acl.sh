#!/bin/sh
# Keep the Go coordinator uid's read access on the model evidence ledger.
# The recorder creates each ledger 0600, and a 0600 create resets the inherited
# ACL mask to none, cancelling the named read entry. Apply the entry and its
# mask to whichever file the ledger path currently names.
set -eu
evidence=${1:?model evidence ledger path is required}
setfacl=${2:?setfacl path is required}
[ -f "$evidence" ] || exit 0
exec "$setfacl" -m u:62033:r,m::r "$evidence"
