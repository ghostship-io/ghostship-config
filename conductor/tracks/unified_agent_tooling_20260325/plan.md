# Unified Agent Tooling Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Gemini, OpenCode, Conductor, and Codex share one consistent agent-tooling model for skills, instructions, extensions, update checks, and MCP servers.

**Architecture:** Extract shared launcher and config behavior into focused Nix modules and wrapper scripts, keep reusable agent assets under `~/.agents`, and make MCP regeneration part of the normal NixOS switch path.

**Tech Stack:** Nix, Home Manager, shell wrappers, `npx`, Node.js, `nh`, MCP servers.

---

## Phase 1: Shared Agent Foundations

### Task 1: Centralize shared agent assets

**Files:**
- Modify: `home/nixos.nix`
- Modify: `home/config/AGENTS.md`
- Modify: `home/config/workflow.md`
- Modify: `conductor/product.md`
- Modify: `conductor/tech-stack.md`
- Modify: `conductor/workflow.md`

- [ ] **Step 1: Define the shared source of truth**

Update the home-managed `~/.agents` layout so shared skills and global instructions are the primary reusable agent assets.

- [ ] **Step 2: Align repo docs with that model**

Update the repo guidance files so Gemini and Conductor both describe the same shared-agent approach.

- [ ] **Step 3: Verify evaluation**

Run: `nh os build --flake .#launch-octopus`

Expected: the system evaluates successfully with the updated shared-agent paths.

- [ ] **Step 4: Commit**

```bash
git add home/nixos.nix home/config/AGENTS.md home/config/workflow.md conductor/product.md conductor/tech-stack.md conductor/workflow.md
git commit -m "docs(agent): centralize shared agent tooling guidance"
```

### Task 2: Update OSS-facing repository docs

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Describe the new unified agent workflow**

Document the shared agent-tooling model at a high level so future changes stay consistent.

- [ ] **Step 2: Record the user-visible change**

Add a changelog entry summarizing the unified agent setup.

- [ ] **Step 3: Verify doc consistency**

Run: `git diff -- README.md CHANGELOG.md`

Expected: only the intended documentation changes appear.

- [ ] **Step 4: Commit**

```bash
git add README.md CHANGELOG.md
git commit -m "docs: describe unified agent tooling"
```

- [ ] Task: Conductor - User Manual Verification 'Shared Agent Foundations' (Protocol in workflow.md)

## Phase 2: Gemini, OpenCode, and Codex Parity

### Task 1: Factor shared launcher/update logic

**Files:**
- Create: `modules/develop/agent-tooling.nix`
- Modify: `modules/develop/default.nix`
- Modify: `modules/develop/core.nix`

- [x] **Step 1: Add the shared launcher helpers** [23f0f15]

Create a small reusable module or helper layer for common update-check and wrapper behavior.

- [x] **Step 2: Wire the helper into the develop module set** [23f0f15]

Import the shared helper from both the system and Home Manager entry points.

- [x] **Step 3: Validate module evaluation** [23f0f15]

Run: `nix eval .#nixosConfigurations.launch-octopus.config.system.build.toplevel.drvPath`

Expected: the derivation path evaluates without module errors.

- [x] **Step 4: Commit** [23f0f15]

```bash
git add modules/develop/agent-tooling.nix modules/develop/default.nix modules/develop/core.nix
git commit -m "refactor(agent): add shared launcher plumbing"
```

### Task 2: Normalize Gemini behavior

**Files:**
- Modify: `modules/develop/gemini.nix`

- [x] **Step 1: Rework the Gemini wrapper flow** [af22ae8]

Make the Gemini launcher use the same pre-launch update pattern as the other CLIs.

- [x] **Step 2: Keep extensions and MCP config consistent** [af22ae8]

Preserve the existing Gemini behavior while aligning it with the shared agent model, and only run extension updates when the remote Git revision changes.

- [x] **Step 3: Verify launch behavior** [af22ae8]

Run: `gemini --help`

Expected: Gemini starts through the wrapper and reaches the CLI help output.

- [x] **Step 4: Commit** [af22ae8]

```bash
git add modules/develop/gemini.nix
git commit -m "refactor(gemini): align launcher and extension flow"
```

### Task 3: Normalize OpenCode behavior

**Files:**
- Modify: `modules/develop/opencode-wrapper.nix`
- Modify: `modules/develop/opencode.nix`

- [x] **Step 1: Align the OpenCode wrapper path** [af22ae8]

Make the wrapper-managed and Home Manager-managed variants follow the same launch/update flow.

- [x] **Step 2: Keep plugin and MCP configuration consistent** [af22ae8]

Ensure the OpenCode config continues to point at the shared MCP/plugin model and only refresh the plugin when its remote Git revision changes.

- [x] **Step 3: Verify launch behavior** [af22ae8]

Run: `opencode --help`

Expected: OpenCode starts through the wrapper and reaches the CLI help output.

- [x] **Step 4: Commit** [af22ae8]

```bash
git add modules/develop/opencode-wrapper.nix modules/develop/opencode.nix
git commit -m "refactor(opencode): align wrapper and config flow"
```

### Task 4: Add Codex parity

**Files:**
- Create: `modules/develop/codex.nix`
- Create: `modules/develop/codex-wrapper.nix`
- Modify: `modules/develop/default.nix`
- Modify: `modules/develop/core.nix`
- Modify: `home/nixos.nix`

- [x] **Step 1: Add a Codex wrapper/module** [23f0f15]

