## Context

This repo already splits interactive user tooling from host-wide runtime packages. `agent-deck` is exposed through the shared develop Home Manager profile, while the agent launchers for `codex`, `gemini`, and `opencode` are managed as declarative wrapper binaries in the develop module layer. The requested `agent-deck-launch` workflow crosses both areas: it is interactive user tooling tied to `agent-deck` state under `~/.agent-deck`, but it also needs to accept the same launcher names that the repo manages elsewhere.

The current `agent-deck` CLI already exposes the primitives needed for the workflow: `group list --json`, `group create`, `list --json`, and `launch`. The requested helper should stay on those supported surfaces instead of reading internal Agent Deck state files directly, and it should use `jq` for the JSON filtering so the implementation stays lightweight and shell-native.

The repo also currently exposes `gemini`, not `gemini-cli`, even though the underlying upstream npm package is `@google/gemini-cli`. A fish alias would only fix interactive fish sessions, not bash, scripts, or helper commands that invoke the tool by name.

## Goals / Non-Goals

**Goals:**
- Provide a repo-managed `agent-deck-launch` command on develop hosts.
- Make `agent-deck-launch` work from the current directory without extra flags in the common case.
- Ensure the matching Agent Deck group exists before launch and create it when missing.
- Default the launcher tool to `codex` while allowing an optional positional tool argument.
- Generate titles in `YYYY-MM-DD-N` form with persistent per-project numbering for a given date.
- Make `gemini-cli` available shell-wide with the same wrapper behavior and defaults as `gemini`.
- Document the workflow and activation requirements in the active repo docs.

**Non-Goals:**
- Rework Agent Deck's own internal data model or upstream CLI behavior.
- Add a generic multi-argument argument parser for every `agent-deck launch` flag beyond the requested optional tool parameter.
- Change server-host shell behavior.
- Introduce imperative install steps or per-user manual shell setup.

## Decisions

### Package `agent-deck-launch` as managed develop-host user tooling

`agent-deck-launch` should be a real executable command, not a fish alias or fish function. It belongs with other interactive develop-host tooling and should be added declaratively through the shared develop Home Manager package set so it is available anywhere in the user's shell after activation.

Alternatives considered:
- Fish alias or function: rejected because the helper needs branching, JSON parsing, and state inspection, and should not be limited to interactive fish.
- System package only: rejected because the helper is user-scoped interactive tooling built around `agent-deck` state in the user's home, so it aligns better with the Home Manager develop profile.

### Create missing Agent Deck groups through the CLI and preserve existing groups

The helper should derive the group name from `basename "$(pwd -P)"`, check `agent-deck group list --json`, and create the group only when it does not already exist. When the group is created, it should set the new group's default path to the current directory. Existing groups should be reused as-is rather than rewritten, because the user may already have customized them.

Alternatives considered:
- Always run `group create` and ignore failures: rejected because it obscures real errors and makes the helper harder to reason about.
- Update the group's default path on every launch: rejected because that would silently overwrite user-managed group settings.

### Derive daily title numbers from Agent Deck JSON output with `jq`

The helper should generate titles in `YYYY-MM-DD-N` format, using `date -I` for the prefix and the next positive integer for that project and date as the suffix. It should determine the next suffix from `agent-deck list --json`, filtered with `jq` against the current project path, group, and date prefix. This keeps the implementation on documented CLI output and avoids direct reads of internal Agent Deck state.

Alternatives considered:
- Read internal Agent Deck SQLite state: rejected because the user explicitly wants the helper to rely only on CLI JSON output.
- Hardcode `-1` or rely on Agent Deck's default title generation: rejected because it does not satisfy the requested date-based naming convention.

### Expose `gemini-cli` as a second managed wrapper binary

`gemini-cli` should be added as a real develop-host wrapper binary that shares the same environment setup and YOLO-default logic as `gemini`. This keeps the command available in fish, bash, scripts, and helper commands without depending on shell aliases, and it lets `agent-deck-launch gemini-cli` pass through a supported command name directly.

Alternatives considered:
- Fish shell alias `gemini-cli="gemini"`: rejected because it would not work everywhere in the shell.
- Normalize `gemini-cli` to `gemini` only inside `agent-deck-launch`: rejected because the user explicitly wants `gemini-cli` to work generally, not only in the launcher.

## Risks / Trade-offs

- [Deleted sessions can let a previously used suffix be reused later] -> Accept numbering based on current CLI-visible sessions because the helper is intentionally restricted to supported JSON output.
- [Concurrent launches in the same project may race on the next numeric suffix] -> Accept the narrow race window for now and let `agent-deck` remain the final source of truth for session creation; the helper only needs best-effort preselection of the next title from current JSON-visible sessions.
- [Group names based on `basename` can collide across unrelated repos with the same folder name] -> Preserve the requested basename behavior and scope title-number lookup by both project path and group where possible.
- [Adding another wrapper name increases launcher surface area] -> Reuse the same wrapper logic as `gemini` so behavior stays consistent and documentation can describe it as an alternate entrypoint rather than a separate tool.
