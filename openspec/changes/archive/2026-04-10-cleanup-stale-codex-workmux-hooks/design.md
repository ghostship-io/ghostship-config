## Context

The repo previously supported `workmux` as part of the develop-host workflow, and Codex hook state on at least one host still contains `workmux set-window-status ...` commands in `~/.codex/hooks.json`. The repo has since removed `workmux` from the managed develop profile and already cleans several known `workmux` artifact paths, but it does not currently reconcile stale Codex hook state. Because Codex runs those hooks at prompt submission and other lifecycle points, stale entries cause immediate `127` hook failures in both Agent Deck and direct Codex sessions.

This change crosses Home Manager cleanup, Codex runtime state, and workflow documentation. It also touches user-home state, so the cleanup must be precise enough to remove repo-owned stale behavior without erasing unrelated user customizations.

## Goals / Non-Goals

**Goals:**
- Remove stale Codex hook commands that reference repo-removed tooling such as `workmux`.
- Make that cleanup declarative so rebuild or switch converges the host back to a working Codex state.
- Preserve unrelated user-defined Codex hooks and only remove entries that match the stale removed-tool pattern.
- Document the cleanup behavior and note that already-running sessions may need a restart before they see the cleaned state.

**Non-Goals:**
- Reintroduce `workmux` or any replacement status-integration workflow.
- Define a new repo-wide Codex hook feature beyond stale removed-tool cleanup.
- Rewrite arbitrary malformed `~/.codex/hooks.json` content that is unrelated to the removed-tool cleanup path.

## Decisions

### Decision: Use targeted JSON cleanup instead of deleting the whole hooks file

The cleanup should surgically remove stale `workmux` command hook entries from `~/.codex/hooks.json` rather than deleting the file wholesale. Users may have their own unrelated Codex hooks, and the repo should not erase that state just to remove one retired integration.

Alternatives considered:
- Delete `~/.codex/hooks.json` entirely: rejected because it would remove unrelated user-managed hooks.
- Leave cleanup manual-only: rejected because the repo already manages develop-host convergence and stale state has already caused repeated user-visible failures.

### Decision: Match only the known removed-tool command strings for the first pass

The initial cleanup should target the known stale `workmux set-window-status ...` commands that the repo previously installed. That keeps the behavior deterministic and avoids trying to infer every possible user customization that happens to mention `workmux`.

Alternatives considered:
- Remove any hook entry containing the substring `workmux`: broader, but more likely to delete intentional user-authored content that the repo did not own.
- Add a generic removed-tool registry immediately: useful later, but more design surface than this bug requires.

### Decision: Treat empty hook groups and empty files as valid cleanup results

After removing stale command entries, the cleanup logic should tolerate hook event arrays or nested hook lists becoming empty. If the whole file becomes structurally empty, it may either remain as an empty hooks object or be removed cleanly, as long as Codex no longer tries to execute the stale commands.

Alternatives considered:
- Preserve exact original formatting and object shape no matter what: unnecessary complexity for generated runtime state.
- Require a fully rewritten canonical hooks file: unnecessary because the goal is convergence away from stale commands, not style normalization.

### Decision: Document session restart implications explicitly

The repo should document that current running Codex or Agent Deck sessions may continue using the pre-cleanup state until restarted. That is a practical runtime detail, not a reason to avoid the declarative cleanup.

Alternatives considered:
- Ignore runtime session behavior in docs: rejected because it would leave a confusing gap after the fix is deployed.

## Risks / Trade-offs

- [The cleanup removes user-authored hooks that happen to mention `workmux`] -> Match only the exact stale command forms that the repo previously installed, not every arbitrary `workmux` reference.
- [Malformed JSON prevents automated cleanup] -> Keep the logic defensive and report that manual intervention is still required when the hook file cannot be parsed safely.
- [Users expect a running session to recover immediately] -> Document that Codex and Agent Deck sessions may need to be restarted after the cleaned state lands.
- [Future removed-tool drift appears in a different file or command shape] -> Keep the first implementation scoped to the confirmed stale Codex hook path, and leave broader removed-tool cleanup as a follow-up if needed.
