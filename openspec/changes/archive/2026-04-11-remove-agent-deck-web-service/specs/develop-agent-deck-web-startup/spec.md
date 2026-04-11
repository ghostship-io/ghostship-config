## REMOVED Requirements

### Requirement: WSL develop hosts define and verify background startup for agent-deck web
**Reason**: The repo no longer wants to support or document automatic `agent-deck web` startup for the `nixos` user on WSL develop hosts.
**Migration**: Remove the declarative user-service wiring and active documentation for the WSL web-service path while keeping `agent-deck` installed through the develop profile. After the updated config is applied, manually stop or disable any remaining `agent-deck-web.service`, remove generated user-unit artifacts, kill lingering `agent-deck-web` tmux sessions, and delete `~/.agent-deck/web-service.log` if it exists.
