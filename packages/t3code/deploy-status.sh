#!/bin/sh
# Read-only status for the T3 deployment tuple.
#
#   usage: deploy-status.sh [--state DIR]
#
# Run on the host as root before any recovery decision, for example:
#   sudo JQ_BIN=jq /path/to/packages/t3code/deploy-status.sh \
#        --state /var/lib/ghostship/t3code-deployment
# Until the deploy status entry is wired, run it from the checked-out
# packages/t3code directory (or install that directory). It only reads files.
#
# Prints one JSON object and exits 0 for a coherent tuple, 1 for a known
# mismatch, 77 for UNKNOWN (missing, unreadable or malformed input). It never
# guesses a tuple and never writes.
#
# Field names and the accepted-receipt predicate are the ones the deploy path
# and the release window already use:
#   deploy-image.sh:155,164-171   receipt identity and provider secret
#   receipt-checks.sh             the only accepted-receipt predicate
set -eu

: "${JQ_BIN:=jq}"

state=/var/lib/ghostship/t3code-deployment
while [ $# -gt 0 ]; do
  case $1 in
    --state) state=${2:?--state needs a directory}; shift 2 ;;
    --state=*) state=${1#--state=}; shift ;;
    -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
    *) echo 'usage: deploy-status.sh [--state DIR]' >&2; exit 2 ;;
  esac
done

script_dir=$(unset CDPATH; cd -- "$(dirname -- "$0")" && pwd)
# shellcheck disable=SC1091
. "$script_dir/receipt-checks.sh"

unknown() {
  "$JQ_BIN" -cn --arg reason "$1" '{state:"unknown",reason:$reason}'
  exit 77
}

mismatch() {
  "$JQ_BIN" -cn --arg reason "$1" --arg desired "${desired:-}" --arg applied "${applied:-}" \
    '{state:"mismatch",reason:$reason,desired:$desired,applied:$applied}'
  exit 1
}

read_value() {
  [ -f "$1" ] && [ ! -L "$1" ] && cat "$1"
}

desired=$(read_value "$state/desired") || unknown 'desired is missing or unreadable'
applied=$(read_value "$state/applied") || unknown 'applied is missing or unreadable'
case $desired in *[!0-9a-f]*|'') unknown 'desired is not a deployment id' ;; esac
case $applied in *[!0-9a-f]*|'') unknown 'applied is not a deployment id' ;; esac
[ "${#desired}" -eq 64 ] || unknown 'desired is not a deployment id'
[ "${#applied}" -eq 64 ] || unknown 'applied is not a deployment id'
[ "$desired" = "$applied" ] || mismatch 'desired and applied differ'

id=$applied
receipt="$state/receipts/$id.json"
[ -f "$receipt" ] && [ ! -L "$receipt" ] && [ -r "$receipt" ] || unknown 'receipt is missing or unreadable'
"$JQ_BIN" -e . "$receipt" >/dev/null 2>&1 || unknown 'receipt is not valid JSON'
receipt_checks_ok "$receipt" || mismatch 'receipt checks failed'

inputs="$state/deployed-inputs.json"
[ -f "$inputs" ] && [ ! -L "$inputs" ] && [ -r "$inputs" ] || unknown 'deployed-inputs is missing or unreadable'
"$JQ_BIN" -e . "$inputs" >/dev/null 2>&1 || unknown 'deployed-inputs is not valid JSON'

receipt_id=$("$JQ_BIN" -r '.deployment_id // empty' "$receipt")
receipt_agent=$("$JQ_BIN" -r '.agent_revision // empty' "$receipt")
receipt_path=$("$JQ_BIN" -r '.agent_path // empty' "$receipt")
receipt_image=$("$JQ_BIN" -r '.image_id // empty' "$receipt")
candidate=$("$JQ_BIN" -r '.candidate_name // empty' "$receipt")
live_before=$("$JQ_BIN" -r '.live_before // empty' "$receipt")
live_after=$("$JQ_BIN" -r '.live_after // empty' "$receipt")
[ "$receipt_id" = "$id" ] || mismatch 'receipt names another deployment'
[ -n "$receipt_agent" ] && [ -n "$receipt_path" ] && [ -n "$receipt_image" ] || unknown 'receipt identity is incomplete'
case $candidate in t3code-candidate-*) ;; *) mismatch 'receipt candidate name is not accepted' ;; esac
# A receipt written after the restart legitimately has different before and
# after identities; what matters is that the recorded post-restart image is the
# receipted one.
[ -n "$live_after" ] || mismatch 'receipt live identity is missing'
recorded_image=$(printf '%s\n' "$live_after" | "$JQ_BIN" -r '.image // empty' 2>/dev/null || true)
[ "${recorded_image#sha256:}" = "${receipt_image#sha256:}" ] \
  || mismatch 'receipt live identity is not the receipted image'

