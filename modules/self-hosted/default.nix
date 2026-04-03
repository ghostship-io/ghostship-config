{ ... }:

{
  imports = [
    # Infra
    ./common.nix
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
    ./plex-auto-languages.nix
    ./searxng.nix
    ./searxng-valkey.nix
    ./pyload.nix

    # Apps and utilities
    ./cloakbrowser.nix
    ./hermes.nix
    ./bentopdf.nix
    ./convertx.nix
    ./it-tools.nix
    ./omnitools.nix
    ./metube.nix
    ./changedetection.nix
    ./rss-bridge.nix
    ./pricebuddy.nix

    # Games
    ./romm-db.nix
    ./romm.nix
    ./grimmory-db.nix
    ./grimmory.nix
  ];
}
