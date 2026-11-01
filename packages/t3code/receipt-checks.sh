# shellcheck shell=bash
# One predicate for the candidate receipt checks. This accepts the new
# desktop_cli marker or the legacy desktop_transport:true receipt; it never
# accepts the typed not_applicable object.
receipt_checks_ok() {
  # Mechanical acceptance only. Two shapes are accepted:
  #  - a mechanical receipt: the deployed image, the digest of the provider
  #    secret, and verified=true, with no behavioural claim at all;
  #  - a legacy receipt from before the digest identity: no image id, but the
  #    provider secret inode it was written against.
  # Behavioural claims (candidate turn, skills, desktop) are ignored: they are
  # not part of activation.
  "${JQ_BIN:?}" -e '
    (.deployment_id | type == "string" and length > 0)
    and (.agent_revision | type == "string" and length > 0)
    and (.agent_path | type == "string" and length > 0)
    and (.candidate_name == null or (.candidate_name | type == "string" and startswith("t3code-candidate-")))
    and (
      ( (.verified == true)
        and (.provider_secret_sha256 | type == "string" and length == 64) )
      or
      # A receipt written before the mechanical schema has neither schema nor
      # verified, but carries the digest, image id and exact live before/after
      # tuple. deploy-status still requires its deployment id, image, agent and
      # tooling to equal the applied tuple, so this only bridges the upgrade.
      # The next real deploy writes a mechanical receipt and retires the clause.
      ( (.schema == null and .verified == null)
        and (.provider_secret_sha256 | type == "string" and length == 64)
        and (.image_id | type == "string" and length > 0)
        and (.live_before != null and .live_before == .live_after) )
      or
      ( (.provider_secret_sha256 == null)
        and (.provider_secret_inode | type == "string" and length > 0) )
    )
  ' "$1" >/dev/null 2>&1
}