applied_inputs="$state/applied-inputs"
[ -f "$applied_inputs" ] && [ ! -L "$applied_inputs" ] && [ -r "$applied_inputs" ] || unknown 'applied-inputs is missing or unreadable'
applied_line=$(cat "$applied_inputs")
applied_agent=$(printf '%s\n' "$applied_line" | sed -n 's/.*agent=\([^ ]*\).*/\1/p')
applied_tooling=$(printf '%s\n' "$applied_line" | sed -n 's/.*tooling=\([^ ]*\).*/\1/p')
applied_digest=$(printf '%s\n' "$applied_line" | sed -n 's/.*secret_sha256=\([^ ]*\).*/\1/p')
applied_inode=$(printf '%s\n' "$applied_line" | sed -n 's/.*secret_inode=\([^ ]*\).*/\1/p')
[ "$applied_agent" = "$receipt_agent" ] || mismatch 'applied agent revision differs from the receipt'
[ "$applied_tooling" = "$receipt_path" ] || mismatch 'applied tooling differs from the receipt'

inputs_id=$("$JQ_BIN" -r '.deployment_id // empty' "$inputs")
inputs_agent=$("$JQ_BIN" -r '.agent_revision // empty' "$inputs")
inputs_path=$("$JQ_BIN" -r '.agent_path // empty' "$inputs")
[ "$inputs_id" = "$id" ] || mismatch 'deployed-inputs names another deployment'
[ "$inputs_agent" = "$receipt_agent" ] || mismatch 'deployed agent revision differs from the receipt'
[ "$inputs_path" = "$receipt_path" ] || mismatch 'deployed agent path differs from the receipt'

receipt_digest=$("$JQ_BIN" -r '.provider_secret_sha256 // empty' "$receipt")
inputs_digest=$("$JQ_BIN" -r '.provider_secret_sha256 // empty' "$inputs")
receipt_inode=$("$JQ_BIN" -r '.provider_secret_inode // empty' "$receipt")
inputs_inode=$("$JQ_BIN" -r '.provider_secret_inode // empty' "$inputs")
secret_sha256=null
if [ -n "$receipt_digest" ] || [ -n "$inputs_digest" ] || [ -n "$applied_digest" ]; then
  [ -n "$receipt_digest" ] && [ "$receipt_digest" = "$inputs_digest" ] || mismatch 'provider secret digest differs between receipt and deployed inputs'
  [ -z "$applied_digest" ] || [ "$applied_digest" = "$receipt_digest" ] || mismatch 'applied secret digest differs from the receipt'
  secret_sha256=$receipt_digest
  secret_evidence=digest
elif [ -n "$receipt_inode" ] || [ -n "$inputs_inode" ] || [ -n "$applied_inode" ]; then
  # Legacy records carry the inode only. The host and container inodes differ
  # by design after a switch; the status reports the weaker evidence and never
  # compares inode numbers.
  secret_evidence=legacy-inode
else
  unknown 'provider secret identity is absent from the receipt and deployed inputs'
fi

"$JQ_BIN" -cn --arg deployment "$id" --arg image "$receipt_image" \
  --arg agent "$receipt_agent" --arg tooling "$receipt_path" \
  --arg secret_sha256 "$secret_sha256" --arg secret_evidence "$secret_evidence" \
  --arg receipt "receipts/$id.json" --arg desired "$desired" --arg applied "$applied" \
  '{state:"coherent",deployment:$deployment,image:$image,agent_revision:$agent,
    tooling:$tooling,secret_sha256:(if $secret_sha256 == "null" then null else $secret_sha256 end),
    secret_evidence:$secret_evidence,receipt:$receipt,desired:$desired,applied:$applied}'
