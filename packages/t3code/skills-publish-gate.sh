#!/usr/bin/env bash
# Publication gate for ghostship-skills-reconcile.
#
# Activation always installs the T3 skill files, so host skills stay current.
# The ChatGPT publish (and the consumer verify that requires a publication)
# runs only when the operator marker exists. This replaces the release #8.2
# wantedBy hold and is the durable #9 switch; the agent-source
# `activate --skip-publish` flag lands in the same series.
set -euo pipefail

marker=${GHOSTSHIP_SKILLS_PUBLISH_MARKER:-/var/lib/ghostship-skills/publish-requested}
mode=${1:?usage: skills-publish-gate.sh install ROLLOUT SKILLS_CLI REPO SHA APP_ID STATE BRIDGE | verify VERIFY}
shift

case $mode in
  install)
    rollout=${1:?rollout}; skills_cli=${2:?skills cli}; repo=${3:?repo}
    sha=${4:?source sha}; app_id=${5:?app id}; state=${6:?state}; bridge=${7:?bridge}
    if [ -e "$marker" ]; then
      exec "$rollout" activate --skills-cli "$skills_cli" --repo "$repo" \
        --source-sha "$sha" --app-id "$app_id" --state "$state" --bridge "$bridge"
    fi
    echo "publication held: $marker is absent; installing host skills only" >&2
    exec "$skills_cli" --repo "$repo" --source-sha "$sha" install-t3
    ;;
  verify)
    verify=${1:?verify command}
    if [ -e "$marker" ]; then exec "$verify"; fi
    echo "publication held: $marker is absent; skipping the consumer verify" >&2
    exit 0
    ;;
  *) echo "usage: $0 install ...|verify ..." >&2; exit 2 ;;
esac
