{ ... }:

{
  imports = [
    # Infra
    ./common.nix
    ./cleanup.nix
    ./secrets.nix
    ./gluetun.nix
    ./cloudflared.nix

    # Dashboards
    ./homepage.nix
    ./muximux.nix

    # Media and downloads
    ./tautulli.nix
    ./plex.nix
    ./prowlarr.nix
    ./sonarr.nix
    ./radarr.nix
    ./nzbget.nix
    ./vuetorrent.nix
    ./flaresolverr.nix
    ./recyclarr.nix
    ./bazarr.nix
    ./chaptarr.nix
    ./plex-auto-languages.nix
    ./pyload.nix

    # Apps and utilities
    ./cloakbrowser.nix
    ./prefect.nix
    ./rss-bridge.nix
    ./codex.nix

    # Games
    ./romm-db.nix
    ./romm.nix
    ./grimmory-db.nix
    ./grimmory.nix
  ];
}
