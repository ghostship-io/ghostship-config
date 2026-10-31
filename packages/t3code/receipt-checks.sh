# shellcheck shell=bash
# One predicate for the candidate receipt checks. This accepts the new
# desktop_cli marker or the legacy desktop_transport:true receipt; it never
# accepts the typed not_applicable object.
receipt_checks_ok() {
  "${JQ_BIN:?}" -e '
    ([.checks.app_ready, .checks.provider_turn, .checks.agent_cli, .checks.skills] | all(. == true))
    and ((.checks.desktop_cli == true)
         or ((.checks.desktop_cli == null) and (.checks.desktop_transport == true)))
  ' "$1" >/dev/null 2>&1
}

# The app release the running container actually serves, through the image's
# single selector. Unknown fails: a receipt never matches an app nobody named.
served_app_release() {
  local target=${PODMAN_TARGET:-t3code} payload version digest
  payload=$("${PODMAN_BIN:?}" exec "$target" /usr/share/t3code/served-identity.sh 2>/dev/null) || return 1
  version=$("${JQ_BIN:?}" -er '.served.version // empty' <<<"$payload" 2>/dev/null) || return 1
  digest=$("${JQ_BIN}" -r '.served.digest // ""' <<<"$payload" 2>/dev/null) || return 1
  [[ $version =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || return 1
  [[ -z $digest || $digest =~ ^[0-9a-f]{64}$ ]] || return 1
  if [[ -n $digest ]]; then printf '%s+%s\n' "$version" "$digest"; else printf '%s\n' "$version"; fi
}
