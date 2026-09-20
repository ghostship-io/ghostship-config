#!/usr/bin/env bash
# T3 Code Activity Probe
# Stable exit contract:
#   0 = definitely idle
#   1 = active
#   2 = unknown / cannot determine

set -u

ADAPTER="${T3CODE_ACTIVITY_PROBE_ADAPTER:-v1-sqlite}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

case "$ADAPTER" in
  v1-sqlite)
    exec node "$DIR/probe-v1-sqlite.cjs" "$@"
    ;;
  v2-api)
    # Placeholder for future V2 orchestration status API
    if [ -n "${T3CODE_API_URL:-}" ]; then
      exit 2
    else
      exec node "$DIR/probe-v1-sqlite.cjs" "$@"
    fi
    ;;
  *)
    echo "unknown activity probe adapter: $ADAPTER" >&2
    exit 2
    ;;
esac
