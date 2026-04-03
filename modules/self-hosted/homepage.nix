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
  grimmory-secrets = config.sops.secrets."grimmory-secrets".path;
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
    environmentFiles = [
      gluetun-secrets
      plex-secrets
      tautulli-secrets
      sonarr-secrets
      radarr-secrets
      prowlarr-secrets
      bazarr-secrets
      cloudflared-secrets
      grimmory-secrets
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
          
          service_args=(
            --secrets-file "${gluetun-secrets}"
            --secrets-file "${plex-secrets}"
            --secrets-file "${tautulli-secrets}"
            --secrets-file "${sonarr-secrets}"
            --secrets-file "${radarr-secrets}"
            --secrets-file "${prowlarr-secrets}"
            --secrets-file "${bazarr-secrets}"
            --secrets-file "${cloudflared-secrets}"
            --secrets-file "${grimmory-secrets}"
            
            # Calendar group
            "[Calendar].[Calendar].icon=literal:mdi-calendar"
            "[Calendar].[Calendar].widget.type=literal:calendar"
            "[Calendar].[Calendar].widget.view=literal:agenda"
            "[Calendar].[Calendar].widget.timezone=literal:Pacific/Honolulu"
            
            # Media group
            "[Media].[Plex].icon=literal:plex.png"
            "[Media].[Plex].description=literal:Media Server"
            "[Media].[Plex].server=literal:chill-penguin"
            "[Media].[Plex].container=literal:plex"
            "[Media].[Plex].widget.type=literal:plex"
            "[Media].[Plex].widget.url=literal:http://plex:32400"
            "[Media].[Plex].widget.key=env:PLEX_API_KEY"
            
            "[Media].[Tautulli].icon=literal:tautulli.png"
            "[Media].[Tautulli].description=literal:Plex Monitoring"
            "[Media].[Tautulli].server=literal:chill-penguin"
            "[Media].[Tautulli].container=literal:tautulli"
            "[Media].[Tautulli].widget.type=literal:tautulli"
            "[Media].[Tautulli].widget.url=literal:http://tautulli:8181"
            "[Media].[Tautulli].widget.key=env:TAUTULLI_API_KEY"
            
            "[Media].[RomM].icon=literal:romm.png"
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
            "[Automation].[Sonarr].icon=literal:sonarr.png"
            "[Automation].[Sonarr].description=literal:TV Series Manager"
            "[Automation].[Sonarr].server=literal:chill-penguin"
            "[Automation].[Sonarr].container=literal:sonarr"
            "[Automation].[Sonarr].widget.type=literal:sonarr"
            "[Automation].[Sonarr].widget.url=literal:http://sonarr:8989"
            "[Automation].[Sonarr].widget.key=env:SONARR_API_KEY"
            
            "[Automation].[Radarr].icon=literal:radarr.png"
            "[Automation].[Radarr].description=literal:Movie Manager"
            "[Automation].[Radarr].server=literal:chill-penguin"
            "[Automation].[Radarr].container=literal:radarr"
            "[Automation].[Radarr].widget.type=literal:radarr"
            "[Automation].[Radarr].widget.url=literal:http://radarr:7878"
            "[Automation].[Radarr].widget.key=env:RADARR_API_KEY"
            
            "[Automation].[Prowlarr].icon=literal:prowlarr.png"
            "[Automation].[Prowlarr].description=literal:Indexer Manager"
            "[Automation].[Prowlarr].server=literal:chill-penguin"
            "[Automation].[Prowlarr].container=literal:prowlarr"
            "[Automation].[Prowlarr].widget.type=literal:prowlarr"
            "[Automation].[Prowlarr].widget.url=literal:http://prowlarr:9696"
            "[Automation].[Prowlarr].widget.key=env:PROWLARR_API_KEY"
            
            "[Automation].[Bazarr].icon=literal:bazarr.png"
            "[Automation].[Bazarr].description=literal:Subtitle Manager"
            "[Automation].[Bazarr].server=literal:chill-penguin"
            "[Automation].[Bazarr].container=literal:bazarr"
            "[Automation].[Bazarr].widget.type=literal:bazarr"
            "[Automation].[Bazarr].widget.url=literal:http://bazarr:6767"
            "[Automation].[Bazarr].widget.key=env:BAZARR_API_KEY"
            
            # Downloads group
            "[Downloads].[Cloudflared].icon=literal:cloudflare.png"
            "[Downloads].[Cloudflared].description=literal:Cloudflare Tunnel"
            "[Downloads].[Cloudflared].server=literal:chill-penguin"
            "[Downloads].[Cloudflared].container=literal:cloudflared"
            "[Downloads].[Cloudflared].widget.type=literal:cloudflared"
            "[Downloads].[Cloudflared].widget.accountid=env:CLOUDFLARED_ACCOUNT_ID"
            "[Downloads].[Cloudflared].widget.tunnelid=env:CLOUDFLARED_TUNNEL_ID"
            "[Downloads].[Cloudflared].widget.key=env:CLOUDFLARED_API_TOKEN"

            "[Downloads].[Gluetun].icon=literal:gluetun.png"
            "[Downloads].[Gluetun].description=literal:VPN Client"
            "[Downloads].[Gluetun].server=literal:chill-penguin"
            "[Downloads].[Gluetun].container=literal:gluetun"
            "[Downloads].[Gluetun].widget.type=literal:gluetun"
            "[Downloads].[Gluetun].widget.url=literal:http://gluetun:8000"
            "[Downloads].[Gluetun].widget.key=env:HTTP_CONTROL_SERVER_API_KEY"
            
            "[Downloads].[NZBGet].icon=literal:nzbget.png"
            "[Downloads].[NZBGet].description=literal:NZB Downloader"
            "[Downloads].[NZBGet].server=literal:chill-penguin"
            "[Downloads].[NZBGet].container=literal:nzbget"
            "[Downloads].[NZBGet].widget.type=literal:nzbget"
            "[Downloads].[NZBGet].widget.url=literal:http://gluetun:5001"
            
            "[Downloads].[VueTorrent].icon=literal:vuetorrent.png"
            "[Downloads].[VueTorrent].description=literal:Torrent Downloader"
            "[Downloads].[VueTorrent].server=literal:chill-penguin"
            "[Downloads].[VueTorrent].container=literal:vuetorrent"
            "[Downloads].[VueTorrent].widget.type=literal:qbittorrent"
            "[Downloads].[VueTorrent].widget.url=literal:http://gluetun:5000"
            
            # Services group
            "[Services].[Hermes].icon=literal:mdi-robot-excited-outline-#06b6d4"
            "[Services].[Hermes].description=literal:Agent Terminal"
            "[Services].[Hermes].server=literal:chill-penguin"
            "[Services].[Hermes].container=literal:hermes"

            "[Services].[CloakBrowser].icon=literal:sh-google-chrome"
            "[Services].[CloakBrowser].description=literal:Stealth Browser Manager"
            "[Services].[CloakBrowser].server=literal:chill-penguin"
            "[Services].[CloakBrowser].container=literal:cloakbrowser"

            "[Services].[pyLoad].icon=literal:sh-pyload"
            "[Services].[pyLoad].description=literal:Download Manager"
            "[Services].[pyLoad].server=literal:chill-penguin"
            "[Services].[pyLoad].container=literal:pyload"

            "[Services].[SearXNG].icon=literal:sh-searxng"
            "[Services].[SearXNG].description=literal:Metasearch Engine"
            "[Services].[SearXNG].server=literal:chill-penguin"
            "[Services].[SearXNG].container=literal:searxng"

            "[Services].[RSS-Bridge].icon=literal:mdi-rss-#f97316"
            "[Services].[RSS-Bridge].description=literal:Feed Bridge"
            "[Services].[RSS-Bridge].server=literal:chill-penguin"
            "[Services].[RSS-Bridge].container=literal:rss-bridge"

            "[Services].[Changedetection].icon=literal:mdi-eye-refresh-outline-#0ea5e9"
            "[Services].[Changedetection].description=literal:Website Change Monitor"
            "[Services].[Changedetection].server=literal:chill-penguin"
            "[Services].[Changedetection].container=literal:changedetectionio"

            "[Services].[PriceBuddy].icon=literal:mdi-currency-usd-#22c55e"
            "[Services].[PriceBuddy].description=literal:Price Tracker"
            "[Services].[PriceBuddy].server=literal:chill-penguin"
            "[Services].[PriceBuddy].container=literal:pricebuddy"
            
            # Management group
            "[Management].[Homepage].icon=literal:homepage.png"
            "[Management].[Homepage].description=literal:Dashboard"
            "[Management].[Homepage].server=literal:chill-penguin"
            "[Management].[Homepage].container=literal:homepage"
            
            "[Management].[Muximux].icon=literal:mdi-view-dashboard-#00c853"
            "[Management].[Muximux].description=literal:Lightweight Portal"
            "[Management].[Muximux].server=literal:chill-penguin"
            "[Management].[Muximux].container=literal:muximux"
            
            # Utilities group
            "[Utilities].[Plex Auto Languages].icon=literal:plex.png"
            "[Utilities].[Plex Auto Languages].description=literal:Language Manager"
            "[Utilities].[Plex Auto Languages].server=literal:chill-penguin"
            "[Utilities].[Plex Auto Languages].container=literal:plex-auto-languages"
            
            "[Utilities].[FlareSolverr].icon=literal:flaresolverr.png"
            "[Utilities].[FlareSolverr].description=literal:Proxy Server"
            "[Utilities].[FlareSolverr].server=literal:chill-penguin"
            "[Utilities].[FlareSolverr].container=literal:flaresolverr"
            
            "[Utilities].[BentoPDF].icon=literal:bentopdf.png"
            "[Utilities].[BentoPDF].description=literal:PDF Toolkit"
            "[Utilities].[BentoPDF].server=literal:chill-penguin"
            "[Utilities].[BentoPDF].container=literal:bentopdf"
            
            "[Utilities].[ConvertX].icon=literal:convertx.png"
            "[Utilities].[ConvertX].description=literal:File Converter"
            "[Utilities].[ConvertX].server=literal:chill-penguin"
            "[Utilities].[ConvertX].container=literal:convertx"
            
            "[Utilities].[IT-Tools].icon=literal:it-tools.png"
            "[Utilities].[IT-Tools].description=literal:Developer Tools"
            "[Utilities].[IT-Tools].server=literal:chill-penguin"
            "[Utilities].[IT-Tools].container=literal:it-tools"
            
            "[Utilities].[MeTube].icon=literal:metube.png"
            "[Utilities].[MeTube].description=literal:YouTube Downloader"
            "[Utilities].[MeTube].server=literal:chill-penguin"
            "[Utilities].[MeTube].container=literal:metube"

            "[Utilities].[OmniTools].icon=literal:sh-it-tools"
            "[Utilities].[OmniTools].description=literal:Omni Toolkit"
            "[Utilities].[OmniTools].server=literal:chill-penguin"
            "[Utilities].[OmniTools].container=literal:omni-tools"
            
            # Infrastructure group
            "[Infrastructure].[SearXNG Cache].icon=literal:redis.png"
            "[Infrastructure].[SearXNG Cache].description=literal:Search Cache"
            "[Infrastructure].[SearXNG Cache].server=literal:chill-penguin"
            "[Infrastructure].[SearXNG Cache].container=literal:searxng-valkey"

            "[Infrastructure].[PriceBuddy Scraper].icon=literal:mdi-robot-outline-#0ea5e9"
            "[Infrastructure].[PriceBuddy Scraper].description=literal:PriceBuddy Scraper"
            "[Infrastructure].[PriceBuddy Scraper].server=literal:chill-penguin"
            "[Infrastructure].[PriceBuddy Scraper].container=literal:pricebuddy-scraper"

            "[Infrastructure].[PriceBuddy DB].icon=literal:mdi-database-#8b5cf6"
            "[Infrastructure].[PriceBuddy DB].description=literal:PriceBuddy Database"
            "[Infrastructure].[PriceBuddy DB].server=literal:chill-penguin"
            "[Infrastructure].[PriceBuddy DB].container=literal:pricebuddy-db"

            "[Infrastructure].[RomM DB].icon=literal:mariadb.png"
            "[Infrastructure].[RomM DB].description=literal:RomM Database"
            "[Infrastructure].[RomM DB].server=literal:chill-penguin"
            "[Infrastructure].[RomM DB].container=literal:romm-db"
            
            "[Infrastructure].[Grimmory DB].icon=literal:mariadb.png"
            "[Infrastructure].[Grimmory DB].description=literal:Grimmory Database"
            "[Infrastructure].[Grimmory DB].server=literal:chill-penguin"
            "[Infrastructure].[Grimmory DB].container=literal:grimmory-db"

          )

          ${pkgs.ghostship-config}/bin/ghostship-config set "$SERVICES_FILE" "''${service_args[@]}"

          ${pkgs.yq-go}/bin/yq -i '
            (.[] | select(has("Services")) | .Services) |= map(select(has("Honcho") | not))
            | (.[] | select(has("Infrastructure")) | .Infrastructure) |= map(select((has("Honcho Redis") or has("Honcho DB")) | not))
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
            "1.search.url=literal:https://searxng.ghostship.io/search?q="
            "1.search.focus=literal:true"
            "1.search.target=literal:_self"
            "1.search.suggestionUrl=literal:https://searxng.ghostship.io/autocompleter?q="
            "1.search.showSearchSuggestions=literal:true"
            "2.openmeteo.label=literal:\"the owner's local area\""
            "2.openmeteo.latitude=literal:a home coordinate"
            "2.openmeteo.longitude=literal:a home coordinate"
            "2.openmeteo.timezone=literal:Pacific/Honolulu"
            "2.openmeteo.units=literal:imperial"
          )
          ${pkgs.ghostship-config}/bin/ghostship-config set "$WIDGETS_FILE" "''${widget_args[@]}"
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
