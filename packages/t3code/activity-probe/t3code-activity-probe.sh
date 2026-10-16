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
    # No verified V2 adapter exists; never fall back to stale V1 state.
    exit 2
    ;;
  *)
    echo "unknown activity probe adapter: $ADAPTER" >&2
    exit 2
    ;;
esac
