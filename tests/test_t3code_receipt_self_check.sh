#!/usr/bin/env bash
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/state/receipts" "$tmp/bin"
cat > "$tmp/bin/podman" <<'SH'
#!/usr/bin/env bash
printf '%s\n' 'sha256:unreceipted'
SH
cat > "$tmp/bin/systemd-cat" <<'SH'
#!/usr/bin/env bash
cat >> "$INCIDENTS"
SH
chmod +x "$tmp/bin/podman" "$tmp/bin/systemd-cat"
export STATE_DIR="$tmp/state" PODMAN_BIN="$tmp/bin/podman" JQ_BIN=jq INCIDENTS="$tmp/incidents"
export PATH="$tmp/bin:$PATH"

bash "$root/packages/t3code/receipt-self-check.sh"
[[ $(wc -l < "$tmp/incidents") == 1 ]]
bash "$root/packages/t3code/receipt-self-check.sh"
[[ $(wc -l < "$tmp/incidents") == 1 ]]
[[ -e "$tmp/state/unreceipted-start-unreceipted" ]]

jq -n '{image_id:"unreceipted",deployment_id:"deployment-accepted",
  candidate_name:"t3code-candidate-accepted",live_before:{id:"candidate"},live_after:{id:"candidate"},
  checks:{app_ready:true,provider_turn:true,agent_cli:true,skills:true,desktop_transport:true}}' \
  > "$tmp/state/receipts/accepted.json"
bash "$root/packages/t3code/receipt-self-check.sh"
[[ $(wc -l < "$tmp/incidents") == 1 ]]
echo 'Startup receipt self-check: missing receipt emits one alarm and never blocks service startup.'
