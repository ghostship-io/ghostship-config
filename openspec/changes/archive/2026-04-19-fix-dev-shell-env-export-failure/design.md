## Context

Repo default dev shell is defined in `flake.nix` and is current entrypoint for `.envrc` via `use flake`. On this develop host, flake evaluation succeeds and shell derivation builds, but environment export fails later inside Nix's `get-env.sh` path. That breaks `nix print-dev-env`, `nix develop`, and then `direnv`, which falls back to previous cached environment instead of loading fresh shell state.

Investigation already narrowed problem surface. Single-package shells work, many partial package combinations work, and full current package set fails. That points away from broad flake wiring failure and toward some interaction in full shell composition or in Nix `2.31.3` environment export behavior on this host. Change therefore needs design because it crosses flake shell behavior, develop-host workflow, and documentation expectations.

## Goals / Non-Goals

**Goals:**
- Identify minimal shell composition that reproduces `get-env.sh failed to produce an environment`.
- Restore successful `nix print-dev-env`, `nix develop`, and `direnv` loading for repo default shell on current develop host.
- Keep fix repo-local and as small as possible.
- Preserve required operator tooling surface, documenting any moved tool or caveat clearly.
- Update active docs so future flake changes do not silently reintroduce same workflow break.

**Non-Goals:**
- Reworking unrelated flake outputs or host modules.
- Changing shared `~/.agents` skill model or unrelated develop-host launcher behavior.
- Depending on ad-hoc manual install steps outside Nix-managed repo workflow.
- Solving every possible upstream Nix environment-export bug beyond this repo's reproducible shell failure.

## Decisions

### Continue from minimal failing package set, not from broad shell rewrites
Implementation should keep narrowing current package list until smallest failing combination is proven. That gives concrete root-cause evidence and avoids speculative shell rewrites.

Alternatives considered:
- Rewrite shell wholesale: rejected because current evidence does not show broad shell design failure.
- Assume one package is broken from first glance: rejected because multiple subsets already show interaction-based behavior.

### Prefer smallest repo-local mitigation in `flake.nix`
Once failing combination is known, change should adjust default shell only enough to avoid bad export path. Preferred order is: simplify package composition, swap one package for equivalent repo-native access, or move one nonessential tool behind documented explicit invocation.

Alternatives considered:
- Host-global Nix or direnv workaround first: rejected because repo should fix its own default workflow when possible.
- Keep broken shell and document fallback only: rejected because `.envrc` expects working default shell, not permanent fallback behavior.

### Verify through exact failing entrypoints
Verification must use same commands users hit in practice: `nix print-dev-env -L .#default`, `nix develop .#default --command ...`, and `direnv` reload in repo root. Shell derivation build success alone is insufficient because current failure happens after build during environment export.

Alternatives considered:
- Verify only `nix flake show` or shell derivation build: rejected because those already pass while user workflow still fails.

### Treat upstream Nix behavior as possible constraint, but keep repo contract explicit
Design should allow that root trigger may be Nix `2.31.3` specific while still defining repo contract clearly: repo default dev shell must export successfully on supported develop-host workflow. If final mitigation is a workaround for upstream behavior, docs should say so.

Alternatives considered:
- Ignore upstream possibility and overfit to repo code only: rejected because current evidence already points at Nix export path behavior.

## Risks / Trade-offs

- [Minimal failing set still looks like upstream Nix bug] → Keep repo fix small, document suspected upstream behavior, and avoid overengineering custom shell wrappers.
- [Removing one package reduces convenience] → Prefer moving only nonessential tooling and document replacement path in active workflow docs.
- [Fix works on this host but not every develop host] → Verify with exact local entrypoints now and keep requirement phrased around supported repo workflow, not accidental host quirks.
- [Documentation drifts from actual shell composition later] → Update README, CHANGELOG, and AGENTS as part of same change so future work sees current contract.

## Migration Plan

1. Continue binary-splitting current shell package set until minimal failing combination is confirmed.
2. Compare working near-full subset against failing set to identify simplest mitigation.
3. Update `flake.nix` with minimal repo-local shell change.
4. Verify `nix print-dev-env`, `nix develop`, and `direnv` all succeed again.
5. Update active docs with final shell behavior, caveats, and any required reload or rebuild step.

## Open Questions

- Which exact package combination is smallest failing set?
- Is trigger package-specific, interaction-specific, or caused by env-size/function-count threshold in current Nix export path?
- If one tool must leave default shell, should repo expose it through alternate documented command path or accept narrower default shell surface?
