## Context

This repo exposes `codex`, `gemini`, and `opencode` through Nix-managed launchers on develop hosts. Their current defaults are inconsistent: Gemini hard-codes `defaultApprovalMode = "default"`, Codex generates a config file without explicit approval or sandbox defaults, and OpenCode relies on its upstream default permissions instead of pinning the behavior in repo config. The change needs to make the dangerous default explicit for all three active CLIs while preserving the existing wrapper structure and the separate Home Manager OpenCode config path.

## Goals / Non-Goals

**Goals:**
- Make the default execution policy explicit for Codex, Gemini, and OpenCode on develop hosts.
- Use each CLI's native config surface instead of wrapper argument injection so explicit user-supplied flags can still override the defaults.
- Keep the system and Home Manager OpenCode configs aligned.
- Update active docs so the new risk profile and activation requirements are visible.

**Non-Goals:**
- Changing model selections, providers, or shared skill wiring.
- Changing server-host services or non-develop host behavior.
- Introducing per-command wrapper aliases or custom subcommand parsing.

## Decisions

### Use config-native defaults instead of injected CLI arguments

Codex, Gemini, and OpenCode all expose configuration surfaces for the relevant defaults, so the repo will set the behavior there rather than prepending hidden wrapper flags. This keeps the implementation declarative, easier to inspect with `nix eval`, and more respectful of explicit user overrides.

Alternatives considered:
- Inject YOLO flags in the wrapper scripts: rejected because it is harder to inspect declaratively and can interfere with explicit user flags.
- Leave OpenCode implicit because upstream already defaults to allow: rejected because the repo goal is explicit, uniform behavior across all three launchers.

### Pin Codex's true YOLO mode in generated TOML

Codex distinguishes between `--full-auto` and its actual no-approval, no-sandbox mode. The generated TOML will therefore set both `approval_policy = "never"` and `sandbox_mode = "danger-full-access"` so the default matches true YOLO semantics instead of the lower-friction sandboxed mode.

Alternatives considered:
- Use `--full-auto` semantics: rejected because it does not match the requested YOLO behavior.

### Keep OpenCode's system and Home Manager configs in sync

The repo currently defines OpenCode config in both `modules/develop/opencode-wrapper.nix` and `modules/develop/opencode.nix`. Both files will declare the same explicit `permission = "allow"` value so develop-host behavior does not drift depending on which config path a host uses.

Alternatives considered:
- Update only the system config path: rejected because the Home Manager profile would still depend on implicit upstream defaults.

## Risks / Trade-offs

- [Risk] The default behavior becomes more dangerous for casual launcher use. → Mitigation: document the new default clearly in `README.md`, `AGENTS.md`, and `CHANGELOG.md`.
- [Risk] Upstream CLI config schemas may evolve. → Mitigation: use documented config keys and verify generated output with `nix eval`.
- [Risk] Split OpenCode config paths can drift again later. → Mitigation: update both paths in the same change and call out the alignment requirement in the design and tasks.

## Migration Plan

1. Update the generated Codex, Gemini, and OpenCode configs in the develop modules.
2. Verify the rendered config output with `nix eval` against a develop host configuration before activation.
3. Rebuild the affected develop hosts and run a Home Manager switch anywhere the Home Manager OpenCode config path is active.

Rollback is a straightforward revert of the config keys followed by the same rebuild or switch flow.

## Open Questions

None.
