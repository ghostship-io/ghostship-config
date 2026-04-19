## Why

This repo's dev shell currently fails to load through `direnv` because `nix print-dev-env` dies with `error: get-env.sh failed to produce an environment`. That blocks normal `use flake` workflow even though flake evaluation and dev shell derivation itself both succeed.

Repo needs focused change now because shell failure breaks default develop-host entrypoint for this repo, hides fresh flake updates behind nix-direnv fallback behavior, and makes further Nix work harder to validate.

## What Changes

- Isolate exact failing interaction inside current default dev shell instead of treating all flake shell wiring as broken.
- Add narrow repo-local mitigation so `nix print-dev-env`, `nix develop`, and `direnv` can enter default shell successfully on current develop host.
- Preserve intended shell tooling surface as much as possible, moving or replacing only tooling that proves necessary to avoid failing export path.
- Document failure mode, mitigation, and any host activation implications for develop-host users.

## Capabilities

### New Capabilities
- `repo-dev-shell`: Define required behavior for this repo's default flake dev shell, including successful environment export and expected operator tooling availability.

### Modified Capabilities
- None.

## Impact

- Affected systems: develop hosts and repo-only workflow files.
- Affected code: `flake.nix`, possible shell helper wiring, and active docs such as `README.md`, `CHANGELOG.md`, and `AGENTS.md` if workflow or caveats change.
- Dependencies: current Nix `2.31.3` behavior on this host is part of problem surface; mitigation should stay repo-local unless investigation proves host-global fix is required.
- Manual implications: develop-host users may need `direnv reload` and the relevant rebuild or shell refresh after changes land; docs should call out any tool moved out of default shell or any residual upstream Nix limitation.
