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
    ./security-monitoring.nix
    ./cloudflare-sync.nix
    ./reliability.nix
    ./backup.nix
    ./monitoring.nix
    ./notify-coverage.nix
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

    # Apps and utilities
    ./agent-desktop.nix
    ./agent-desktop-update.nix
    ./private-integrations.nix
    ./github-engineering.nix
    ./inference-bridge.nix
    ./t3code.nix
    ./t3code-hardening.nix
    ../agent-host

    # Games
    ./romm-db.nix
    ./romm.nix
    ./grimmory-db.nix
    ./grimmory.nix
  ];
}
