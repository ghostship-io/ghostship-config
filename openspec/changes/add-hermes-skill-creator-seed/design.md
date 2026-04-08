## Context

The current Hermes runtime work in this repo already recognizes
`/home/hermes/seeds/shared/skills` as a supported persistent input path, but
the repo has not defined any shared Hermes skill seed sources yet. The user's
goal is not to extend the develop-host shared skill inventory under
`home/config/skills/`; it is to add a Hermes-specific shared `skill-creator`
seed that Hermes can copy into its own runtime state.

The upstream source of truth is the `vercel-labs/agent-browser` `v0.9.3`
`skills/skill-creator/` package. The desired workflow is:

1. Copy that upstream package into a Hermes-specific seed source as-is.
2. Review the exact markdown edits before implementation.
3. Adapt the Hermes seed copy so Hermes can use it well, with most behavior
   changes landing in Python scripts rather than in expanded markdown prose.

Hermes documentation indicates that skills are filesystem-backed directories
with `SKILL.md`, optional `references/`, optional `scripts/`, and Hermes-aware
frontmatter such as `version` and `metadata.hermes.*`. The repo also already
uses copy-once seed behavior for Hermes profile `SOUL.md` files and should
follow the same ownership model for a shared skill seed: seed only when the
runtime-owned copy is missing, then leave runtime state untouched.

## Goals / Non-Goals

**Goals:**
- Add a repo-managed Hermes shared skill seed source for `skill-creator`.
- Seed that skill into `/home/hermes/seeds/shared/skills/skill-creator/` only
  when the runtime-owned copy is missing.
- Preserve the upstream package contents first, then adapt the Hermes seed copy
  for Hermes conventions.
- Keep `SKILL.md` edits minimal and explicit for user review.
- Push Hermes-specific behavior into Python scripts and metadata where possible
  instead of bloating markdown.

**Non-Goals:**
- Changing the shared develop-host skill inventory under `home/config/skills/`.
- Rewriting the upstream `skill-creator` prose into a new local style guide.
- Introducing broad markdown churn across the upstream `references/` files.
- Forcing updates onto an already-seeded Hermes runtime copy.
- Implementing additional Hermes shared skills as part of this change.

## Decisions

### Decision: Keep Hermes-specific seed sources separate from shared develop-host skills

The Hermes copy will live under a new repo-managed seed path rooted in
`modules/self-hosted/hermes-seeds/shared/skills/skill-creator/` and will be
seeded into `/home/hermes/seeds/shared/skills/skill-creator/` at runtime.

Why:
- The user explicitly does not want to reuse `home/config/skills/skills-creator/`.
- Hermes runtime seeding is a separate concern from `~/.agents/skills/`.
- This avoids breaking the repo's existing shared-skill contract for develop
  hosts.

Alternatives considered:
- Reuse `home/config/skills/skills-creator/`. Rejected because that inventory
  is for another project and a different runtime surface.
- Install the skill directly inside the live Hermes home instead of seeding it.
  Rejected because the repo should manage seed inputs, not overwrite runtime
  state.

### Decision: Import the upstream package first, then adapt the Hermes copy

Implementation should first copy the upstream `v0.9.3` package layout and
contents into the Hermes seed source, then make Hermes-specific edits on that
copy.

Why:
- It preserves a clear baseline for review.
- It makes later drift from upstream explicit and auditable.
- It matches the requested "include all the files as is from the repo first"
  workflow.

Alternatives considered:
- Rewrite directly into a Hermes-native package shape from scratch. Rejected
  because it obscures what changed versus upstream.

### Decision: Keep markdown edits minimal and concentrate adaptation in Python scripts

The Hermes adaptation should prefer script and metadata changes over large
markdown rewrites.

Why:
- The user wants minimal changes to the actual markdown files.
- Hermes compatibility gaps are primarily around frontmatter and skill-creation
  scaffolding, which are best handled in `scripts/init_skill.py` and
  `scripts/quick_validate.py`.
