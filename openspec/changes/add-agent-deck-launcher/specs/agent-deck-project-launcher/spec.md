## ADDED Requirements

### Requirement: Develop hosts expose a managed Agent Deck project launcher
Develop hosts SHALL expose an `agent-deck-launch` command as repo-managed interactive tooling so users can launch the current project into Agent Deck without manually preparing the group, title, and default tool arguments each time.

#### Scenario: Launcher command is available as managed tooling
- **WHEN** the evaluated shared develop-host interactive tooling is inspected after the change
- **THEN** it SHALL include an `agent-deck-launch` command

#### Scenario: Launcher targets the current project directory
- **WHEN** `agent-deck-launch` is invoked from a project directory without an explicit path argument
- **THEN** it SHALL launch Agent Deck for the current working directory

### Requirement: The launcher ensures the current project group exists before launch
`agent-deck-launch` SHALL derive the group name from the current directory basename, SHALL create that group when it does not already exist in Agent Deck, and SHALL launch the new session into that group.

#### Scenario: Missing group is created
- **WHEN** `agent-deck-launch` is invoked from `/path/to/nixos-config` and no `nixos-config` group exists yet
- **THEN** it SHALL create the `nixos-config` group before launching the session

#### Scenario: Existing group is reused
- **WHEN** `agent-deck-launch` is invoked from a directory whose matching Agent Deck group already exists
- **THEN** it SHALL reuse that existing group instead of failing or creating a duplicate

### Requirement: The launcher selects the requested tool and defaults to codex
`agent-deck-launch` SHALL accept an optional positional tool parameter and SHALL pass the selected tool through to Agent Deck's launch command. If the caller omits the tool parameter, it SHALL default to `codex`.

#### Scenario: Default tool is codex
- **WHEN** `agent-deck-launch` is invoked with no positional tool argument
- **THEN** it SHALL launch the session with `-c codex`

#### Scenario: Explicit tool is passed through
- **WHEN** `agent-deck-launch gemini-cli` is invoked from the current project directory
- **THEN** it SHALL launch the session with `-c gemini-cli`

### Requirement: The launcher generates date-based incrementing titles
`agent-deck-launch` SHALL generate Agent Deck session titles in `YYYY-MM-DD-N` format, where the date uses ISO format for the launch day and `N` is the next positive integer for launches associated with the current project on that date.

#### Scenario: First launch of the day starts at one
- **WHEN** `agent-deck-launch` is invoked for a project with no recorded launches for the current date
- **THEN** it SHALL use the title `YYYY-MM-DD-1` for that date

#### Scenario: Later launches increment the suffix
- **WHEN** `agent-deck-launch` is invoked for a project that already has recorded launches titled `YYYY-MM-DD-1` and `YYYY-MM-DD-2` for the current date
- **THEN** it SHALL use the title `YYYY-MM-DD-3`

### Requirement: Active documentation describes the launcher workflow
The repo SHALL document `agent-deck-launch` as a managed develop-host workflow helper and SHALL describe the activation requirement for the new command in active docs and changelog entries.

#### Scenario: Workflow docs mention the launcher
- **WHEN** active develop workflow documentation is inspected after the change
- **THEN** it SHALL describe `agent-deck-launch` as a repo-managed helper for launching the current project into Agent Deck

#### Scenario: Docs mention activation requirements
- **WHEN** active workflow documentation is inspected after the change
- **THEN** it SHALL state that `agent-deck-launch` becomes available only after the relevant Home Manager or NixOS rebuild or switch
