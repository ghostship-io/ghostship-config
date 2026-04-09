## Context

This change now has four linked concerns: keeping `agent-deck` as a supported develop-host tool, removing `workmux`, cleaning the known `workmux` user-home artifacts, and tightening the Ghostship OpenSpec override behavior. `agent-deck` is currently pinned to `v1.3.4`, but the latest confirmed upstream tag as of April 9, 2026 is `v1.4.1`. The repo already uses Home Manager user-scoped services and WSL-specific Home Manager profile layers, so a user-service-based `agent-deck web` startup path is a natural integration point to investigate and verify live.

As before, the Ghostship OpenSpec workflow has a source-of-truth issue: the checked-in skill files are visible, but `modules/develop/agent-tooling.nix` regenerates the `Ghostship Override` blocks after `openspec init` and `openspec update`. That wrapper must remain the authoritative place for the override wording.

## Goals / Non-Goals

**Goals:**
- Remove repo-managed `workmux` packaging from the develop profile and overlay.
- Remove the repo documentation and spec claims that `workmux` remains supported.
- Delete the known `/home/nixos` artifacts tied to `workmux`, including related OpenCode integration files.
- Keep `agent-deck` supported, bump it to `v1.4.1`, and define a default WSL user-service startup path for `agent-deck web`.
- Verify live that the supported WSL `agent-deck web` user service starts successfully and that its endpoint is reachable.
- Tighten the Ghostship OpenSpec propose/apply/archive overrides so agents summarize proposals for review, use Python-based edits in worktrees, update the current proposal instead of creating new proposal/worktree state mid-apply, and attempt to leave `main` clean after archive.
- Keep the wrapper-generated override text and the checked-in visible skill assets aligned.

**Non-Goals:**
- Removing unrelated old branches or unrelated existing worktrees.
- Removing `agent-deck` local runtime state while the tool remains supported.
- Reworking broader agent launcher defaults beyond the specific OpenSpec override behavior requested here.

## Decisions

### Keep `agent-deck` and bump it to `v1.4.1`

The repo should keep `agent-deck` as a managed develop-host tool and update it from `v1.3.4` to the latest confirmed upstream release, `v1.4.1`, instead of removing it with `workmux`.

Alternatives considered:
- Remove `agent-deck` too: rejected because the requested scope changed to keep it.
- Keep `agent-deck` pinned at `v1.3.4`: rejected because the user explicitly wants the latest release.

### Run `agent-deck web` by default on WSL through a user service and verify it live

The preferred design direction is a Home Manager `systemd.user.services` unit that starts `agent-deck web` for the `nixos` user on WSL develop hosts by default. The startup behavior should live in the WSL-scoped Home Manager layer unless the existing repo structure makes a gated shared profile simpler. The change is not complete until the service is actually started and its endpoint is reached successfully on a WSL develop host.

Alternatives considered:
- Start `agent-deck web` from shell init: rejected because it is harder to supervise and less declarative than a user service.
- Start it for all develop hosts: rejected because the requested behavior is WSL-specific.
- Treat evaluation-only service wiring as sufficient: rejected because the user explicitly wants the service tested live.

### Remove `workmux` at the packaging, spec, documentation, and local-artifact layers

`workmux` should be removed comprehensively rather than only dropping it from `home.packages`. The repo would otherwise keep advertising support, and the known user-home artifacts would remain as unmanaged clutter.

Alternatives considered:
- Remove only the Home Manager entry: rejected because the overlay package, docs, and specs would still claim support.
- Leave the local `workmux` state behind with a manual checklist: rejected because the user explicitly wants those artifacts deleted.

### Make `modules/develop/agent-tooling.nix` the source of truth for OpenSpec override wording

The wrapper-generated `Ghostship Override` blocks should be updated in `modules/develop/agent-tooling.nix`, then the repo-visible generated skill files should be refreshed or patched to match.

Alternatives considered:
- Update only `.codex/skills/openspec-*.md`: rejected because the wrapper will eventually overwrite behavior expectations.
- Update only the wrapper and ignore the checked-in generated skill files: rejected because the repo would remain misleading during review.

### Proposed override wording

The proposed `propose` override wording is:

```markdown
## Ghostship Override

- Create and refine the proposal, design, and tasks on `main`.
- When propose finishes, give the user a full summary of the proposed plan for review before moving on.
- When working in a worktree, use Python-based file edits instead of `apply_patch`.
- Verify the diff after each worktree file edit.
```

The proposed `apply` override wording is:

```markdown
## Ghostship Override

- Before implementation, commit the proposal, design, and tasks changes for the change on `main`.
- Create the change worktree at the start of apply, or reuse it if it already exists.
- Implement from the active change worktree, not from `main`.
- During apply, if the user changes the work, do not create a new proposal or a new worktree; update the current proposal instead.
- If implementation gets stuck on a bug, failing test, or unexpected behavior, use `systematic-debugging` if it is available.
- Do root-cause-first debugging before proposing or applying fixes.
```

The proposed `archive` override wording is:

```markdown
## Ghostship Override

- If the user does not specify a change, assume `archive` applies to the change currently being worked on.
- Before archiving, check whether the change has a matching worktree.
- If it does, explicitly use `$using-git-worktrees` to work from that isolated checkout while reconciling and cleaning up the change.
- If it does, commit all pending work in the worktree.
- Merge `main` into the worktree and resolve any issues there.
- Merge the worktree back into `main`.
- Run the archive flow on `main` and commit the resulting archive move there.
- After the archive commit succeeds, delete the change worktree with `git worktree remove <worktree-path>`.
- After archive completes, return `main` to a clean working state if possible.
- Reconcile or remove remaining related artifacts.
- Clearly report anything that still requires manual cleanup.
```

## Risks / Trade-offs

- [A default WSL user service starts `agent-deck web` when the user does not want it] -> Scope the service to the WSL profile and keep the startup behavior explicit in documentation.
- [Live service verification fails because WSL user services are not healthy yet on the target host] -> Treat that as blocking feedback and debug it before considering the change complete.
- [Runtime cleanup deletes a `workmux` file the user still wanted] -> Limit deletion to the explicitly identified `workmux` paths and report anything adjacent but ambiguous.
- [Repo-visible skill files drift from wrapper behavior again later] -> Treat the wrapper text as authoritative and refresh the visible skill assets in the same change.

## Migration Plan

1. Update `agent-deck` to `v1.4.1` and verify the package still builds in the develop profile.
2. Add the WSL-scoped `agent-deck web` user-service path and verify live that the service reaches a healthy running state and the endpoint is reachable.
3. Remove `workmux` from the local overlay and develop Home Manager profile.
4. Remove active docs, AGENTS memory entries, changelog claims, and active OpenSpec specs that advertise `workmux` as supported.
5. Delete the known `/home/nixos` state paths tied to `workmux` and report any related leftovers that are ambiguous or intentionally retained.
6. Update the Ghostship override generation in `modules/develop/agent-tooling.nix`.
7. Refresh the checked-in OpenSpec skill surfaces so the repo-visible wording matches the generated override source.
8. Verify that the develop profile includes `agent-deck` at `v1.4.1`, no longer includes `workmux`, that the known `workmux` local artifact paths are gone, and that the supported WSL `agent-deck web` service works live.

Rollback would require reintroducing `workmux`, rolling back the `agent-deck` pin, reverting the WSL user-service behavior if added, and restoring intentionally deleted local `workmux` runtime state.

## Open Questions

- Which listen address and port should the repo treat as the supported default for the WSL `agent-deck web` user service, if upstream does not already provide a stable default that fits the host.
