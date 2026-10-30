#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
export REAL_SYNC
REAL_SYNC=$(command -v sync)
cat > "$tmp/sync" <<'SH'
#!/usr/bin/env bash
sleep 2
exec "$REAL_SYNC" "$@"
SH
chmod +x "$tmp/sync"
PATH="$tmp:$PATH" bash "$root/tests/test_t3code_window_lock.sh"
