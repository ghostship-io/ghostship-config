## MODIFIED Requirements

### Requirement: Propose flow ends with a full plan review summary and worktree edit guidance
The Ghostship OpenSpec `propose` override SHALL require the agent to create or reuse the change worktree at the start of propose, create and refine proposal, design, and tasks artifacts from that active change worktree instead of `main`, use Python-based file edits instead of `apply_patch` when working in a worktree, verify the diff after each worktree file edit, and finish by giving the user a detailed overview of the full proposed change and everything it plans to do before moving on.

#### Scenario: Propose begins from the change worktree
- **WHEN** the generated Ghostship `propose` override instructions are inspected
- **THEN** they SHALL instruct the agent to create or reuse the change worktree at the start of propose and to create and refine the proposal, design, and tasks from that active change worktree instead of `main`

#### Scenario: Propose includes worktree edit guidance
- **WHEN** the generated Ghostship `propose` override instructions are inspected
- **THEN** they SHALL instruct the agent to use Python-based file edits instead of `apply_patch` when working in a worktree and to verify the diff after each worktree file edit

#### Scenario: Propose concludes with a detailed overview
- **WHEN** the generated Ghostship `propose` override instructions are inspected
- **THEN** they SHALL instruct the agent to give the user a detailed overview of the full proposed change and everything it plans to do before moving on

### Requirement: Apply flow reuses the active change context midstream
The Ghostship OpenSpec `apply` override SHALL require the agent to commit the proposal, design, and tasks changes for the change in the active worktree before implementation, implement from the active change worktree instead of `main`, update the current proposal instead of creating a new proposal or a new worktree when the user changes the work during apply, keep track of issues, follow-up work, and notable problems found during apply, and finish by giving the user a detailed overview of the completed work, the changes made, any proposal updates made during apply, and any issues found during apply before moving on.

#### Scenario: Apply begins from the existing change worktree
- **WHEN** the generated Ghostship `apply` override instructions are inspected
- **THEN** they SHALL instruct the agent to commit the proposal, design, and tasks changes in the active worktree before implementation and to implement from that existing change worktree instead of `main`

#### Scenario: Mid-apply change request reuses current proposal and worktree
- **WHEN** the user changes the work while the agent is already in the apply flow for the current change
- **THEN** the generated Ghostship `apply` override SHALL instruct the agent not to create a new proposal or a new worktree and to update the current proposal instead

#### Scenario: Apply tracks and reports issues found during implementation
- **WHEN** the generated Ghostship `apply` override instructions are inspected
- **THEN** they SHALL instruct the agent to keep track of issues, follow-up work, and notable problems found during apply and to report them in the final apply summary

#### Scenario: Apply concludes with a detailed completion overview
- **WHEN** the generated Ghostship `apply` override instructions are inspected
- **THEN** they SHALL instruct the agent to give the user a detailed overview of the completed work, the changes made, and any proposal updates made during apply before moving on

### Requirement: Archive flow attempts to leave main clean
The Ghostship OpenSpec `archive` override SHALL require the agent to attempt to leave `main` in a clean working state after archive completes by reconciling or removing remaining related artifacts, clearly reporting any leftovers that still require manual cleanup, and finishing with a list of issues or follow-up work that should be considered next.

#### Scenario: Archive includes post-archive cleanup expectation
- **WHEN** the generated Ghostship `archive` override instructions are inspected
- **THEN** they SHALL instruct the agent to attempt post-archive cleanup of remaining related artifacts on `main` and to report anything left for manual cleanup

#### Scenario: Archive concludes with next issues or follow-up work
- **WHEN** the generated Ghostship `archive` override instructions are inspected
- **THEN** they SHALL instruct the agent to give the user a list of issues or follow-up work that should be considered next after archive finishes