Implement Codex using the same behavioral pattern as Gemini and OpenCode, including wrapper-managed launch behavior.

- [x] **Step 2: Register Codex in the module graph** [23f0f15]

Import the new Codex module from the relevant system and home entry points.

- [x] **Step 3: Verify launch behavior** [23f0f15]

Run: `codex --help`

Expected: Codex launches through the repo-managed wrapper and reaches the CLI help output.

- [x] **Step 4: Commit** [23f0f15]

```bash
git add modules/develop/codex.nix modules/develop/codex-wrapper.nix modules/develop/default.nix modules/develop/core.nix home/nixos.nix
git commit -m "feat(codex): add wrapper-managed parity with other agents"
```

### Task 5: Add Gemini delegation MCP server

**Files:**
- Modify: `modules/develop/agent-tooling.nix`
- Modify: `modules/develop/gemini.nix`
- Modify: `modules/develop/opencode-wrapper.nix`
- Modify: `modules/develop/opencode.nix`
- Modify: `modules/develop/codex.nix`
- Modify: `README.md`
- Modify: `CHANGELOG.md`

- [x] **Step 1: Research the Gemini delegation server** [23f0f15]

Confirm the package and interface for the local Gemini-CLI-backed MCP server and document the chosen command path.

- [x] **Step 2: Add the MCP server to each CLI config** [23f0f15]

Expose the new Gemini-delegation server in Gemini, OpenCode, and Codex configs so each CLI can delegate repo research and planning prompts to Gemini CLI.

- [x] **Step 3: Verify the delegate workflow** [23f0f15]

Run: `gemini --help && opencode --help && codex --help`

Expected: all wrappers still launch successfully with the new MCP server configured.

- [x] **Step 4: Commit** [23f0f15]

```bash
git add modules/develop/agent-tooling.nix modules/develop/gemini.nix modules/develop/opencode-wrapper.nix modules/develop/opencode.nix modules/develop/codex.nix README.md CHANGELOG.md
git commit -m "feat(agent): add gemini delegation mcp server"
```

- [ ] Task: Conductor - User Manual Verification 'Gemini, OpenCode, and Codex Parity' (Protocol in workflow.md)

## Phase 3: MCP Refresh on Switch

### Task 1: Refresh MCP configuration during `nh os switch`

**Files:**
- Modify: `modules/common/automation.nix`

- [x] **Step 1: Add an activation hook or switch hook** [c7787f6]

Make `nh os switch` refresh MCP server configuration automatically.

- [x] **Step 2: Keep the refresh lightweight** [c7787f6]

Use a minimal non-interactive update path so the switch experience stays fast.

- [x] **Step 3: Verify the hook path** [c7787f6]

Run: `nh os switch --flake .#launch-octopus --dry-run`

Expected: the switch path includes the MCP refresh behavior without requiring manual steps.

- [x] **Step 4: Commit** [c7787f6]

```bash
git add modules/common/automation.nix
git commit -m "feat(system): refresh mcp config on switch"
```

### Task 2: Confirm end-to-end MCP parity

**Files:**
- Modify: `modules/develop/gemini.nix`
- Modify: `modules/develop/opencode-wrapper.nix`
- Modify: `modules/develop/opencode.nix`
- Modify: `modules/develop/codex.nix`

- [ ] **Step 1: Ensure each CLI sees the same MCP set**

Align the CLI configs so they all expose the same server inventory where possible.

- [ ] **Step 2: Verify generated config files**

Run: `nixos-rebuild build --flake .#launch-octopus`

Expected: the generated system config reflects the refreshed MCP setup.

- [ ] **Step 3: Commit**

```bash
git add modules/develop/gemini.nix modules/develop/opencode-wrapper.nix modules/develop/opencode.nix modules/develop/codex.nix
git commit -m "refactor(agent): unify mcp server configuration"
```

- [ ] Task: Conductor - User Manual Verification 'MCP Refresh on Switch' (Protocol in workflow.md)

## Phase 4: Final Validation and Cleanup

### Task 1: Update project memory and release notes

**Files:**
- Modify: `AGENTS.md`
- Modify: `CHANGELOG.md` if needed

- [ ] **Step 1: Record any new findings**

Add lessons learned or corrections discovered while wiring the shared agent model.

- [ ] **Step 2: Keep release notes current**

Add a concise note if the user-facing workflow changed materially.

- [ ] **Step 3: Verify no stray edits remain**

Run: `git diff --stat`

Expected: only the intended files are changed.

- [ ] **Step 4: Commit**

```bash
git add AGENTS.md CHANGELOG.md
git commit -m "docs: record unified agent tooling changes"
```

### Task 2: End-to-end validation

**Files:**
- Modify: none

- [ ] **Step 1: Validate all supported launchers**

Run: `gemini --help && opencode --help && codex --help`

Expected: all three launchers start successfully through the repo-managed wrappers.

- [ ] **Step 2: Validate the system switch path**

Run: `nh os switch --flake .#launch-octopus`

Expected: the switch completes and refreshes MCP configuration.

- [ ] **Step 3: Check the final repository state**

Run: `git status --short`

Expected: only the planned track artifacts or intentionally uncommitted changes remain.

- [ ] **Step 4: Commit any final cleanup**

```bash
git add .
git commit -m "chore(agent): finish unified tooling overhaul"
```

- [ ] Task: Conductor - User Manual Verification 'Final Validation and Cleanup' (Protocol in workflow.md)
