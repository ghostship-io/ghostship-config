## Context

The repo already distinguishes between system-wide host packages and interactive user tooling. Shared develop-host binaries that support the agent ecosystem are exposed through NixOS modules, while user-facing CLI tools are generally added through the develop Home Manager profile. `agent-deck` is an upstream Go CLI distributed through imperative installers, Homebrew, and `go install`, but it is not present in the `nixpkgs` revision currently pinned by this repo.

This change needs a small amount of design because it introduces a new third-party CLI into the managed agent workflow and has a practical runtime dependency on `tmux`. The packaging choice also needs to stay aligned with the repo’s existing separation between declarative host defaults and interactive tooling.

## Goals / Non-Goals

**Goals:**
- Package upstream `agent-deck` from a tagged release in a Nix-native way.
- Make `agent-deck` available to users of the shared develop profile without requiring upstream install scripts.
- Ensure the develop environment includes the runtime pieces `agent-deck` expects for normal use.
- Document how the tool is installed and when it becomes active.

**Non-Goals:**
- Managing `agent-deck` configuration, session state, or skills pool contents.
- Exposing `agent-deck` as a baseline package on server-role hosts.
- Reworking existing Codex, Gemini, or OpenCode wrapper behavior.
- Adding automatic update logic outside the normal Nix upgrade workflow.

## Decisions

### Package `agent-deck` as a local Nix derivation

The repo will package `agent-deck` locally rather than calling the upstream installer or relying on `go install`. That keeps the binary reproducible, reviewable, and tied to this repo’s pinned inputs.

Alternatives considered:
- Use the upstream installer script: rejected because it is imperative and bypasses Nix state.
- Use `go install` in a wrapper or maintenance job: rejected because it creates unmanaged user-local state outside the repo’s declarative package model.
- Wait for `nixpkgs` support: rejected because the user wants the tool now and the repo already carries local agent-tooling packaging where needed.

### Expose `agent-deck` through the develop Home Manager profile

`agent-deck` is interactive user tooling, so it should be added to the shared develop Home Manager package set rather than the server-safe `environment.systemPackages` baseline. This matches the repo’s existing workflow guidance and keeps the package limited to hosts where agent orchestration is relevant.

Alternatives considered:
- Add it to `environment.systemPackages` for all develop hosts: possible, but broader than necessary for a user-facing TUI.
- Add it to the common system package baseline: rejected because server-role hosts do not need it.

### Install `tmux` alongside `agent-deck` in the develop profile

Upstream documents `tmux` as a required runtime dependency. The packaged workflow should therefore ensure `tmux` is present anywhere `agent-deck` is installed, rather than assuming the user has installed it out of band.

Alternatives considered:
- Document `tmux` as a manual prerequisite: rejected because it weakens the declarative contract.
- Wrap `agent-deck` to fail with a custom message if `tmux` is missing: less useful than simply declaring the dependency in the profile.

### Keep documentation and changelog in the same change

This packaging change affects the user-visible develop workflow, so the implementation should update active docs and changelog entries as part of the same task rather than leaving discoverability to commit history.

## Risks / Trade-offs

- [Upstream release process or source layout changes] -> Pin a tagged release and verify the build inputs against upstream’s published Go module and release configuration.
- [Runtime assumptions drift beyond `tmux`] -> Validate the packaged binary in the develop environment and document any additional durable prerequisites if discovered.
- [Package placement becomes inconsistent with future agent tooling] -> Keep the capability scoped to interactive develop-profile tooling so the rule remains clear: baseline infrastructure in modules, user-facing tools in Home Manager.
- [Docs drift from actual package wiring] -> Require README/changelog updates in the implementation tasks and verify the final develop profile references match the documented path.

## Migration Plan

1. Add a local derivation for the upstream `agent-deck` tagged source.
2. Wire the derivation into the shared develop Home Manager package set.
3. Add `tmux` to the same develop profile if it is not already present.
4. Update active docs and changelog to describe the packaged workflow and activation path.
5. Validate via Nix evaluation/build and by confirming the binary resolves from the develop profile output.

Rollback is straightforward: remove the local derivation and the develop-profile package entry, then rebuild or switch back to the previous generation.

## Open Questions

- Whether the local package should live in a dedicated reusable package file or be added through the existing overlay pattern used elsewhere in the repo.
- Whether any extra runtime helper such as `jq` should be documented explicitly for advanced `agent-deck` features, even though it already exists in the current develop profile.
