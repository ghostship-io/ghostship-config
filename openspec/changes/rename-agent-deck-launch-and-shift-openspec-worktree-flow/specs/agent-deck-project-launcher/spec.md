## MODIFIED Requirements

### Requirement: Develop hosts expose a managed Agent Deck project launcher
Develop hosts SHALL expose a `launch-agent` command as repo-managed interactive
tooling so users can launch the current project into Agent Deck without
manually preparing the group, title, and default tool arguments each time.

#### Scenario: Launcher command is available as managed tooling
- **WHEN** the evaluated shared develop-host interactive tooling is inspected
  after the change
- **THEN** it SHALL include a `launch-agent` command

#### Scenario: Launcher targets the current project directory
- **WHEN** `launch-agent` is invoked from a project directory without an
  explicit path argument
- **THEN** it SHALL launch Agent Deck for the current working directory

### Requirement: The launcher ensures the current project group exists before launch
`launch-agent` SHALL derive the group name from the current directory basename,
SHALL create that group when it does not already exist in Agent Deck, and SHALL
launch the new session into that group.

#### Scenario: Missing group is created
- **WHEN** `launch-agent` is invoked from `/path/to/nixos-config` and no
  `nixos-config` group exists yet
- **THEN** it SHALL create the `nixos-config` group before launching the
  session

#### Scenario: Existing group is reused
- **WHEN** `launch-agent` is invoked from a directory whose matching Agent Deck
  group already exists
- **THEN** it SHALL reuse that existing group instead of failing or creating a
  duplicate

### Requirement: The launcher selects the requested tool and defaults to codex
`launch-agent` SHALL accept an optional positional tool parameter and SHALL
pass the selected tool through to Agent Deck's session creation flow. If the
caller omits the tool parameter, it SHALL default to `codex`.

#### Scenario: Default tool is codex
- **WHEN** `launch-agent` is invoked with no positional tool argument
- **THEN** it SHALL launch the session with `-c codex`

#### Scenario: Explicit tool is passed through
- **WHEN** `launch-agent gemini-cli` is invoked from the current project
  directory
- **THEN** it SHALL launch the session with `-c gemini-cli`

### Requirement: The launcher uses Agent Deck quick-title session creation
`launch-agent` SHALL create the session through Agent Deck's supported `add -Q`
flow and SHALL start that created session through the corresponding `session
start` command instead of relying on an unsupported single-step `launch -Q`
path.

#### Scenario: Quick title creation is delegated to Agent Deck
- **WHEN** `launch-agent` is invoked for a project directory
- **THEN** it SHALL let Agent Deck choose the session title through `add -Q`

#### Scenario: Created quick-title session is started explicitly
- **WHEN** `launch-agent` creates a new session through `add -Q`
- **THEN** it SHALL start that created session through `session start`

### Requirement: Active documentation describes the launcher workflow
The repo SHALL document `launch-agent` as a managed develop-host workflow
helper and SHALL describe the activation requirement for the new command in
active docs and changelog entries.

#### Scenario: Workflow docs mention the launcher
- **WHEN** active develop workflow documentation is inspected after the change
- **THEN** it SHALL describe `launch-agent` as a repo-managed helper for
  launching the current project into Agent Deck

#### Scenario: Docs mention activation requirements
- **WHEN** active workflow documentation is inspected after the change
- **THEN** it SHALL state that `launch-agent` becomes available only after the
  relevant Home Manager or NixOS rebuild or switch
