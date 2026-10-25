#!/usr/bin/env bash
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
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
export AGENT_REVISION=new-agent PROVIDER_SECRETS_FILE="$tmp/secrets" SYSTEMCTL_BIN="$tmp/bin/systemctl"

# Hold the deploy lock as an acceptance/restart would. Activation must wait and
# leave the current target intact until the deploy completes.
exec 8>"$STATE_DIR/deploy.lock"
flock -x 8
bash "$root/packages/t3code/activate-deployment.sh" &
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
[[ $(cat "$STATE_DIR/desired-inputs") == "agent=new-agent secret_inode=$(stat -Lc '%i' "$PROVIDER_SECRETS_FILE")" ]]
[[ $(sed -n '1p' "$EVENTS") == daemon-reload ]]
[[ $(sed -n '2p' "$EVENTS") == 'start --no-block ghostship-t3code-deploy.service' ]]
echo 'Activation shell proof: activation serializes desired writes, reloads units, then starts deployment.'
