---
name: codex-queue
description: Run long Codex CLI manual-review queues in tmux-backed worktrees with durable ledgers, monitoring, resume prompts, smoke tests, and merge-preflight support. Use when a user asks Codex to process many items that require human-like judgment, per-item inspection, or reasoning that must not be automated away.
---

# codex-queue

Use this skill when a user wants Codex to work through a large queue of
manual-review items without stopping. The bundled script handles queue setup,
tmux sessions, liveness checks, and merge assistance. It must not decide queue
items for the agent.

## Core Rule

Every queued item must be manually reviewed by a Codex worker. Do not create
scripts, classifiers, rankers, parsers, or bulk transformations that make the
final decision for multiple queue items. Tooling may only surface evidence,
split work, track progress, launch workers, monitor tmux, and help merge
finished work.

This matters because long-review queues are usually brittle: source metadata can
be inconsistent, judgment depends on context, similar items can differ in small
ways, automated matching creates false positives, and quality depends on direct
inspection of each item.

## Workflow

1. Inspect the repo and available data before launching workers.
2. Decide whether support tooling is sufficient. If not, add support-tooling
   work to the plan before spawning queue workers.
3. Prepare the run:

   ```bash
   $HOME/.agents/skills/codex-queue/scripts/codex_queue.py prepare \
     --run-name <name> \
     --queue <items.jsonl> \
     --objective '<manual review objective>'
   ```

4. Review and commit the generated `codex-queue/<run-name>/` state.
5. Spawn workers:

   ```bash
   $HOME/.agents/skills/codex-queue/scripts/codex_queue.py spawn --run-name <name>
   ```

6. Start the monitor:

   ```bash
   $HOME/.agents/skills/codex-queue/scripts/codex_queue.py spawn-monitor --run-name <name>
   ```

7. Check progress:

   ```bash
   $HOME/.agents/skills/codex-queue/scripts/codex_queue.py status --run-name <name>
   ```

8. When all ledgers are complete, inspect merge state:

   ```bash
   $HOME/.agents/skills/codex-queue/scripts/codex_queue.py merge-preflight --run-name <name>
   ```

9. Manually merge queue branches/worktrees back into the originating worktree,
   preserving every ledger line and reconciling any shared outputs.

## Run Settings

The user may override these settings when preparing or spawning a run:

- `--model`, default `gpt-5.5`
- `--reasoning-effort`, default `high`
- `--batch-size`, default `10`
- `--monitor-interval`, default `300`
- `--parallel-queues`, default derived from item count

Default queue splitting is 1 queue for 200 or fewer known items, 2 queues for
201-300 items, and 3 queues for more than 300 items. Unknown-size queues stay in
one queue and require a final `queue_complete` ledger line.

## Examples

Website review:

```bash
$HOME/.agents/skills/codex-queue/scripts/codex_queue.py prepare \
  --run-name site-review \
  --queue sites.jsonl \
  --objective 'Manually visit each URL, inspect the live page, and write a short summary with evidence.'
```

Issue backlog triage:

```bash
$HOME/.agents/skills/codex-queue/scripts/codex_queue.py prepare \
  --run-name issue-triage \
  --queue issues.jsonl \
  --objective 'Manually inspect each issue, linked discussion, and current code state, then classify the issue with a short rationale.'
```

Research source curation:

```bash
$HOME/.agents/skills/codex-queue/scripts/codex_queue.py prepare \
  --run-name source-curation \
  --queue candidate-sources.jsonl \
  --objective 'Manually inspect each source candidate and decide whether it is relevant, credible, and useful for the target research brief.'
```

Document set review:

```bash
$HOME/.agents/skills/codex-queue/scripts/codex_queue.py prepare \
  --run-name doc-review \
  --queue documents.jsonl \
  --objective 'Manually inspect each document and summarize its key claim, evidence, and whether it should be included.'
```

## Support Tooling Boundary

Allowed support tooling:

- list queue items and metadata
- search available local metadata
- open source documents, pages, or files for one item at a time
- validate ledger completeness
- create worktrees, prompts, and tmux sessions
- detect idle workers and send `continue`

Forbidden task automation:

- bulk-deciding keep/skip/classification outcomes
- bulk-ranking or scoring items
- matching ambiguous entities without manual review
- using a script to generate final summaries or decisions
- creating new worker-side tooling after the queue starts

If required support tooling is missing, stop before spawning workers and add
that tooling to the implementation plan.

## Worker Prompt

Prompts are rendered from
[worker-prompt-template.md](references/worker-prompt-template.md). Read it when
changing the queue-worker contract.

## Smoke Test

Run the smoke test after changing this skill or its script:

```bash
$HOME/.agents/skills/codex-queue/scripts/codex_queue.py smoke \
  --batch-size 5 \
  --parallel-queues 1 \
  --monitor-interval 15
```

The smoke test creates a temporary git repo, launches a Codex worker in tmux,
requires manual browser review of 20 public sites with `agent-browser`, sends
Escape after 10 completed ledger entries, and verifies the monitor resumes the
worker. If the worker skips per-item browser inspection or bulk-summarizes the
queue, strengthen the prompt and rerun from a clean smoke repo.
