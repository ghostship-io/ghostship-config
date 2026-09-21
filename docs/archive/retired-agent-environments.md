# Retired agent environments

T3 Code is the fleet's coding environment. The containers below were removed and
are quarantined by the shared sweep in `modules/self-hosted/cleanup.nix`.

## OpenChamber

Removed from `modules/self-hosted/`. Its `/srv/apps/openchamber` state, Podman
container and image, `openchamber-deploy-when-idle` units, and dashboard entries
are quarantined on the next `chill-penguin` activation. The stability design is
no longer current and was removed with the module.

## Synara

Synara was a second T3 Code container sharing the primary image. Its duplicate
declaration had already been removed; the remaining `/srv/apps/synara` state and
the `podman-synara` unit are quarantined, and stale references are gone.

## ChatGPT/Codex workstation

The separate `codex.ghostship.io` Linux workstation is removed:
`modules/self-hosted/codex.nix`, `packages/codex-desktop-web/`, its CI workflow,
and its guides are gone. `/srv/apps/chatgpt` is quarantined. The T3 Code
**Codex provider** (`@openai/codex`) is unrelated and remains installed.

## WSL2 artifacts

The develop-host cleanup inventory retires the old `paseo`, `agent-deck`,
`opencode-server`, `openchamber` user-service, and `.openchamber` artifacts from
user homes. T3 Code workers are standalone Windows development boxes and link
only the skills under `home/config/skills/`.
