## Context

The repo already treats interactive develop-host tooling as Home Manager
packages while keeping shared runtime prerequisites such as `git` and `tmux` in
the host baseline. That split was used recently for `agent-deck`, and it maps
cleanly to `workmux`, which upstream positions as a terminal-first orchestration
tool for git worktrees and terminal-multiplexer windows.

`workmux` is not available from the pinned `nixpkgs` package set in this repo,
so adding it requires an explicit packaging choice. Upstream also supports
multiple backends such as `tmux`, Kitty, WezTerm, and Zellij, but this repo's
documented remote and local agent workflows already standardize on `tmux`.

## Goals / Non-Goals

**Goals:**
- Make `workmux` available declaratively on develop hosts.
- Keep package placement consistent with the repo's existing develop-tooling
  model.
- Target the current `tmux`-centric workflow explicitly so the first managed
  path is clear and supportable.
- Document activation requirements and the intended scope of the managed setup.

**Non-Goals:**
- Defining a repo-wide `.workmux.yaml` config, hook set, or skill inventory.
- Managing `workmux` session state, dashboard setup, or agent prompts.
- Standardizing non-`tmux` backends such as Kitty, WezTerm, or Zellij in the
  same change.
- Reworking existing Codex, Gemini, OpenCode, or OpenSpec wrapper behavior to
  integrate with `workmux` on day one.

## Decisions

### Package `workmux` as repo-managed Nix tooling

The repo should package or pin `workmux` through Nix rather than rely on
upstream's curl installer, `cargo install`, or ad hoc user-local bootstrap.
That keeps the binary reproducible, reviewable, and aligned with the repo's
general develop-host model.

Alternatives considered:
- Use the upstream installer script: rejected because it creates imperative
  unmanaged state.
- Ask users to run `cargo install workmux`: rejected because it bypasses the
  repo's declarative package contract.
- Wait for `nixpkgs` support: rejected because the current pinned channel does
  not expose `workmux` and the user wants the utility now.

### Expose `workmux` through the shared develop Home Manager profile

`workmux` is interactive user tooling, so it belongs in the shared develop
profile rather than the common system package baseline. This matches the repo's
current treatment of `agent-deck`, `gh`, and similar shell-facing utilities.

Alternatives considered:
- Add `workmux` to `environment.systemPackages` for develop hosts: broader than
  necessary for a user-facing terminal workflow tool.
- Add it to the common baseline for all hosts: rejected because server-role
  hosts do not need it.

### Support the `tmux` backend first

Although `workmux` supports multiple backends, the repo should scope the first
managed path to `tmux`. The current operating guidance, remote-work patterns,
and existing runtime baseline already assume `tmux`, which makes it the lowest
risk and most coherent first target.

Alternatives considered:
- Treat all upstream backends as equally supported from day one: rejected
  because it broadens docs and support scope without a matching repo standard.
- Prefer a different backend such as Zellij: rejected because the repo's
  durable workflow guidance and existing package baseline are already `tmux`
  based.

### Defer repo-managed `workmux` configuration defaults

The first change should focus on delivering the CLI declaratively. Repo-managed
defaults such as a shared `.workmux.yaml`, hook commands, sandbox presets, or
 `/worktree`-style skill wiring should stay out of scope until there is a clear
need to standardize them.

Alternatives considered:
- Ship a repo-wide `.workmux.yaml` immediately: rejected because the user asked
  to add the utility, not to lock in workflow conventions before trying it.
- Wrap `workmux` with repo-specific defaults on first install: rejected because
  it increases hidden behavior and design surface prematurely.

## Risks / Trade-offs

- [Upstream package shape changes] -> Pin a specific tagged release or flake
  revision and verify the chosen Nix packaging path against upstream's current
  source layout.
- [Runtime expectations exceed `git` and `tmux`] -> Validate the packaged CLI in
  the develop environment and document any additional durable prerequisites if
  they surface.
- [Users assume non-`tmux` backends are supported by repo docs] -> State
  explicitly that the managed path targets `tmux` first, while other upstream
  backends remain possible but undocumented here.
- [Premature workflow lock-in] -> Keep config and skill automation out of the
  initial scope so the repo can standardize later based on actual usage.

## Migration Plan

1. Choose the Nix packaging path for `workmux` and pin it declaratively.
2. Add `workmux` to the shared develop Home Manager package set.
3. Reuse the existing declarative `git` and `tmux` baseline rather than adding
   duplicate Home Manager entries.
4. Update active docs and changelog entries to describe the managed workflow and
   the `tmux`-first support boundary.
5. Validate via Nix evaluation/build and by confirming the binary resolves from
   the develop profile output.

Rollback is straightforward: remove the package wiring and the develop-profile
entry, then rebuild or switch back to the previous generation.

## Open Questions

- Whether the cleanest implementation is a local package derivation, an
  upstream flake input, or another pinned Nix import pattern that fits this
  repo's existing structure best.
- Whether `workmux` requires any additional documented runtime helpers beyond
  the repo's current `git` and `tmux` baseline for the workflows the user cares
  about.
- Whether a later follow-up should standardize a shared `.workmux.yaml` once
  real usage patterns emerge.
