{ ... }:

{
  imports = [
    # Infra
    ./common.nix
    ./app-registry.nix
    ./apparmor.nix
    ./container-apparmor.nix
    ./ca-distrust.nix
    ./siem
    ./container-hardening.nix
    ./container-isolation.nix
    ./security-monitoring.nix
    ./cloudflare-sync.nix
    ./reliability.nix
    ./backup.nix
    ./monitoring.nix
    ./boot-generation-drift.nix
    ./configuration-drift.nix
    ./newsletter-health.nix
    ./notify-coverage.nix
    ./ssh-command-guard.nix
    ./storage-health.nix
    ./synology-health.nix
    ./seerr.nix
    ./cleanup.nix
    ./secrets.nix
    ./gluetun.nix
    ./cloudflared.nix

    # Dashboards
    ./homepage.nix
    ./muximux.nix

    # Media and downloads
    ./tautulli.nix
    ./tdarr.nix
    ./plex.nix
    ./prowlarr.nix
    ./sonarr.nix
    ./radarr.nix
    ./nzbget.nix
    ./qbittorrent.nix
    ./flaresolverr.nix
    ./recyclarr.nix
    ./bazarr.nix
    ./chaptarr.nix
    ./plex-auto-languages.nix
    ./pyload.nix

    # AI usage: read-only provider limits, usage and free models
    ./ai-usage

    # Apps and utilities
    ./agent-desktop.nix
    ./agent-desktop-update.nix
    ./private-integrations.nix
    ./github-engineering.nix
    ./inference-bridge.nix
    ./free-worker.nix
    ./t3code.nix
    ./t3code-hardening.nix
    ./t3code-podman.nix
    ./podman-only.nix
    ../agent-host

    # Games
    ./romm-db.nix
    ./romm.nix
    ./grimmory-db.nix
    ./grimmory.nix
  ];
}
