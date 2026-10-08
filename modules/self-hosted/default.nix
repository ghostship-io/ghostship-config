{ ... }:

{
  imports = [
    # Infra
    ./common.nix
    ./app-registry.nix
    ./cloudflare-sync.nix
    ./reliability.nix
    ./backup.nix
    ./monitoring.nix
    ./storage-health.nix
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
    ./private-integrations.nix
    ./cloakbrowser.nix
    ./t3code.nix
    ../agent-host

    # Games
    ./romm-db.nix
    ./romm.nix
    ./grimmory-db.nix
    ./grimmory.nix
  ];
}
