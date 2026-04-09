## 1. Remove WSL web-service support

- [x] 1.1 Delete the `agent-deck-web` runner and `systemd.user.services.agent-deck-web` wiring from `home/profiles/wsl.nix` without changing the shared develop-profile `agent-deck` package list.
- [x] 1.2 Update the active `openspec/specs/` contract so it no longer requires automatic WSL `agent-deck web` startup and still makes clear that managed `agent-deck` packaging remains supported.

## 2. Update docs and verification

- [x] 2.1 Update `README.md`, `CHANGELOG.md`, and `AGENTS.md` to remove the supported automatic WSL `agent-deck web` startup path while keeping `agent-deck` and `agent-deck-launch` documented as managed develop-host tooling.
- [x] 2.2 Verify the affected WSL develop-host configs still evaluate or build cleanly with concrete commands such as `nix build .#nixosConfigurations.launch-octopus.config.system.build.toplevel -L` and `nix build .#nixosConfigurations.armored-armadillo.config.system.build.toplevel -L`.
- [x] 2.3 Record the manual post-apply cleanup targets for the live host state: `agent-deck-web.service`, its `default.target.wants` symlink, any lingering `agent-deck-web` tmux session, and `~/.agent-deck/web-service.log`.
