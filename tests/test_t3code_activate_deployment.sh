#!/usr/bin/env bash
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
printf '%s\n' "$tmp/window" > "$tmp/window-config"
# First installation: the activation bootstrap creates missing paths before
# the deployment hook. Re-running it must preserve an existing lock inode.
export WINDOW_INTENT_HELPER="$root/packages/t3code/window-intent.sh"
export WINDOW_CONFIG="$tmp/window-config"
bash "$root/packages/t3code/window-bootstrap.sh"
inode=$(stat -c %i "$tmp/window/window.lock")
bash "$root/packages/t3code/window-bootstrap.sh"
[[ $(stat -c %i "$tmp/window/window.lock") == "$inode" ]]
export WINDOW_CONFIG="$tmp/window-config" WINDOW_INTENT_HELPER="$root/packages/t3code/window-intent.sh"
mkdir -p "$tmp/bin" "$tmp/state"
printf '%s\n' old-deployment > "$tmp/state/desired"
printf '%s\n' old-inputs > "$tmp/state/desired-inputs"
: > "$tmp/events"
printf 'secret=fixture\n' > "$tmp/secrets"

cat > "$tmp/bin/systemctl" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "$EVENTS"
SH
chmod +x "$tmp/bin/systemctl"
export EVENTS="$tmp/events" STATE_DIR="$tmp/state" DEPLOYMENT_ID=new-deployment
export AGENT_REVISION=new-agent TOOLING_PATH=/nix/store/expected-tooling \
  PROVIDER_SECRETS_FILE="$tmp/secrets" SYSTEMCTL_BIN="$tmp/bin/systemctl"

# Hold the deploy lock as an acceptance/restart would. Activation must wait and
# leave the current target intact until the deploy completes.
exec 8>"$STATE_DIR/deploy.lock"
flock -x 8
cp "$root/packages/t3code/activate-deployment.sh" "$tmp/fixture-activation-writer"
bash "$tmp/fixture-activation-writer" &
activation_pid=$!
for _ in $(seq 1 40); do
  [[ $(cat "$STATE_DIR/desired") == old-deployment ]] || break
  sleep 0.05
done
[[ $(cat "$STATE_DIR/desired") == old-deployment ]]
[[ ! -s "$EVENTS" ]]
flock -u 8
wait "$activation_pid"

[[ $(cat "$STATE_DIR/desired") == new-deployment ]]
# The recorded expectation must include the tooling path, the value the
# acceptance gate compares against the loaded agent.
[[ $(cat "$STATE_DIR/desired-inputs") == "agent=new-agent secret_sha256=$(sha256sum "$PROVIDER_SECRETS_FILE" | cut -d ' ' -f1) tooling=/nix/store/expected-tooling" ]]
[[ $(sed -n '1p' "$EVENTS") == daemon-reload ]]
[[ $(sed -n '2p' "$EVENTS") == 'start --no-block ghostship-t3code-deploy.service' ]]
echo 'Activation shell proof: activation serializes desired writes, reloads units, then starts deployment.'
