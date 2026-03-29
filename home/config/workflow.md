# Project Workflow

## Guiding Principles

1. **The Plan is the Source of Truth:** All work must be tracked in `plan.md`
2. **Open Source Excellence (MANDATORY):** Treat every repository as a high-quality OSS project. Maintain `README.md`, `CHANGELOG.md`, `LICENSE`, and `SECURITY.md` proactively.
3. **Continuous Learning (MANDATORY):** Update the project `AGENTS.md` immediately upon discovering new facts or correcting mistakes.
4. **Autonomous Validation:** Validation is the only path to finality. Empirically confirm state using available tools before and after changes.
5. **The Tech Stack is Deliberate:** Changes to the tech stack must be documented in `tech-stack.md` *before* implementation
6. **User Experience First:** Every decision should prioritize user experience
7. **Non-Interactive & CI-Aware:** Prefer non-interactive commands.

## Task Workflow

All tasks follow a strict lifecycle:

### Phase 0: Repository Setup (Conductor & OSS)
- **Identity & Baseline:** Initialize the mandatory OSS baseline: `README.md`, `LICENSE`, `CHANGELOG.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, versioning (`0.1.0`), and GitHub metadata.

### Standard Task Workflow

1. **Planning & Research (MANDATORY):** 
   - **Select Task:** Choose the next available task from `plan.md` in sequential order.
   - **Research Implementation:** Deep-dive into the codebase and documentation to determine the most robust and idiomatic way to implement the task.
   - **Clarify Ambiguities:** You MUST proactively ask the user targeted questions for any ambiguities or critically underspecified requirements before proceeding.
   - **Strategy Proposal:** Briefly summarize your proposed implementation strategy to the user.

2. **Mark In Progress:** Once the plan is clear and ambiguities are resolved, edit `plan.md` and change the task from `[ ]` to `[~]`.

3. **Implement & Test:** 
   - Write the application code necessary to fulfill the task requirements.
   - **Autonomous Validation (MANDATORY):** Verify the implementation autonomously via relevant system checks or tests. Only ask for manual verification if physically impossible.

4. **Refactor (MANDATORY):**
   - Improve clarity, remove duplication, and enhance performance without changing the external behavior.
   - Ensure the code remains idiomatic and follows the project style guide.

5. **Security Review (MANDATORY):**
   - Audit the changes for potential vulnerabilities (e.g., hardcoded secrets, injection flaws, broken access control).
   - Ensure no sensitive data is logged or exposed.
   - Refer to `SECURITY.md` for project-specific security standards.

6. **Documentation & OSS Maintenance (MANDATORY):**
   - **OSS Maintenance:** Update `README.md`, `CHANGELOG.md`, `SECURITY.md`, and versioning (SemVer 2.0.0) to reflect the changes.
   - **Continuous Learning:** Update project `AGENTS.md` with new findings or mistake corrections immediately.
   - **Document Deviations:** If implementation differs from the original plan or tech stack:
     - Update `tech-stack.md` with the new design.
     - Update `plan.md` to reflect the adjusted path.
     - Add a dated note explaining the rationale for the change.

7. **Commit Code Changes:**
   - Stage all code and OSS changes related to the task.
   - Propose a clear, concise commit message following `<type>(<scope>): <description>`.
   - Perform the commit.

8. **Attach Task Summary with Git Notes:**
   - **Step 8.1: Get Commit Hash:** Obtain the hash of the *just-completed commit* (`git log -1 --format="%H"`).
   - **Step 8.2: Draft Note Content:** Create a detailed summary for the completed task. This should include the task name, a summary of changes, a list of all created/modified files, and the core "why" for the change.
   - **Step 8.3: Attach Note:** Use the `git notes` command to attach the summary to the commit.
     ```bash
     # The note content from the previous step is passed via the -m flag.
     git notes add -m "<note content>" <commit_hash>
     ```

9. **Get and Record Task Commit SHA:**
    - **Step 9.1: Update Plan:** Read `plan.md`, find the line for the completed task, update its status from `[~]` to `[x]`, and append the first 7 characters of the *just-completed commit's* commit hash.
    - **Step 9.2: Write Plan:** Write the updated content back to `plan.md`.

10. **Commit Plan Update:**
    - **Action:** Stage the modified `plan.md` file.
    - **Action:** Commit this change with a descriptive message (e.g., `conductor(plan): Mark task 'Create user model' as complete`).

### Phase Completion Verification and Checkpointing Protocol

**Trigger:** This protocol is executed immediately after a task is completed that also concludes a phase in `plan.md`.

1.  **Announce Protocol Start:** Inform the user that the phase is complete and the verification and checkpointing protocol has begun.

2.  **Perform Autonomous Verification and Report Results:**
    -   **CRITICAL:** Before presenting the report, first analyze `product.md`, `product-guidelines.md`, and `plan.md` to determine the user-facing goals of the completed phase.
    -   You **must** attempt to verify all changes autonomously using available tools (SSH, `lsblk`, `nix-store`, etc.).
    -   Generate a report detailing what was verified autonomously and what (if anything) requires manual user action.
    -   The report you present to the user **must** follow this format:

        ```
        The phase implementation is complete. Autonomous verification has been performed.

        **Verification Results:**
        1.  **Autonomous Check:** [e.g., Kernel version confirmed via SSH]
        2.  **Manual Verification Required:** [e.g., Please physically verify the screen is not black]
        ```

3.  **Await Explicit User Feedback:**
    -   After presenting the detailed plan, ask the user for confirmation: "**Does this meet your expectations? Please confirm with yes or provide feedback on what needs to be changed.**"
    -   **PAUSE** and await the user's response. Do not proceed without an explicit yes or confirmation.

4.  **Create Checkpoint Commit:**
    -   Stage all changes. If no changes occurred in this step, proceed with an empty commit.
    -   Perform the commit with a clear and concise message (e.g., `conductor(checkpoint): Checkpoint end of Phase X`).

5.  **Attach Auditable Verification Report using Git Notes:**
    -   **Step 5.1: Draft Note Content:** Create a detailed verification report including the manual verification steps and the user's confirmation.
    -   **Step 5.2: Attach Note:** Use the `git notes` command and the full commit hash from the previous step to attach the full report to the checkpoint commit.

6.  **Get and Record Phase Checkpoint SHA:**
    -   **Step 6.1: Get Commit Hash:** Obtain the hash of the *just-created checkpoint commit* (`git log -1 --format="%H"`).
    -   **Step 6.2: Update Plan:** Read `plan.md`, find the heading for the completed phase, and append the first 7 characters of the commit hash in the format `[checkpoint: <sha>]`.
    -   **Step 6.3: Write Plan:** Write the updated content back to `plan.md`.

7. **Commit Plan Update:**
    - **Action:** Stage the modified `plan.md` file.
    - **Action:** Commit this change with a descriptive message following the format `conductor(plan): Mark phase '<PHASE NAME>' as complete`.

8.  **Announce Completion:** Inform the user that the phase is complete and the checkpoint has been created, with the detailed verification report attached as a git note.

### Quality Gates

Before marking any task complete, verify:

- [ ] Implementation meets specification
- [ ] Code follows project's code style guidelines (as defined in `code_styleguides/`)
- [ ] No linting or static analysis errors
- [ ] Documentation updated if needed
- [ ] No security vulnerabilities introduced

## Development Commands

### Rebuild and Switch
```bash
nixos-rebuild build --flake .#launch-octopus
./result/bin/switch-to-configuration switch
```

### Edit Secrets
```bash
secrets-edit secrets.yaml
```

## Code Review Process

### Self-Review Checklist
Before requesting review:

1. **Functionality**
   - Feature works as specified
   - Edge cases handled
   - Error messages are user-friendly

2. **Code Quality**
   - Follows style guide
   - DRY principle applied
   - Clear variable/function names
   - Appropriate comments

3. **Security**
   - No hardcoded secrets
   - Input validation present

## Commit Guidelines

### Message Format
```
<type>(<scope>): <description>

[optional body]

[optional footer]
```

### Types
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation only
- `style`: Formatting, missing semicolons, etc.
- `refactor`: Code change that neither fixes a bug nor adds a feature
- `chore`: Maintenance tasks

## Definition of Done

A task is complete ONLY when:

1. All code implemented to specification and project style guide.
2. OSS files (`README.md`, `CHANGELOG.md`, `SECURITY.md`, etc.) are updated.
3. Project `AGENTS.md` is updated with lessons learned or new findings.
4. Changes committed with proper message and version incremented if necessary.
5. Git note with task summary attached to the final commit.
6. `plan.md` updated with status `[x]` and commit SHA.