- The upstream `skills-creator` guidance already emphasizes lean `SKILL.md`
  files and progressive disclosure.

Alternatives considered:
- Rewrite `SKILL.md` heavily into a Hermes-only format. Rejected because it
  creates review noise and departs from the upstream source more than needed.

### Decision: Review the exact `SKILL.md` edits before implementation

The implementation should be constrained to the following planned markdown
changes unless later review explicitly approves more:

1. Frontmatter changes only:
   - keep `name: skill-creator`
   - keep the existing description with only the minimum wording change needed
     to reference Hermes instead of Claude if that proves necessary
   - add `version: 0.9.3-hermes.1` or similar Hermes-local versioning
   - add `metadata.hermes.category`
   - add `metadata.hermes.tags`
   - add `metadata.hermes.config` only if Hermes config prompts are actually
     needed for this skill
2. Body heading normalization only where needed:
   - add or rename a top-level `## When to Use` section near the top
   - add or rename a top-level `## Procedure` section for the main creation
     flow
   - add or rename a top-level `## Pitfalls` section for compact warnings
   - add or rename a top-level `## Verification` section for validation and
     packaging checks
3. Preserve the rest of the upstream body text and examples as much as
   possible.
4. Do not expand the `references/` markdown unless Hermes-specific guidance
   cannot be expressed in scripts or concise cross-references.

Why:
- This gives the user a precise review surface before implementation.
- It aligns with the `skills-creator` preference for lean markdown.

Alternatives considered:
- Defer markdown specifics until implementation. Rejected because the user
  asked to review exact markdown edits up front.

### Decision: Use copy-once seeding for the shared Hermes skill directory

Hermes runtime preparation should seed
`/home/hermes/seeds/shared/skills/skill-creator/` only when that directory is
missing, and should leave an existing runtime-owned copy untouched.

Why:
- This matches the repo's existing Hermes seed ownership model for profile
  `SOUL.md` files.
- It keeps operator or runtime edits from being clobbered on later starts.

Alternatives considered:
- Always resync the repo copy into the runtime seed directory. Rejected because
  the current Hermes seed model is explicitly copy-once.

## Risks / Trade-offs

- [Hermes may require more `SKILL.md` structure than expected] -> Mitigation:
  define the exact planned markdown edits up front and keep any further changes
  behind explicit review.
- [Validator changes could drift away from Hermes' actual accepted frontmatter]
  -> Mitigation: anchor the script changes to Hermes docs and keep them narrow.
- [Copying upstream first may still require non-trivial follow-up edits] ->
  Mitigation: separate the import baseline from the adaptation commit-level work
  and review the diff by file role.
- [A shared seeded skill may be mistaken for the global shared skill inventory]
  -> Mitigation: document that this change only affects Hermes seed paths under
  `/home/hermes/seeds/shared/skills`.

## Migration Plan

1. Add the new Hermes shared skill seed source under
   `modules/self-hosted/hermes-seeds/shared/skills/skill-creator/`.
2. Copy the upstream `v0.9.3` package into that seed source as the initial
   baseline.
3. Apply the reviewed Hermes-specific metadata and script changes to the Hermes
   seed copy.
4. Update `modules/self-hosted/hermes.nix` so Hermes runtime preparation creates
   `/home/hermes/seeds/shared/skills` and seeds `skill-creator` only when the
   target directory is missing.
5. Verify the repo emits the expected seed source tree and that Hermes runtime
   preparation preserves an existing runtime-owned seeded copy.
6. Update README, CHANGELOG, and AGENTS if the implementation changes the
   documented Hermes seed contract or operating guidance.

## Open Questions

- What Hermes-local version string should the adapted `SKILL.md` use?
- Does Hermes need `metadata.hermes.config` for this skill, or are category and
  tags sufficient?
- Should `package_skill.py` keep `.skill` archive output unchanged, or should it
  grow an optional Hermes-oriented packaging mode?
