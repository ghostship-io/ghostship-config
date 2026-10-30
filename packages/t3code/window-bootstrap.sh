set -euo pipefail
# shellcheck disable=SC1090
source "${WINDOW_INTENT_HELPER:?}"
window_root
[[ ! -L $WINDOW_ROOT ]] || { echo 'window root is a symlink' >&2; exit 1; }
install -d -m 0700 "$WINDOW_ROOT"
[[ ! -L $WINDOW_ROOT/window.lock ]] || { echo 'window lock is a symlink' >&2; exit 1; }
# Append opens an existing inode without truncating or replacing a live lock.
: >> "$WINDOW_ROOT/window.lock"
[[ -f $WINDOW_ROOT/window.lock ]] || exit 1
