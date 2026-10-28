set -euo pipefail

: "${STATE_DIR:?}"
: "${DEPLOYMENT_ID:?}"
: "${AGENT_REVISION:?}"
: "${TOOLING_PATH:?}"
: "${PROVIDER_SECRETS_FILE:?}"
: "${SYSTEMCTL_BIN:?}"

install -d -m 0700 "$STATE_DIR"
exec 9>"$STATE_DIR/deploy.lock"
flock -x 9

printf '%s\n' "$DEPLOYMENT_ID" > "$STATE_DIR/desired.tmp"
mv -f "$STATE_DIR/desired.tmp" "$STATE_DIR/desired"
secret_inode=$(stat -Lc '%i' "$PROVIDER_SECRETS_FILE")
# Record every accepted input the deployment gate later compares, including the
# tooling path. Without it the enqueued expectation omitted the exact value the
# gate checks, so a stale tooling pointer was invisible until acceptance failed.
printf 'agent=%s secret_inode=%s tooling=%s\n' "$AGENT_REVISION" "$secret_inode" "$TOOLING_PATH" \
  > "$STATE_DIR/desired-inputs.tmp"
mv -f "$STATE_DIR/desired-inputs.tmp" "$STATE_DIR/desired-inputs"
rm -f "$STATE_DIR/restart.pending" "$STATE_DIR/restart.pending.tmp"

# NixOS updates unit links before this activation hook. Load those units before
# starting the deployer, while the deployment lock excludes an older run.
"$SYSTEMCTL_BIN" daemon-reload
"$SYSTEMCTL_BIN" start --no-block ghostship-t3code-deploy.service
