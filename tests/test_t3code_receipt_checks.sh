#!/usr/bin/env bash
# One predicate for the receipt: mechanical identity only. Behavioural claims
# (the candidate turn, skills, desktop) are not part of activation, so a receipt
# that carries them (written before this change) still reads as accepted, while
# a receipt missing the mechanical identity is refused.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
export JQ_BIN=jq
# shellcheck source=../packages/t3code/receipt-checks.sh
. "$root/packages/t3code/receipt-checks.sh"
sha=$(printf 'secret' | sha256sum | cut -d ' ' -f 1)
mechanical() {
  jq -n --arg s "$sha" --argjson extra "$1" '
    {schema:2,deployment_id:"d",image_id:"sha256:abc",
     candidate_name:"t3code-candidate-fixture",agent_revision:"rev",agent_path:"/nix/store/tools",
     provider_secret_sha256:$s,verified:true} + $extra' > "$tmp/receipt.json"
}
mechanical '{}'
receipt_checks_ok "$tmp/receipt.json" || { echo 'the mechanical receipt was rejected' >&2; exit 1; }
# A receipt written before the cut carries behavioural checks: still accepted.
mechanical '{"checks":{"app_ready":true,"fixture_turn":true}}'
receipt_checks_ok "$tmp/receipt.json" || { echo 'a legacy behavioural receipt was rejected' >&2; exit 1; }
# The mechanical identity is required.
mechanical '{"provider_secret_sha256":""}'
if receipt_checks_ok "$tmp/receipt.json"; then echo 'a receipt without the secret digest was accepted' >&2; exit 1; fi
mechanical '{"candidate_name":"something-else"}'
if receipt_checks_ok "$tmp/receipt.json"; then echo 'a receipt with a foreign candidate name was accepted' >&2; exit 1; fi
mechanical '{"verified":false}'
if receipt_checks_ok "$tmp/receipt.json"; then echo 'an unverified mechanical receipt was accepted' >&2; exit 1; fi
echo 'Receipt-check fixture passed: mechanical identity required, legacy behavioural receipts readable.'
