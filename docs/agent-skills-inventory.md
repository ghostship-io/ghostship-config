# Installed agent skills and optional additions

Inventory verified in the T3 Code container on 2026-09-08. Shared skills are
available to Codex/ChatGPT, OpenCode, and Antigravity. Plugin skills remain
available through their owning provider when the plugin is active.

## Shared skills

| Skill | Source |
| --- | --- |
| `ghostship-agent-tooling` | Existing Ghostship catalog |
| `ghostship-audit-worktree` | Existing Ghostship catalog |
| `ghostship-bitwarden` | Existing Ghostship catalog |
| `ghostship-cloakbrowser` | Existing Ghostship catalog |
| `ghostship-google-workspace` | Existing Ghostship catalog |
| `ghostship-merge-worktree` | Existing Ghostship catalog |
| `ghostship-openchamber` | Existing Ghostship catalog |
| `ghostship-openchamber-automation` | Existing Ghostship catalog |
| `ghostship-printing-press` | Existing Ghostship catalog |
| `ghostship-printing-press-library` | Existing Ghostship catalog |
| `ghostship-pull-worktree` | Existing Ghostship catalog |
| `ghostship-review-tunnels` | Existing Ghostship catalog |
| `ghostship-user-services` | Existing Ghostship catalog |
| `grill-me` | Existing Ghostship catalog |
| `improve-codebase-architecture` | Existing Ghostship catalog |
| `writing-for-agents` | Matt Pocock (installed for this task) |

The Google Workspace skill has a compatibility copy with its missing `name`
added; its source and supporting resources are preserved.

## Provider skills

Codex built-ins: `imagegen`, `openai-docs`, `plugin-creator`, `review-agent`, `skill-creator`, `skill-installer`.

OpenCode also exposes its built-in `customize-opencode` skill.

### deep-research-work

- `deep-research`

### google-drive

- `google-docs`
- `google-drive`
- `google-drive-comments`
- `google-sheets`
- `google-slides`

### openai-templates

- `artifact-template-analytics-dashboard`
- `artifact-template-business-review`
- `artifact-template-design-report`
- `artifact-template-experiment-analysis`
- `artifact-template-financial-budget`
- `artifact-template-investment-committee-memo`
- `artifact-template-legal-memorandum`
- `artifact-template-market-trends-report`
- `artifact-template-minimal-letterhead`
- `artifact-template-operating-calendar`
- `artifact-template-operating-review`
- `artifact-template-project-kickoff`
- `artifact-template-project-tracker`
- `artifact-template-sales-pipeline`
- `artifact-template-simple-dark-mode`
- `artifact-template-simple-light-mode`
- `artifact-template-strategy-memorandum`
- `artifact-template-system-design`
- `artifact-template-team-alignment`
- `artifact-template-three-statement-forecast`

### plugin-management

- `plugin-management`

## Verified plugins

Codex plugin discovery returned no marketplace errors. These 11 plugins were
installed and enabled; this does not transfer their connectors to other agents.

| Plugin | Status |
| --- | --- |
| `gmail` | Enabled |
| `github` | Enabled |
| `google-drive` | Enabled |
| `google-calendar` | Enabled |
| `finances` | Enabled |
| `plugin-management` | Enabled |
| `app-691eab1e001081919e57189f8b2f03bc` | Enabled |
| `app-6944c4eec37c8191839ab9eafaa2f1f4` | Enabled |
| `app-6923772ef3d48191b6b18899af1cb037` | Enabled |
| `openai-templates` | Enabled |
| `deep-research-work` | Enabled |

OpenCode uses its configured providers without additional user plugins.
Antigravity uses its authenticated T3 Code ACP profile and shared skill paths.

## Recommended additions — awaiting selection

Install only the selection the user requests. `grill-me` and
`improve-codebase-architecture` are already present in the Ghostship catalog.

| Source | Skill | Why it fits |
| --- | --- | --- |
| Matt Pocock | `diagnosing-bugs` | Reproduce and isolate service or performance failures. |
| Matt Pocock | `resolving-merge-conflicts` | Reconcile concurrent fleet changes while preserving intent. |
| Matt Pocock | `tdd` | Behavior-focused tests for bootstrap and configuration code. |
| Matt Pocock | `code-review` | Separate standards and specification reviews; uses subagents. |
| pstack | `blast-radius` | Check how a small Nix change affects other services. |
| pstack | `principle-prove-it-works` | Require direct evidence from the deployed artifact. |
| pstack | `principle-make-operations-idempotent` | Make startup and migration safe to retry. |
| pstack | `principle-fix-root-causes` | Avoid accumulating workaround configuration. |
| pstack | `technical-writing` | Keep runbooks and PR descriptions easy to review. |

The first two Matt skills plus the first three pstack skills are the suggested
small starting set. pstack marks these skills `disable-model-invocation: true`;
their native invocation behavior varies by agent, so activation must be checked
when installing rather than assuming Cursor plugin behavior transfers.

Sources: [Matt Pocock skills](https://github.com/mattpocock/skills),
[pstack skills](https://github.com/cursor/plugins/tree/main/pstack/skills).

## Installed writing skill provenance

- Repository: `mattpocock/skills`
- Revision: `3cca18b368ae95cdbdebbff572ccafa662551015`
- Path: `skills/productivity/writing-for-agents`
- Installed using Codex’s Skill Installer into `~/.agents/skills`.
- Read and applied to the project and shared `AGENTS.md` files.
- Shared with Antigravity through `~/.gemini/config/skills`.
- Available on the next agent turn; start a new provider session if its catalog is cached.
