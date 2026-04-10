## Context

Develop hosts currently manage Gemini in two different layers: a Nix-generated system settings file under `/etc/gemini-cli/settings.json`, and a scheduled `ghostship-agent-maintenance` service that installs or upgrades the user-local `@google/gemini-cli` package. Recent investigation showed two distinct failures in that split design:

- the generated Gemini settings still declare `experimental.plan = true`, which current Gemini releases treat as deprecated and warn about on every invocation;
- the maintenance service logs repeated npm and npx subprocess failures with `spawn sh ENOENT`, which means some upkeep steps do not have a reliable runtime environment under systemd.

The change is cross-cutting because it touches both the declarative Gemini config module and the develop-host maintenance service that owns agent CLI refresh.

## Goals / Non-Goals

**Goals:**
- Stop develop hosts from shipping deprecated Gemini system settings.
- Make the maintenance runtime requirements explicit enough that npm and npx child processes can run reliably under the scheduled systemd service.
- Preserve the existing managed wrapper model, npm prefix layout, and scheduled maintenance ownership for Gemini updates.
- Document the resulting behavior and activation requirements clearly.

**Non-Goals:**
- Rework Gemini's wrapper-level YOLO default behavior.
- Replace the user-local npm install model with a Nix-packaged Gemini CLI.
- Redesign unrelated maintenance tasks or change server-host behavior.

## Decisions

### Remove the deprecated Gemini setting from the Nix-generated system config

The warning comes from the repo-managed `/etc/gemini-cli/settings.json`, so the correct fix is to stop generating `experimental.plan` in [`modules/develop/gemini.nix`](/home/nixos/nixos-config/modules/develop/gemini.nix). The remaining Gemini defaults can stay in place as long as they remain valid for current Gemini releases.

Alternative considered:
- Leave the key in place and rely on Gemini auto-migration. Rejected because Gemini explicitly reports that system settings are read-only and cannot be migrated automatically.

### Treat the maintenance runtime as declarative service contract, not incidental environment

The `spawn sh ENOENT` failures show that the current maintenance service environment is insufficient for some npm- or npx-driven subprocess paths. The fix should make the service runtime explicit in the generated maintenance wiring, including the shell/runtime tools that npm child processes need, rather than assuming the base systemd service environment is enough.

Alternative considered:
- Ignore the warning-only failures because the primary Gemini install step currently succeeds. Rejected because the same fragile runtime can break later Gemini extension refreshes or future install paths, and the logs already show repeated failed upkeep.

### Keep scheduled maintenance as the owner of Gemini updates

Gemini version drift should continue to be resolved through `ghostship-agent-maintenance` and its timer rather than by moving update behavior into the launcher wrappers. This preserves the repo's existing separation between lightweight launchers and scheduled upkeep.

Alternative considered:
- Add launch-time self-update behavior to the Gemini wrapper. Rejected because it would make interactive launches slower, less predictable, and inconsistent with the documented maintenance model.

## Risks / Trade-offs

- [Gemini upstream deprecates another settings key soon after this fix] → Keep the spec focused on schema-valid generated settings and verify the generated config against a current Gemini release during implementation.
- [The npm child-process failure has more than one root cause] → Define the service runtime explicitly first, then verify the failing maintenance steps directly so the implementation can confirm whether additional follow-up is needed.
- [Documentation drifts from live behavior] → Update the active launcher and maintenance docs in the same change and verify them against the generated service behavior.

## Migration Plan

1. Update the develop-host Gemini module so new system generations stop emitting `experimental.plan`.
2. Update the maintenance service runtime wiring in the develop-host module layer so npm and npx subprocesses have the required shell/runtime tools under systemd.
3. Rebuild or switch a develop-host generation so the new Gemini system config and maintenance script become live.
4. Run or wait for `ghostship-agent-maintenance` to verify the repaired runtime and confirm Gemini launches without the deprecated-setting warning.

Rollback is straightforward: revert the module changes and switch back to the previous generation. The main user-visible effect of rollback would be the deprecated Gemini warning returning.

## Open Questions

- Whether the `spawn sh ENOENT` failures are fully resolved by the explicit runtime-path fix or if one of the npm-driven steps also needs a command-specific adjustment.
