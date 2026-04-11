## 1. Rename the managed Agent Deck launcher

- [ ] 1.1 Update `home/profiles/develop.nix` so the managed launcher command,
  usage text, and help output are renamed from `agent-deck-launch` to
  `launch-agent` without changing the current launch behavior.
- [ ] 1.2 Update active references to the launcher in the repo docs and
  workflow guidance, including `README.md`, `CHANGELOG.md`, and `AGENTS.md`, so
  they consistently describe `launch-agent` as the supported command and note
  the rebuild or switch required for activation.

## 2. Revise the Ghostship OpenSpec override workflow

- [ ] 2.1 Update `modules/develop/agent-tooling.nix` so the generated
  Ghostship `propose` override creates or reuses the change worktree at the
  start, creates proposal/design/tasks from that active worktree, and ends with
  a detailed overview of the full proposed change and everything it plans to
  do.
- [ ] 2.2 Update `modules/develop/agent-tooling.nix` so the generated
  Ghostship `apply` override assumes the active change worktree already exists,
  keeps track of issues and follow-up work found during apply, and ends with a
  detailed overview of completed work, changes made, proposal updates, and
  issues found during apply.
- [ ] 2.3 Update `modules/develop/agent-tooling.nix` so the generated
  Ghostship `archive` override keeps the existing cleanup guidance and ends with
  a list of issues or follow-up work that should be considered next.
- [ ] 2.4 Refresh the checked-in OpenSpec skill and command surfaces that carry
  the generated override wording so they stay aligned with the wrapper source.

## 3. Update active specs and verify the shared workflow

- [ ] 3.1 Update the active OpenSpec specs under
  `openspec/specs/agent-deck-project-launcher/spec.md` and
  `openspec/specs/ghostship-openspec-override-behavior/spec.md` so the live
  requirements match the renamed launcher and revised propose/apply/archive
  behavior.
- [ ] 3.2 Run `nix flake check --no-build -L` from the repo root and run a
  targeted develop-host build such as
  `nix build .#nixosConfigurations.launch-octopus.config.system.build.toplevel -L`
  to verify the renamed launcher and updated override generation evaluate
  cleanly.
- [ ] 3.3 Run `openspec status --change rename-agent-deck-launch-and-shift-openspec-worktree-flow`
  and confirm the change remains apply-ready after the artifacts, docs, and
  verification updates are complete.
