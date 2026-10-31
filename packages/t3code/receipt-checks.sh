# shellcheck shell=bash
# One predicate for the candidate receipt checks. This accepts the new
# desktop_cli marker or the legacy desktop_transport:true receipt; it never
# accepts the typed not_applicable object.
receipt_checks_ok() {
  "${JQ_BIN:?}" -e '
    ([.checks.app_ready, .checks.agent_cli, .checks.skills] | all(. == true))
    and ((.checks.fixture_turn == true) or (.checks.provider_turn == true))
    and ((.checks.desktop_cli == true)
         or ((.checks.desktop_cli == null) and (.checks.desktop_transport == true)))
  ' "$1" >/dev/null 2>&1
}
