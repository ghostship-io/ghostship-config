## ADDED Requirements

### Requirement: Propose flow ends with a full plan review summary and worktree edit guidance
The Ghostship OpenSpec `propose` override SHALL require the agent to present a full summary of the proposed plan for user review after proposal generation completes, and SHALL tell the agent to use Python-based file edits instead of `apply_patch` when working in a worktree.

#### Scenario: Propose concludes with review summary
- **WHEN** the generated Ghostship `propose` override instructions are inspected
- **THEN** they SHALL instruct the agent to give a full summary of the proposed plan for user review before moving on

#### Scenario: Propose includes worktree edit guidance
- **WHEN** the generated Ghostship `propose` override instructions are inspected
- **THEN** they SHALL instruct the agent to use Python-based file edits instead of `apply_patch` when working in a worktree and to verify the diff after each worktree file edit

### Requirement: Apply flow reuses the active change context midstream
The Ghostship OpenSpec `apply` override SHALL require the agent to create or reuse the change worktree at the start of apply, and if the user changes the work during apply, SHALL forbid the agent from creating a new proposal or a new worktree and instead direct the agent to update the current proposal.

#### Scenario: Apply begins from the change worktree
- **WHEN** the generated Ghostship `apply` override instructions are inspected
- **THEN** they SHALL instruct the agent to create the change worktree at the start of apply, or reuse it if it already exists, and to implement from that worktree instead of `main`

#### Scenario: Mid-apply change request reuses current proposal and worktree
- **WHEN** the user changes the work while the agent is already in the apply flow for the current change
- **THEN** the generated Ghostship `apply` override SHALL instruct the agent not to create a new proposal or a new worktree and to update the current proposal instead

### Requirement: Archive flow attempts to leave main clean
The Ghostship OpenSpec `archive` override SHALL require the agent to attempt to leave `main` in a clean working state after archive completes by reconciling or removing remaining related artifacts and clearly reporting any leftovers that still require manual cleanup.

#### Scenario: Archive includes post-archive cleanup expectation
- **WHEN** the generated Ghostship `archive` override instructions are inspected
- **THEN** they SHALL instruct the agent to attempt post-archive cleanup of remaining related artifacts on `main` and to report anything left for manual cleanup
