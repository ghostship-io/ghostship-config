#!/usr/bin/env bash
# T3 Code Activity Probe
# Stable exit contract:
#   0 = definitely idle
#   1 = active
#   2 = unknown / cannot determine

set -u

ADAPTER="${T3CODE_ACTIVITY_PROBE_ADAPTER:-auto}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE="${T3CODE_STATE_DB:-${T3CODE_HOME:+$T3CODE_HOME/userdata/state.sqlite}}"
STATE="${STATE:-$HOME/.t3/userdata/state.sqlite}"
# T3 Code 2 migrates state.sqlite into statev2.sqlite beside it.
V2="$(dirname "$STATE")/statev2.sqlite"
if [ "$ADAPTER" = auto ]; then
  if [ -f "$V2" ]; then ADAPTER=v2-sqlite; else ADAPTER=v1-sqlite; fi
fi

case "$ADAPTER" in
  v1-sqlite)
    exec node "$DIR/probe-v1-sqlite.cjs" "$@"
    ;;
  v2-sqlite)
    T3CODE_STATE_DB="$V2" exec node "$DIR/probe-v2-sqlite.cjs" "$@"
    ;;
  *)
    echo "unknown activity probe adapter: $ADAPTER" >&2
    exit 2
    ;;
esac
