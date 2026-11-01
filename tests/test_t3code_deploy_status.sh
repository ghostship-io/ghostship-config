#!/usr/bin/env bash
# The read-only deployment status: coherent digest and legacy tuples, known
# mismatches, and UNKNOWN inputs. No host state, no podman, no T3.
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
status="$root/packages/t3code/deploy-status.sh"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
export JQ_BIN=jq

id=$(printf '%064d' 3)
other=$(printf '%064d' 4)
image=$(printf '%064d' 2)
digest=$(printf 'a%.0s' {1..64})
tooling=/nix/store/t3code-tools

receipt() {
  local dir=$1 secret_field=$2 secret_value=$3 checks=${4:-true}
  "$JQ_BIN" -n --arg d "$id" --arg i "$image" --arg p "$tooling" \
    --arg field "$secret_field" --arg value "$secret_value" --argjson checks "$checks" \
    '{deployment_id:$d,image_id:$i,candidate_name:"t3code-candidate-fixture",
      agent_revision:"agent-rev",agent_path:$p,live_before:{id:"live"},live_after:{id:"live"},
      checks:{app_ready:true,provider_turn:$checks,agent_cli:true,skills:true,desktop_cli:true},
      ($field):$value}'
}

inputs() {
  local dir=$1 secret_field=$2 secret_value=$3 path=${4:-$tooling}
  "$JQ_BIN" -n --arg d "$id" --arg p "$path" --arg field "$secret_field" --arg value "$secret_value" \
    '{deployment_id:$d,agent_revision:"agent-rev",agent_path:$p,($field):$value}'
}

coherent() {
  local dir=$1 field=$2 value=$3 line_field=$4 line_value=$5
  mkdir -p "$dir/receipts"
  printf '%s\n' "$id" > "$dir/desired"
  printf '%s\n' "$id" > "$dir/applied"
  printf 'agent=agent-rev %s=%s tooling=%s\n' "$line_field" "$line_value" "$tooling" > "$dir/applied-inputs"
  printf 'agent=agent-rev %s=%s tooling=%s\n' "$line_field" "$line_value" "$tooling" > "$dir/desired-inputs"
  receipt "$dir" "$field" "$value" > "$dir/receipts/$id.json"
  inputs "$dir" "$field" "$value" > "$dir/deployed-inputs.json"
}

run_status() {
  local dir=$1
  set +e
  out=$("$status" --state "$dir" 2>"$tmp/error")
  rc=$?
  set -e
}

# 1. Coherent digest tuple.
coherent "$tmp/digest" provider_secret_sha256 "$digest" secret_sha256 "$digest"
run_status "$tmp/digest"
[[ $rc == 0 ]]
"$JQ_BIN" -e --arg d "$id" --arg s "$digest" \
  '.state == "coherent" and .deployment == $d and .secret_evidence == "digest" and .secret_sha256 == $s' <<<"$out" >/dev/null

# 2. Coherent legacy tuple: inode-only receipts and applied input, with the
# host and container inodes deliberately different.
coherent "$tmp/legacy" provider_secret_inode "1" secret_inode "2"
"$JQ_BIN" -n --arg id "$id" --arg s "50203924" \
  '{deployment_id:$id,agent_revision:"agent-rev",agent_path:"'$tooling'",provider_secret_inode:$s}' > "$tmp/legacy/deployed-inputs.json"
run_status "$tmp/legacy"
[[ $rc == 0 ]]
"$JQ_BIN" -e '.state == "coherent" and .secret_evidence == "legacy-inode" and .secret_sha256 == null' <<<"$out" >/dev/null

# 3. desired and applied differ: the 329 hybrid.
cp -R "$tmp/digest" "$tmp/split"
printf '%s\n' "$other" > "$tmp/split/desired"
run_status "$tmp/split"
[[ $rc == 1 ]]
"$JQ_BIN" -e '.state == "mismatch" and .desired != .applied' <<<"$out" >/dev/null

# 4. Failed receipt checks.
cp -R "$tmp/digest" "$tmp/checks"
receipt "$tmp/checks" provider_secret_sha256 "$digest" false > "$tmp/checks/receipts/$id.json"
run_status "$tmp/checks"
[[ $rc == 1 ]]

# 5. Deployed inputs disagree with the receipt.
cp -R "$tmp/digest" "$tmp/inputs"
inputs "$tmp/inputs" provider_secret_sha256 "$digest" /nix/store/other-tooling > "$tmp/inputs/deployed-inputs.json"
run_status "$tmp/inputs"
[[ $rc == 1 ]]

# 6. Missing receipt.
cp -R "$tmp/digest" "$tmp/missing"
rm "$tmp/missing/receipts/$id.json"
run_status "$tmp/missing"
[[ $rc == 77 ]]

# 7. Malformed receipt.
cp -R "$tmp/digest" "$tmp/malformed"
printf '{not json\n' > "$tmp/malformed/receipts/$id.json"
run_status "$tmp/malformed"
[[ $rc == 77 ]]

# 8. Unreadable input.
cp -R "$tmp/digest" "$tmp/unreadable"
chmod 000 "$tmp/unreadable/applied-inputs"
run_status "$tmp/unreadable"
[[ $rc == 77 ]]
chmod 600 "$tmp/unreadable/applied-inputs"

echo 'Deploy-status fixture passed: coherent digest and legacy tuples pass; mismatch and failed checks fail; missing, malformed and unreadable are UNKNOWN.'
