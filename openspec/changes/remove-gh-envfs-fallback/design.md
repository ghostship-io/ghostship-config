## Context

`gh` currently lives in the shared system package baseline and is also injected into WSL `envfs` as `/usr/bin/gh`. That made the repo responsible for a special compatibility path that did not solve the real Codex Desktop detection problem and also drifted away from the repo's package-ownership model, where interactive user tooling belongs in Home Manager.

This change narrows the contract back down: `gh` is available to develop-profile users through Home Manager, and the repo stops advertising a special `envfs` fallback for it.

## Goals / Non-Goals

**Goals:**
- Restore `gh` to the shared develop Home Manager package set.
- Remove the explicit `envfs` fallback that exposes `/usr/bin/gh`.
- Align documentation with the narrower, user-tooling-only contract.

**Non-Goals:**
- Add any new compatibility shim or real-path workaround.
- Modify Codex Desktop or any external caller.
- Remove general WSL `envfs` support for paths such as `/usr/bin/bash`.

## Decisions

### Keep `gh` as develop-profile user tooling
`gh` should live in `home.packages` because it is interactive user tooling and does not need to be part of the shared system baseline.

Alternatives considered:
- Leave `gh` in `environment.systemPackages`: rejected because it broadens the host-wide baseline without establishing a clearer contract.

### Remove the repo-managed `/usr/bin/gh` envfs fallback
The repo should stop creating `/usr/bin/gh` through `services.envfs.extraFallbackPathCommands`. That fallback was a custom compatibility exception, not a general WSL requirement, and it did not provide a reliable fix for external detection behavior.

Alternatives considered:
- Keep the fallback in place: rejected because it preserves repo-managed behavior we no longer want to support.

## Risks / Trade-offs

- [Narrower compatibility] External callers that only look for `/usr/bin/gh` may stop finding it through repo-managed config. → Mitigation: document that the repo now only guarantees `gh` as a develop-profile user package.
- [Expectation drift] Existing docs and assumptions may still imply `/usr/bin/gh` support. → Mitigation: update active docs and agent memory in the same change.

## Migration Plan

1. Add `gh` back to the shared develop Home Manager package set.
2. Remove the explicit `envfs` fallback entry for `/usr/bin/gh`.
3. Verify host evaluation/build still succeeds after the contract is narrowed.
4. Update docs to state that the repo no longer manages a special `envfs` path for `gh`.

## Open Questions

- None. The change intentionally narrows support rather than introducing another compatibility mechanism.
