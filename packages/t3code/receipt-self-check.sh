set -euo pipefail

: "${STATE_DIR:?}"
: "${PODMAN_BIN:?}"
: "${JQ_BIN:?}"

image_id=$("$PODMAN_BIN" inspect t3code --format '{{.Image}}' 2>/dev/null || true)
[[ -n "$image_id" ]] || exit 0
image_id=${image_id#sha256:}
for receipt in "$STATE_DIR"/receipts/*.json; do
  [[ -f "$receipt" ]] || continue
  if "$JQ_BIN" -e --arg image "$image_id" \
    '((.image_id | sub("^sha256:"; "")) == $image)
     and (.deployment_id | type == "string" and length > 0)
     and (.candidate_name | type == "string" and startswith("t3code-candidate-"))
     and (.live_before != null and .live_before == .live_after)
     and ([.checks.app_ready, .checks.provider_turn, .checks.agent_cli,
           .checks.skills, .checks.desktop_transport] | all(. == true))' \
    "$receipt" >/dev/null 2>&1; then
    exit 0
  fi
done

incident="$STATE_DIR/unreceipted-start-$image_id"
if [[ ! -e "$incident" ]]; then
  install -d -m 0700 "$STATE_DIR"
  : > "$incident"
  chmod 0600 "$incident"
  printf '%s\n' "T3 Code started image sha256:$image_id without a matching PASS candidate-acceptance receipt" \
    | systemd-cat -t t3code-receipt-check -p err
fi
exit 0
