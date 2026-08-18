{
  config,
  lib,
  pkgs,
  ...
}:

let
  homepage-secrets = config.ghostship.selfHostedSecrets.projections.homepage.path;
  render-homepage-secrets = "${config.ghostship.selfHostedSecrets.render}/bin/ghostship-secret-project homepage";
in

{
  virtualisation.oci-containers.containers."homepage" = {
    image = "ghcr.io/gethomepage/homepage:latest";
    pull = "always";
    labels = {
      "io.containers.autoupdate" = "registry";
    };
    user = "3000:3000";
    extraOptions = [
      "--network=ghostship_net"
      "--group-add=989"
      "--group-add=131"
      "--health-cmd=wget -q --spider --tries=1 --timeout=5 http://127.0.0.1:3000/ || exit 1"
      "--health-interval=30s"
      "--health-timeout=10s"
      "--health-retries=5"
      "--health-start-period=1m"
      "--health-on-failure=kill"
    ];
    environment = {
      HOMEPAGE_ALLOWED_HOSTS = "homepage.ghostship.io";
      HOMEPAGE_SKIP_METADATA = "true";
    };
    volumes = [
      "/srv/apps/homepage:/app/config:rw"
      "/run/podman/podman.sock:/var/run/podman.sock:ro"
      "/sys/class/net:/sys/class/net:ro"
      "/sys/devices/platform:/sys/devices/platform:ro"
    ];
    environmentFiles = [ homepage-secrets ];
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
      if [ -d "/srv/apps/homepage" ]; then
        # Update settings.yaml if it exists
        if [ -f "$SETTINGS_FILE" ]; then
          echo "Surgically updating Homepage settings..."
          settings_args=(
            title=literal:"Ghostship Dashboard"
            quicklaunch.hideInternetSearch=literal:true
          )
          ${pkgs.ghostship-config}/bin/ghostship-config set "$SETTINGS_FILE" "''${settings_args[@]}"
          fi
        # Update services.yaml if it exists
        if [ -f "$SERVICES_FILE" ]; then
          echo "Surgically updating Homepage services..."
          
          ${render-homepage-secrets}

          service_args=(
            --secrets-file "${homepage-secrets}"
            
            # Calendar group
            "[Calendar].[Calendar].icon=literal:sh-fluidcalendar"
            "[Calendar].[Calendar].widget.type=literal:calendar"
            "[Calendar].[Calendar].widget.view=literal:agenda"
            "[Calendar].[Calendar].widget.timezone=literal:Pacific/Honolulu"
            
            # Media group
            "[Media].[Plex].icon=literal:sh-plex"
            "[Media].[Plex].description=literal:Media Server"
            "[Media].[Plex].server=literal:chill-penguin"
            "[Media].[Plex].container=literal:plex"
            "[Media].[Plex].widget.type=literal:plex"
            "[Media].[Plex].widget.url=literal:http://plex:32400"
            "[Media].[Plex].widget.key=env:PLEX_API_KEY"
            
            "[Media].[Tautulli].icon=literal:sh-tautulli"
            "[Media].[Tautulli].description=literal:Plex Monitoring"
            "[Media].[Tautulli].server=literal:chill-penguin"
            "[Media].[Tautulli].container=literal:tautulli"
            "[Media].[Tautulli].widget.type=literal:tautulli"
            "[Media].[Tautulli].widget.url=literal:http://tautulli:8181"
            "[Media].[Tautulli].widget.key=env:TAUTULLI_API_KEY"
            
            "[Media].[RomM].icon=literal:sh-romm"
            "[Media].[RomM].description=literal:ROM Manager"
            "[Media].[RomM].server=literal:chill-penguin"
            "[Media].[RomM].container=literal:romm"
            "[Media].[RomM].widget.type=literal:romm"
            "[Media].[RomM].widget.url=literal:http://romm:8080"
            
            "[Media].[Grimmory].icon=literal:sh-booklore"
            "[Media].[Grimmory].description=literal:Ebook Manager"
            "[Media].[Grimmory].server=literal:chill-penguin"
            "[Media].[Grimmory].container=literal:grimmory"
            "[Media].[Grimmory].widget.type=literal:booklore"
            "[Media].[Grimmory].widget.url=literal:http://grimmory:6060"
            "[Media].[Grimmory].widget.username=env:GRIMMORY_USER"
            "[Media].[Grimmory].widget.password=env:GRIMMORY_PASS"
            "[Media].[Grimmory].dd=yaml:false"
            
            # Automation group
            "[Automation].[Sonarr].icon=literal:sh-sonarr"
            "[Automation].[Sonarr].description=literal:TV Series Manager"
            "[Automation].[Sonarr].server=literal:chill-penguin"
            "[Automation].[Sonarr].container=literal:sonarr"
            "[Automation].[Sonarr].widget.type=literal:sonarr"
            "[Automation].[Sonarr].widget.url=literal:http://sonarr:8989"
            "[Automation].[Sonarr].widget.key=env:SONARR_API_KEY"
            
            "[Automation].[Radarr].icon=literal:sh-radarr"
            "[Automation].[Radarr].description=literal:Movie Manager"
            "[Automation].[Radarr].server=literal:chill-penguin"
            "[Automation].[Radarr].container=literal:radarr"
            "[Automation].[Radarr].widget.type=literal:radarr"
            "[Automation].[Radarr].widget.url=literal:http://radarr:7878"
            "[Automation].[Radarr].widget.key=env:RADARR_API_KEY"
            
            "[Automation].[Prowlarr].icon=literal:sh-prowlarr"
            "[Automation].[Prowlarr].description=literal:Indexer Manager"
            "[Automation].[Prowlarr].server=literal:chill-penguin"
            "[Automation].[Prowlarr].container=literal:prowlarr"
            "[Automation].[Prowlarr].widget.type=literal:prowlarr"
            "[Automation].[Prowlarr].widget.url=literal:http://prowlarr:9696"
            "[Automation].[Prowlarr].widget.key=env:PROWLARR_API_KEY"
            
            "[Automation].[Bazarr].icon=literal:sh-bazarr"
            "[Automation].[Bazarr].description=literal:Subtitle Manager"
            "[Automation].[Bazarr].server=literal:chill-penguin"
            "[Automation].[Bazarr].container=literal:bazarr"
            "[Automation].[Bazarr].widget.type=literal:bazarr"
            "[Automation].[Bazarr].widget.url=literal:http://bazarr:6767"
            "[Automation].[Bazarr].widget.key=env:BAZARR_API_KEY"

            "[Automation].[Chaptarr].icon=literal:sh-readarr"
            "[Automation].[Chaptarr].description=literal:Book Manager"
            "[Automation].[Chaptarr].server=literal:chill-penguin"
            "[Automation].[Chaptarr].container=literal:chaptarr"
            "[Automation].[Chaptarr].widget.type=literal:readarr"
            "[Automation].[Chaptarr].widget.url=literal:http://chaptarr:8789"
            "[Automation].[Chaptarr].widget.key=env:CHAPTARR_API_KEY"
            

            # Downloads group
            "[Downloads].[Cloudflared].icon=literal:sh-cloudflare"
            "[Downloads].[Cloudflared].description=literal:Cloudflare Tunnel"
            "[Downloads].[Cloudflared].server=literal:chill-penguin"
            "[Downloads].[Cloudflared].container=literal:cloudflared"
            "[Downloads].[Cloudflared].widget.type=literal:cloudflared"
            "[Downloads].[Cloudflared].widget.accountid=env:CLOUDFLARED_ACCOUNT_ID"
            "[Downloads].[Cloudflared].widget.tunnelid=env:CLOUDFLARED_TUNNEL_ID"
            "[Downloads].[Cloudflared].widget.key=env:CLOUDFLARED_API_TOKEN"

            "[Downloads].[Gluetun].icon=literal:sh-gluetun"
            "[Downloads].[Gluetun].description=literal:VPN Client"
            "[Downloads].[Gluetun].server=literal:chill-penguin"
            "[Downloads].[Gluetun].container=literal:gluetun"
            "[Downloads].[Gluetun].widget.type=literal:gluetun"
            "[Downloads].[Gluetun].widget.url=literal:http://gluetun:8000"
            "[Downloads].[Gluetun].widget.key=env:HTTP_CONTROL_SERVER_API_KEY"

            "[Downloads].[NZBGet].icon=literal:sh-nzbget"
            "[Downloads].[NZBGet].description=literal:NZB Downloader"
            "[Downloads].[NZBGet].server=literal:chill-penguin"
            "[Downloads].[NZBGet].container=literal:nzbget"
            "[Downloads].[NZBGet].widget.type=literal:nzbget"
            "[Downloads].[NZBGet].widget.url=literal:http://gluetun:5001"
            "[Downloads].[NZBGet].widget.username=literal:ghostship"
            "[Downloads].[NZBGet].widget.password=literal:"

            "[Downloads].[qBittorrent].icon=literal:sh-qbittorrent"
            "[Downloads].[qBittorrent].description=literal:Torrent Downloader"
            "[Downloads].[qBittorrent].server=literal:chill-penguin"
            "[Downloads].[qBittorrent].container=literal:qbittorrent"
            "[Downloads].[qBittorrent].widget.type=literal:qbittorrent"
            "[Downloads].[qBittorrent].widget.url=literal:http://gluetun:5000"

            # Services group
            "[Services].[pyLoad].icon=literal:sh-pyload"
            "[Services].[pyLoad].description=literal:Download Manager"
            "[Services].[pyLoad].server=literal:chill-penguin"
            "[Services].[pyLoad].container=literal:pyload"

            "[Services].[OpenChamber].icon=literal:mdi-code-braces-#111827"
            "[Services].[OpenChamber].href=literal:https://openchamber.ghostship.io"
            "[Services].[OpenChamber].description=literal:OpenChamber Web"
            "[Services].[OpenChamber].server=literal:chill-penguin"
            "[Services].[OpenChamber].container=literal:openchamber"

            # Management group
            "[Management].[Homepage].icon=literal:sh-homepage"
            "[Management].[Homepage].description=literal:Dashboard"
            "[Management].[Homepage].server=literal:chill-penguin"
            "[Management].[Homepage].container=literal:homepage"

            "[Management].[Muximux].icon=literal:mdi-view-dashboard-#00c853"
            "[Management].[Muximux].description=literal:Lightweight Portal"
            "[Management].[Muximux].server=literal:chill-penguin"
            "[Management].[Muximux].container=literal:muximux"

            "[Management].[CloakBrowser].icon=literal:sh-google-chrome"
            "[Management].[CloakBrowser].href=literal:https://cloakbrowser.ghostship.io"
            "[Management].[CloakBrowser].description=literal:Browser Profile Manager"
            "[Management].[CloakBrowser].server=literal:chill-penguin"
            "[Management].[CloakBrowser].container=literal:cloakbrowser"

            # Utilities group
            "[Utilities].[FlareSolverr].icon=literal:sh-flaresolverr"
            "[Utilities].[FlareSolverr].description=literal:Proxy Server"
            "[Utilities].[FlareSolverr].server=literal:chill-penguin"
            "[Utilities].[FlareSolverr].container=literal:flaresolverr"

            "[Utilities].[Plex Auto Languages].icon=literal:sh-plex"
            "[Utilities].[Plex Auto Languages].description=literal:Language Manager"
            "[Utilities].[Plex Auto Languages].server=literal:chill-penguin"
            "[Utilities].[Plex Auto Languages].container=literal:plex-auto-languages"

          )

          ${pkgs.ghostship-config}/bin/ghostship-config set "$SERVICES_FILE" "''${service_args[@]}"

          ${pkgs.yq-go}/bin/yq -i '
            (.[] | select(has("Services")) | .Services) |= map(select((has("Paseo") or has("Hermes") or has("Honcho") or has("Firecrawl") or has("Firecrawl Playwright") or has("PriceBuddy") or has("PriceBuddy Scraper") or has("Changedetection") or has("n8n") or has("SearXNG") or has("Windmill") or has("Hatchet") or has("Prefect")) | not))
            | (.[] | select(has("Downloads")) | .Downloads) |= map(select((has("VueTorrent")) | not))
            | (.[] | select(has("Management")) | .Management) |= map(select((has("Codex") or has("T3 Code") or has("n8n") or has("Changedetection") or has("BookStack") or has("SearXNG") or has("Plex Auto Languages") or has("PriceBuddy Scraper")) | not))
            | (.[] | select(has("Utilities")) | .Utilities) |= map(select((has("BentoPDF") or has("ConvertX") or has("IT-Tools") or has("MeTube") or has("OmniTools")) | not))
            | (.[] | select(has("Utilities")) | .Utilities) |= map(select((has("SearXNG") or has("Firecrawl") or has("Firecrawl Playwright")) | not))
            | (.[] | select(has("Infrastructure")) | .Infrastructure) |= map(select((has("Honcho Redis") or has("Honcho DB") or has("Firecrawl Postgres") or has("Firecrawl RabbitMQ") or has("Firecrawl Redis")) | not))
            | (.[] | select(has("Infrastructure")) | .Infrastructure) |= map(select((has("FlareSolverr") or has("Firecrawl Playwright") or has("PriceBuddy") or has("PriceBuddy DB") or has("PriceBuddy Scraper") or has("SearXNG Cache")) | not))
          ' "$SERVICES_FILE"
        fi

        # Update widgets.yaml if it exists
        WIDGETS_FILE="/srv/apps/homepage/widgets.yaml"
        if [ -f "$WIDGETS_FILE" ]; then
          echo "Surgically updating Homepage widgets..."
          widget_args=(
            "0.resources.cpu=yaml:true"
            "0.resources.memory=yaml:true"
            "0.resources.disk=literal:/"
            "0.resources.network=literal:end0"
            "1.search.provider=literal:custom"
            "1.search.url=literal:https://duckduckgo.com/?q="
            "1.search.focus=literal:true"
            "1.search.target=literal:_blank"
            "1.search.showSearchSuggestions=literal:false"
            "2.openmeteo.label=literal:\"the owner's local area\""
            "2.openmeteo.latitude=literal:a home coordinate"
            "2.openmeteo.longitude=literal:a home coordinate"
            "2.openmeteo.timezone=literal:Pacific/Honolulu"
            "2.openmeteo.units=literal:imperial"
          )
          ${pkgs.ghostship-config}/bin/ghostship-config set "$WIDGETS_FILE" "''${widget_args[@]}"
          ${pkgs.yq-go}/bin/yq -i 'del(.[1].search.suggestionUrl)' "$WIDGETS_FILE"
        fi

        # Update docker.yaml if it exists
        if [ -f "$DOCKER_FILE" ]; then
          echo "Surgically updating Homepage docker config..."
          docker_args=(
            chill-penguin.socket=literal:/var/run/podman.sock
          )
          ${pkgs.ghostship-config}/bin/ghostship-config set "$DOCKER_FILE" "''${docker_args[@]}"
        fi

        chown -R apps:apps /srv/apps/homepage
      else
        echo "Homepage config directory not found, skipping activation"
      fi
    '';
  };
}
