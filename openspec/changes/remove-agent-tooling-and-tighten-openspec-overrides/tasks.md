## 1. Update supported develop tooling

- [ ] 1.1 Bump the repo-managed `agent-deck` package pin from `v1.3.4` to the latest confirmed upstream release `v1.4.1` and verify the derivation still builds.
- [ ] 1.2 Remove the repo-managed `workmux` package definition, overlay wiring, and shared develop Home Manager package entry.

## 2. Define startup and cleanup behavior

- [ ] 2.1 Add the repo-supported WSL user-service behavior for running `agent-deck web` automatically for the `nixos` user.
- [ ] 2.2 Test the WSL `agent-deck web` user service live by starting it after the config change is applied, verifying it reaches a healthy user-service state, and confirming the configured web endpoint is reachable.
- [ ] 2.3 Delete the known `workmux` local artifacts under `/home/nixos`, including `/home/nixos/.cache/workmux/`, `/home/nixos/.config/workmux/`, `/home/nixos/.local/state/workmux/`, `/home/nixos/.config/opencode/plugin/workmux-status.ts`, and `/home/nixos/.config/opencode/skills/workmux/`.
- [ ] 2.4 Report any related but ambiguous leftover `workmux` branches, worktrees, or integrations that are found during cleanup instead of silently deleting unrelated state.

## 3. Update workflow docs and OpenSpec behavior

- [ ] 3.1 Update active documentation, including `README.md`, `AGENTS.md`, and `CHANGELOG.md`, so they describe `agent-deck` support at `v1.4.1`, remove `workmux` support claims, and document the supported `agent-deck web` startup behavior on WSL.
- [ ] 3.2 Update `modules/develop/agent-tooling.nix` and the checked-in OpenSpec skill surfaces so `propose`, `apply`, and `archive` use the revised Ghostship override wording.
- [ ] 3.3 Run concrete verification for the package and profile wiring, including a develop-profile evaluation/build, and confirm that `agent-deck` remains present at `v1.4.1`, `workmux` is absent, the targeted `workmux` local artifact paths are gone, and the supported WSL `agent-deck web` path has already passed live verification.
