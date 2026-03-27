{ config, lib, pkgs, ... }:

let
  gluetun-secrets = config.sops.secrets."gluetun-secrets".path;
  plex-secrets = config.sops.secrets."plex-secrets".path;
  tautulli-secrets = config.sops.secrets."tautulli-secrets".path;
  sonarr-secrets = config.sops.secrets."sonarr-secrets".path;
  radarr-secrets = config.sops.secrets."radarr-secrets".path;
  prowlarr-secrets = config.sops.secrets."prowlarr-secrets".path;
  bazarr-secrets = config.sops.secrets."bazarr-secrets".path;
  cloudflared-secrets = config.sops.secrets."cloudflared-secrets".path;
in

{
  virtualisation.oci-containers.containers."homepage" = {
    image = "ghcr.io/gethomepage/homepage:latest";
    user = "3000:3000";
    extraOptions = [
      "--network=ghostship_net"
      "--group-add=989"
      "--group-add=131"
      "--health-cmd=wget --quiet --tries=1 --spider http://localhost:3000 || exit 1"
      "--health-interval=10s"
      "--health-retries=3"
      "--health-start-period=30s"
    ];
    environment = {
      HOMEPAGE_ALLOWED_HOSTS = "homepage.ghostship.io";
      HOMEPAGE_SKIP_METADATA = "true";
    };
    volumes = [
      "/srv/apps/homepage:/app/config:rw"
      "/run/podman/podman.sock:/var/run/podman.sock:ro"
    ];
  };

  systemd.tmpfiles.rules = [
    "d /srv/apps/homepage 0755 apps apps -"
    "d /srv/apps/homepage/logs 0755 apps apps -"
  ];

  system.activationScripts.homepage-config = {
    text = ''
      SETTINGS_FILE="/srv/apps/homepage/settings.yaml"
      SERVICES_FILE="/srv/apps/homepage/services.yaml"
      DOCKER_FILE="/srv/apps/homepage/docker.yaml"

      # Check if config directory exists
      if [ ! -d "/srv/apps/homepage" ]; then
        echo "Homepage config directory not found, skipping activation"
        exit 0
      fi

      # Update settings.yaml if it exists
      if [ -f "$SETTINGS_FILE" ]; then
        echo "Surgically updating Homepage settings..."
        ${pkgs.ghostship-config}/bin/ghostship-config set "$SETTINGS_FILE" \
          title=literal:"Ghostship Dashboard" \
          quicklaunch.hideInternetSearch=literal:true
      fi

      # Update services.yaml if it exists
      if [ -f "$SERVICES_FILE" ]; then
        echo "Surgically updating Homepage services..."
        ${pkgs.ghostship-config}/bin/ghostship-config set "$SERVICES_FILE" \
          --secrets-file "${gluetun-secrets}" \
          --secrets-file "${plex-secrets}" \
          --secrets-file "${tautulli-secrets}" \
          --secrets-file "${sonarr-secrets}" \
          --secrets-file "${radarr-secrets}" \
          --secrets-file "${prowlarr-secrets}" \
          --secrets-file "${bazarr-secrets}" \
          --secrets-file "${cloudflared-secrets}" \
          "[Calendar].[Calendar].icon=literal:mdi-calendar" \
          "[Calendar].[Calendar].widget.type=literal:calendar" \
          "[Calendar].[Calendar].widget.view=literal:agenda" \
          "[Calendar].[Calendar].widget.timezone=literal:Pacific/Honolulu" \
          "[Plex].[Plex].icon=literal:plex.png" \
          "[Plex].[Plex].description=literal:\"Media Server\"" \
          "[Plex].[Plex].server=literal:chill-penguin" \
          "[Plex].[Plex].container=literal:plex" \
          "[Plex].[Plex].widget.type=literal:plex" \
          "[Plex].[Plex].widget.url=literal:http://plex:32400" \
          "[Plex].[Plex].widget.key=env:PLEX_API_KEY" \
          "[Plex].[Tautulli].icon=literal:tautulli.png" \
          "[Plex].[Tautulli].description=literal:\"Plex Monitoring\"" \
          "[Plex].[Tautulli].server=literal:chill-penguin" \
          "[Plex].[Tautulli].container=literal:tautulli" \
          "[Plex].[Tautulli].widget.type=literal:tautulli" \
          "[Plex].[Tautulli].widget.url=literal:http://tautulli:8181" \
          "[Plex].[Tautulli].widget.key=env:TAUTULLI_API_KEY" \
          "[Plex].[Plex Auto Languages].icon=literal:plex.png" \
          "[Plex].[Plex Auto Languages].description=literal:\"Language Manager\"" \
          "[Plex].[Plex Auto Languages].server=literal:chill-penguin" \
          "[Plex].[Plex Auto Languages].container=literal:plex-auto-languages" \
          "[Library].[Sonarr].icon=literal:sonarr.png" \
          "[Library].[Sonarr].description=literal:\"TV Series Manager\"" \
          "[Library].[Sonarr].server=literal:chill-penguin" \
          "[Library].[Sonarr].container=literal:sonarr" \
          "[Library].[Sonarr].widget.type=literal:sonarr" \
          "[Library].[Sonarr].widget.url=literal:http://sonarr:8989" \
          "[Library].[Sonarr].widget.key=env:SONARR_API_KEY" \
          "[Library].[Radarr].icon=literal:radarr.png" \
          "[Library].[Radarr].description=literal:\"Movie Manager\"" \
          "[Library].[Radarr].server=literal:chill-penguin" \
          "[Library].[Radarr].container=literal:radarr" \
          "[Library].[Radarr].widget.type=literal:radarr" \
          "[Library].[Radarr].widget.url=literal:http://radarr:7878" \
          "[Library].[Radarr].widget.key=env:RADARR_API_KEY" \
          "[Library].[RomM].icon=literal:romm.png" \
          "[Library].[RomM].description=literal:\"ROM Manager\"" \
          "[Library].[RomM].server=literal:chill-penguin" \
          "[Library].[RomM].container=literal:romm" \
          "[Library].[RomM].widget.type=literal:romm" \
          "[Library].[RomM].widget.url=literal:http://romm:8080" \
          "[Library].[Grimmory].icon=literal:sh-booklore" \
          "[Library].[Grimmory].description=literal:\"Ebook Manager\"" \
          "[Library].[Grimmory].server=literal:chill-penguin" \
          "[Library].[Grimmory].container=literal:grimmory" \
          "[Library].[Manyfold].icon=literal:manyfold.png" \
          "[Library].[Manyfold].description=literal:\"3D Model Manager\"" \
          "[Library].[Manyfold].server=literal:chill-penguin" \
          "[Library].[Manyfold].container=literal:manyfold" \
          "[Library].[Huntarr].icon=literal:huntarr.png" \
          "[Library].[Huntarr].description=literal:\"Content Searcher\"" \
          "[Library].[Huntarr].server=literal:chill-penguin" \
          "[Library].[Huntarr].container=literal:huntarr" \
          "[Downloads].[Gluetun].icon=literal:gluetun.png" \
          "[Downloads].[Gluetun].description=literal:\"VPN Client\"" \
          "[Downloads].[Gluetun].server=literal:chill-penguin" \
          "[Downloads].[Gluetun].container=literal:gluetun" \
          "[Downloads].[Gluetun].widget.type=literal:gluetun" \
          "[Downloads].[Gluetun].widget.url=literal:http://gluetun:8000" \
          "[Downloads].[Gluetun].widget.key=env:HTTP_CONTROL_SERVER_API_KEY" \
          "[Downloads].[NZBGet].icon=literal:nzbget.png" \
          "[Downloads].[NZBGet].description=literal:\"NZB Downloader\"" \
          "[Downloads].[NZBGet].server=literal:chill-penguin" \
          "[Downloads].[NZBGet].container=literal:nzbget" \
          "[Downloads].[NZBGet].widget.type=literal:nzbget" \
          "[Downloads].[NZBGet].widget.url=literal:http://gluetun:5001" \
          "[Downloads].[VueTorrent].icon=literal:vuetorrent.png" \
          "[Downloads].[VueTorrent].description=literal:\"Torrent Downloader\"" \
          "[Downloads].[VueTorrent].server=literal:chill-penguin" \
          "[Downloads].[VueTorrent].container=literal:vuetorrent" \
          "[Downloads].[VueTorrent].widget.type=literal:qbittorrent" \
          "[Downloads].[VueTorrent].widget.url=literal:http://gluetun:5000" \
          "[Utilities].[Prowlarr].icon=literal:prowlarr.png" \
          "[Utilities].[Prowlarr].description=literal:\"Indexer Manager\"" \
          "[Utilities].[Prowlarr].server=literal:chill-penguin" \
          "[Utilities].[Prowlarr].container=literal:prowlarr" \
          "[Utilities].[Prowlarr].widget.type=literal:prowlarr" \
          "[Utilities].[Prowlarr].widget.url=literal:http://prowlarr:9696" \
          "[Utilities].[Prowlarr].widget.key=env:PROWLARR_API_KEY" \
          "[Utilities].[FlareSolverr].icon=literal:flaresolverr.png" \
          "[Utilities].[FlareSolverr].description=literal:\"Proxy Server\"" \
          "[Utilities].[FlareSolverr].server=literal:chill-penguin" \
          "[Utilities].[FlareSolverr].container=literal:flaresolverr" \
          "[Utilities].[BentoPDF].icon=literal:bentopdf.png" \
          "[Utilities].[BentoPDF].description=literal:\"PDF Toolkit\"" \
          "[Utilities].[BentoPDF].server=literal:chill-penguin" \
          "[Utilities].[BentoPDF].container=literal:bentopdf" \
          "[Utilities].[ConvertX].icon=literal:convertx.png" \
          "[Utilities].[ConvertX].description=literal:\"File Converter\"" \
          "[Utilities].[ConvertX].server=literal:chill-penguin" \
          "[Utilities].[ConvertX].container=literal:convertx" \
          "[Utilities].[IT-Tools].icon=literal:it-tools.png" \
          "[Utilities].[IT-Tools].description=literal:\"Developer Tools\"" \
          "[Utilities].[IT-Tools].server=literal:chill-penguin" \
          "[Utilities].[IT-Tools].container=literal:it-tools" \
          "[Utilities].[MeTube].icon=literal:metube.png" \
          "[Utilities].[MeTube].description=literal:\"YouTube Downloader\"" \
          "[Utilities].[MeTube].server=literal:chill-penguin" \
          "[Utilities].[MeTube].container=literal:metube" \
          "[Automation].[Bazarr].icon=literal:bazarr.png" \
          "[Automation].[Bazarr].description=literal:\"Subtitle Manager\"" \
          "[Automation].[Bazarr].server=literal:chill-penguin" \
          "[Automation].[Bazarr].container=literal:bazarr" \
          "[Automation].[Bazarr].widget.type=literal:bazarr" \
          "[Automation].[Bazarr].widget.url=literal:http://bazarr:6767" \
          "[Automation].[Bazarr].widget.key=env:BAZARR_API_KEY" \
          "[Management].[Homepage].icon=literal:homepage.png" \
          "[Management].[Homepage].description=literal:Dashboard" \
          "[Management].[Homepage].server=literal:chill-penguin" \
          "[Management].[Homepage].container=literal:homepage" \
          "[Management].[Muximux].icon=literal:mdi-view-dashboard-#00c853" \
          "[Management].[Muximux].description=literal:\"Lightweight Portal\"" \
          "[Management].[Muximux].server=literal:chill-penguin" \
          "[Management].[Muximux].container=literal:muximux" \
          "[Management].[Cloudflared].icon=literal:cloudflare.png" \
          "[Management].[Cloudflared].description=literal:\"Cloudflare Tunnel\"" \
          "[Management].[Cloudflared].server=literal:chill-penguin" \
          "[Management].[Cloudflared].container=literal:cloudflared" \
          "[Management].[Cloudflared].widget.type=literal:cloudflared" \
          "[Management].[Cloudflared].widget.accountid=literal:the owner's local area" \
          "[Management].[Cloudflared].widget.tunnelid=literal:d0e34b31-7ec6-432d-82b8-70323bc3d921" \
          "[Management].[Cloudflared].widget.key=env:CLOUDFLARE_API_TOKEN" \
          "[Infrastructure].[SearXNG].icon=literal:sh-searxng" \
          "[Infrastructure].[SearXNG].description=literal:\"Metasearch Engine\"" \
          "[Infrastructure].[SearXNG].server=literal:chill-penguin" \
          "[Infrastructure].[SearXNG].container=literal:searxng" \
          "[Infrastructure].[SearXNG Cache].icon=literal:redis.png" \
          "[Infrastructure].[SearXNG Cache].description=literal:\"Search Cache\"" \
          "[Infrastructure].[SearXNG Cache].server=literal:chill-penguin" \
          "[Infrastructure].[SearXNG Cache].container=literal:searxng-valkey" \
          "[Infrastructure].[RomM DB].icon=literal:mariadb.png" \
          "[Infrastructure].[RomM DB].description=literal:\"RomM Database\"" \
          "[Infrastructure].[RomM DB].server=literal:chill-penguin" \
          "[Infrastructure].[RomM DB].container=literal:romm-db" \
          "[Infrastructure].[Grimmory DB].icon=literal:mariadb.png" \
          "[Infrastructure].[Grimmory DB].description=literal:\"Grimmory Database\"" \
          "[Infrastructure].[Grimmory DB].server=literal:chill-penguin" \
          "[Infrastructure].[Grimmory DB].container=literal:grimmory-db"

      fi

      # Update widgets.yaml if it exists
      WIDGETS_FILE="/srv/apps/homepage/widgets.yaml"
      if [ -f "$WIDGETS_FILE" ]; then
        echo "Surgically updating Homepage widgets..."
        ${pkgs.ghostship-config}/bin/ghostship-config set "$WIDGETS_FILE" \
          "0.resources.cpu=literal:true" \
          "0.resources.memory=literal:true" \
          "0.resources.disk=literal:/" \
          "0.resources.network=literal:true" \
          "1.search.provider=literal:custom" \
          "1.search.url=literal:https://searxng.ghostship.io/search?q=" \
          "1.search.focus=literal:true" \
          "1.search.target=literal:_self" \
          "1.search.suggestionUrl=literal:https://searxng.ghostship.io/autocompleter?q=" \
          "1.search.showSearchSuggestions=literal:true" \
          "2.openmeteo.label=literal:\"the owner's local area\"" \
          "2.openmeteo.latitude=literal:a home coordinate" \
          "2.openmeteo.longitude=literal:a home coordinate" \
          "2.openmeteo.timezone=literal:Pacific/Honolulu" \
          "2.openmeteo.units=literal:imperial"
      fi

      # Update docker.yaml if it exists
      if [ -f "$DOCKER_FILE" ]; then
        echo "Surgically updating Homepage docker config..."
        ${pkgs.ghostship-config}/bin/ghostship-config set "$DOCKER_FILE" \
          chill-penguin.socket=literal:/var/run/podman.sock
      fi

      chown -R apps:apps /srv/apps/homepage
    '';
  };
}
