#!/usr/bin/env bash
# One predicate for the candidate receipt claims: the credential-free fixture
# turn (new) or the legacy provider turn; neither is refused.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
export JQ_BIN=jq
# shellcheck source=../packages/t3code/receipt-checks.sh
. "$root/packages/t3code/receipt-checks.sh"
mk() {
  jq -n --argjson fx "$1" --argjson pv "$2" \
    '{deployment_id:"d",checks:{app_ready:true,agent_cli:true,skills:true,
      desktop_cli:true,fixture_turn:$fx,provider_turn:$pv}}' > "$tmp/receipt.json"
}
mk true null
receipt_checks_ok "$tmp/receipt.json" || { echo 'fixture-only receipt rejected' >&2; exit 1; }
mk null true
receipt_checks_ok "$tmp/receipt.json" || { echo 'legacy-only receipt rejected' >&2; exit 1; }
mk null null
if receipt_checks_ok "$tmp/receipt.json"; then echo 'receipt without a turn claim accepted' >&2; exit 1; fi
mk false null
if receipt_checks_ok "$tmp/receipt.json"; then echo 'fixture_turn false accepted' >&2; exit 1; fi
echo 'Receipt-check claim fixture passed.'
