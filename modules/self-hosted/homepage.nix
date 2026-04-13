{ config, lib, pkgs, ... }:

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
            
            "[Downloads].[VueTorrent].icon=literal:sh-vuetorrent"
            "[Downloads].[VueTorrent].description=literal:Torrent Downloader"
            "[Downloads].[VueTorrent].server=literal:chill-penguin"
            "[Downloads].[VueTorrent].container=literal:vuetorrent"
            "[Downloads].[VueTorrent].widget.type=literal:qbittorrent"
            "[Downloads].[VueTorrent].widget.url=literal:http://gluetun:5000"
            
            # Services group
            "[Services].[Hermes].icon=literal:sh-agent-zero"
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

            "[Services].[RSS-Bridge].icon=literal:rss-bridge"
            "[Services].[RSS-Bridge].description=literal:Feed Bridge"
            "[Services].[RSS-Bridge].server=literal:chill-penguin"
            "[Services].[RSS-Bridge].container=literal:rss-bridge"

            "[Services].[Changedetection].icon=literal:sh-changedetection"
            "[Services].[Changedetection].description=literal:Website Change Monitor"
            "[Services].[Changedetection].server=literal:chill-penguin"
            "[Services].[Changedetection].container=literal:changedetection"

            "[Services].[BookStack].icon=literal:sh-bookstack"
            "[Services].[BookStack].description=literal:Documentation Wiki"
            "[Services].[BookStack].server=literal:chill-penguin"
            "[Services].[BookStack].container=literal:bookstack"
            "[Services].[BookStack].href=literal:https://bookstack.ghostship.io"

            "[Services].[PriceBuddy].icon=literal:sh-priceghost"
            "[Services].[PriceBuddy].description=literal:Price Tracker"
            "[Services].[PriceBuddy].server=literal:chill-penguin"
            "[Services].[PriceBuddy].container=literal:pricebuddy"

            "[Services].[n8n].icon=literal:sh-n8n"
            "[Services].[n8n].description=literal:Workflow Orchestrator"
            "[Services].[n8n].server=literal:chill-penguin"
            "[Services].[n8n].container=literal:n8n"
            
            # Management group
            "[Management].[Homepage].icon=literal:sh-homepage"
            "[Management].[Homepage].description=literal:Dashboard"
            "[Management].[Homepage].server=literal:chill-penguin"
            "[Management].[Homepage].container=literal:homepage"
            
            "[Management].[Muximux].icon=literal:mdi-view-dashboard-#00c853"
            "[Management].[Muximux].description=literal:Lightweight Portal"
            "[Management].[Muximux].server=literal:chill-penguin"
            "[Management].[Muximux].container=literal:muximux"
            
            # Utilities group
            "[Utilities].[Plex Auto Languages].icon=literal:sh-plex"
            "[Utilities].[Plex Auto Languages].description=literal:Language Manager"
            "[Utilities].[Plex Auto Languages].server=literal:chill-penguin"
            "[Utilities].[Plex Auto Languages].container=literal:plex-auto-languages"
            
            "[Utilities].[FlareSolverr].icon=literal:sh-flaresolverr"
            "[Utilities].[FlareSolverr].description=literal:Proxy Server"
            "[Utilities].[FlareSolverr].server=literal:chill-penguin"
            "[Utilities].[FlareSolverr].container=literal:flaresolverr"
            
            "[Utilities].[BentoPDF].icon=literal:sh-bentopdf"
            "[Utilities].[BentoPDF].description=literal:PDF Toolkit"
            "[Utilities].[BentoPDF].server=literal:chill-penguin"
            "[Utilities].[BentoPDF].container=literal:bentopdf"
            
            "[Utilities].[ConvertX].icon=literal:sh-convertx"
            "[Utilities].[ConvertX].description=literal:File Converter"
            "[Utilities].[ConvertX].server=literal:chill-penguin"
            "[Utilities].[ConvertX].container=literal:convertx"
            
            "[Utilities].[IT-Tools].icon=literal:sh-it-tools"
            "[Utilities].[IT-Tools].description=literal:Developer Tools"
            "[Utilities].[IT-Tools].server=literal:chill-penguin"
            "[Utilities].[IT-Tools].container=literal:it-tools"
            
            "[Utilities].[MeTube].icon=literal:sh-metube"
            "[Utilities].[MeTube].description=literal:YouTube Downloader"
            "[Utilities].[MeTube].server=literal:chill-penguin"
            "[Utilities].[MeTube].container=literal:metube"

            "[Utilities].[OmniTools].icon=literal:sh-omnitools"
            "[Utilities].[OmniTools].description=literal:Omni Toolkit"
            "[Utilities].[OmniTools].server=literal:chill-penguin"
            "[Utilities].[OmniTools].container=literal:omni-tools"
            
            # Infrastructure group
            "[Infrastructure].[SearXNG Cache].icon=literal:sh-redis"
            "[Infrastructure].[SearXNG Cache].description=literal:Search Cache"
            "[Infrastructure].[SearXNG Cache].server=literal:chill-penguin"
            "[Infrastructure].[SearXNG Cache].container=literal:searxng-valkey"

            "[Infrastructure].[PriceBuddy Scraper].icon=literal:web-check"
            "[Infrastructure].[PriceBuddy Scraper].description=literal:PriceBuddy Scraper"
            "[Infrastructure].[PriceBuddy Scraper].server=literal:chill-penguin"
            "[Infrastructure].[PriceBuddy Scraper].container=literal:pricebuddy-scraper"

            "[Infrastructure].[PriceBuddy DB].icon=literal:sh-mariadb"
            "[Infrastructure].[PriceBuddy DB].description=literal:PriceBuddy Database"
            "[Infrastructure].[PriceBuddy DB].server=literal:chill-penguin"
            "[Infrastructure].[PriceBuddy DB].container=literal:pricebuddy-db"

            "[Infrastructure].[BookStack DB].icon=literal:sh-mariadb"
            "[Infrastructure].[BookStack DB].description=literal:BookStack Database"
            "[Infrastructure].[BookStack DB].server=literal:chill-penguin"
            "[Infrastructure].[BookStack DB].container=literal:bookstack-db"

            "[Infrastructure].[RomM DB].icon=literal:sh-mariadb"
            "[Infrastructure].[RomM DB].description=literal:RomM Database"
            "[Infrastructure].[RomM DB].server=literal:chill-penguin"
            "[Infrastructure].[RomM DB].container=literal:romm-db"
            
            "[Infrastructure].[Grimmory DB].icon=literal:sh-mariadb"
            "[Infrastructure].[Grimmory DB].description=literal:Grimmory Database"
            "[Infrastructure].[Grimmory DB].server=literal:chill-penguin"
            "[Infrastructure].[Grimmory DB].container=literal:grimmory-db"

          )

          ${pkgs.ghostship-config}/bin/ghostship-config set "$SERVICES_FILE" "''${service_args[@]}"

          ${pkgs.yq-go}/bin/yq -i '
            (.[] | select(has("Services")) | .Services) |= map(select(has("Honcho") | not))
            | (.[] | select(has("Infrastructure")) | .Infrastructure) |= map(select((has("Honcho Redis") or has("Honcho DB")) | not))
            | (.[] | select(has("Infrastructure")) | .Infrastructure) |= (
                map(select(has("PriceBuddy Scraper") | not))
                + map(select(has("PriceBuddy Scraper")))
              )
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
