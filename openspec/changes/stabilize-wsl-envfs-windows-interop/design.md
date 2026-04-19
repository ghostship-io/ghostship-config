## Context

Current WSL config enables `services.envfs` in `modules/wsl/default.nix` so Windows-side tools can assume paths like `/usr/bin/bash`. Current WSL base config in `modules/wsl/wsl.nix` leaves Windows interop enabled with default PATH import behavior, so the process PATH includes Windows directories. `envfs` resolves executables from the requesting process PATH, which means imported Windows PATH entries cause synthetic `/usr/bin/*.exe` paths to appear.

Home Manager's WSL profile installs upstream `pkgs.wsl-open` and aliases `open` to `wsl-open`. Upstream `wsl-open` resolves `powershell.exe` from PATH, which currently selects `/usr/bin/powershell.exe` through `envfs`. On this host that synthetic path fails, while the real `/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe` path succeeds. The repo already documents that generic `powershell.exe` handling is unreliable on this host, so the implementation should align code with that documented reality.

## Goals / Non-Goals

**Goals:**
- Preserve `envfs` for Linux/FHS compatibility such as `/usr/bin/bash`.
- Stop accidental Windows executable synthesis through `/usr/bin` on WSL hosts.
- Keep Windows interop available through explicit, durable entrypoints.
- Make `wsl-open` use the real Windows PowerShell executable path.
- Update repo docs to describe explicit Windows interop instead of PATH-based discovery.

**Non-Goals:**
- Remove WSL interop entirely.
- Replace `envfs` with a custom patched fork.
- Guarantee every Windows executable through repo-managed wrappers.
- Redesign unrelated WSL host behavior.

## Decisions

### Keep `envfs` for Linux/FHS paths
The repo intentionally wants `/usr/bin/bash`, `/usr/bin/sh`, and related Linux/FHS compatibility paths for Windows-side tools. `envfs` already provides that and is upstream-supported in NixOS-WSL, so the change should keep `services.envfs.enable = true`.

Alternatives considered:
- Remove `envfs`: rejected because it drops existing FHS compatibility and forces a broader static-link redesign.
- Patch `envfs`: rejected because it adds custom maintenance for a problem WSL already exposes a cleaner knob for.

### Disable Windows PATH import with `appendWindowsPath = false`
The durable root fix is to stop importing Windows PATH entries into Linux PATH on WSL hosts. This keeps `envfs` focused on Linux/FHS entries and prevents synthetic `/usr/bin/powershell.exe` and similar accidental Windows `.exe` paths.

Alternatives considered:
- Keep Windows PATH import and only wrap `wsl-open`: rejected because it fixes one symptom but leaves the mixed namespace bug class in place.
- Re-add Windows paths later in shell init: rejected because `envfs` reads the current process PATH at lookup time, so the synthetic `.exe` paths would return.

### Keep Windows interop, but expose explicit wrappers
Windows interop itself remains useful. The repo should keep `wsl.wslConf.interop.enabled = true`, then expose explicit repo-managed entrypoints for supported tools instead of relying on bare PATH lookup. Minimum required wrapper is Windows PowerShell because `wsl-open` depends on it and current host docs already rely on the explicit path.

Alternatives considered:
- Continue using bare `powershell.exe`: rejected because current host behavior is already known-bad.
- Add wrappers for every common Windows tool immediately: rejected because it broadens scope without a concrete need.

### Wrap `wsl-open` to pin the real PowerShell path
`home/profiles/wsl.nix` should stop installing raw `pkgs.wsl-open` and instead install a wrapper that exports `PowershellExe=/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe` before delegating to upstream `wsl-open`. That keeps the established `open = "wsl-open"` fish alias while removing brittle PATH-based PowerShell discovery.

Alternatives considered:
- Replace `wsl-open` completely: rejected because upstream `wsl-open` already does the rest of the job.
- Patch upstream package behavior repo-wide: rejected because a small wrapper is enough.

## Risks / Trade-offs

- [Bare Windows commands disappear from PATH] -> Document the new contract clearly and provide explicit wrappers for supported tools.
- [Some operator habits rely on `powershell.exe` by name] -> Provide a repo-managed PowerShell wrapper and update docs/examples.
- [Other repo-managed WSL helpers may still assume PATH-based Windows commands] -> Audit current WSL profile and docs for bare Windows command references during implementation.

## Migration Plan

1. Keep `services.envfs.enable = true` in WSL module.
2. Set `wsl.wslConf.interop.appendWindowsPath = false` while keeping interop enabled.
3. Replace raw `pkgs.wsl-open` with a wrapped `wsl-open` package that pins `PowershellExe` to the real Windows PowerShell path.
4. Add the minimum explicit Windows wrapper surface needed by repo-managed workflows, starting with PowerShell.
5. Update WSL docs, AGENTS memory, and skill references to describe explicit Windows entrypoints instead of PATH-based lookup.
6. Verify `open .` works, `wsl-open -x .` shows the real PowerShell path, `/usr/bin/bash` still works, and synthetic `/usr/bin/powershell.exe` is no longer selected.

## Open Questions

- None. User direction favors the balanced approach: keep `envfs`, remove Windows PATH import, and use explicit wrappers.
