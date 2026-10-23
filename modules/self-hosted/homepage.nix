{
  config,
  lib,
  pkgs,
  ...
}:

let
  homepage-secrets = config.ghostship.selfHostedSecrets.projections.homepage.path;
  render-homepage-secrets = "${config.ghostship.selfHostedSecrets.renderFor "homepage"}/bin/ghostship-secret-project homepage";
  brokerConfig = pkgs.writeText "homepage-podman-broker.conf" (
    builtins.readFile ./homepage-podman-broker.conf
  );
in

{
  ghostship.apps.homepage = {
    name = "Homepage";
    group = "Management";
    description = "Dashboard";
    icon = "sh-homepage";
    order = 10;
    hostname = "homepage.ghostship.io";
    origin = "http://homepage:3000";
    muximux = {
      icon = "muximux-home2";
      color = "#109f61";
      dropdown = false;
      label = "";
    };
  };

  virtualisation.oci-containers.containers."homepage" = {
    podman.sdnotify = "healthy";
    image = "ghcr.io/gethomepage/homepage:latest";
    pull = "always";
    labels = {
      "io.containers.autoupdate" = "registry";
    };
    user = "3000:3000";
    extraOptions = [
      "--network=ghostship_net"
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
      "/srv/apps/homepage:/app/config:rw,noexec,nosuid,nodev"
      "/run/homepage-podman-broker:/run/homepage-podman-broker:ro"
      "/sys/class/net:/sys/class/net:ro"
      "/sys/devices/platform:/sys/devices/platform:ro"
    ];
    environmentFiles = [ config.ghostship.selfHostedSecrets.projections.homepage.containerPath ];
  };

  systemd.services.homepage-podman-broker = {
    description = "Restricted read-only Podman API for Homepage";
    wantedBy = [ "multi-user.target" ];
    requires = [ "podman.socket" ];
    after = [ "podman.socket" ];
    before = [ "podman-homepage.service" ];
    serviceConfig = {
      ExecStart = "${pkgs.nginx}/bin/nginx -e stderr -p /run/homepage-podman-broker -c ${brokerConfig}";
      Restart = "on-failure";
      DynamicUser = true;
      User = "homepage-podman-broker";
      Group = "apps";
      SupplementaryGroups = [ "podman" ];
      RuntimeDirectory = "homepage-podman-broker";
      RuntimeDirectoryMode = "0750";
      UMask = "0007";
      NoNewPrivileges = true;
      ProtectSystem = "strict";
      ProtectHome = true;
      PrivateTmp = true;
      RestrictAddressFamilies = [ "AF_UNIX" ];
      CapabilityBoundingSet = "";
    };
  };
  systemd.services.podman-homepage = {
    requires = [ "homepage-podman-broker.service" ];
    after = [ "homepage-podman-broker.service" ];
  };

  systemd.tmpfiles.rules = [
    "d /srv/apps/homepage 0700 apps apps -"
    "d /srv/apps/homepage/logs 0755 apps apps -"
  ];

  systemd.services.podman-homepage.preStart = lib.mkAfter ''
    SETTINGS_FILE="/srv/apps/homepage/settings.yaml"
    SERVICES_FILE="/srv/apps/homepage/services.yaml"
    DOCKER_FILE="/srv/apps/homepage/docker.yaml"

    install -d -m0700 -o apps -g apps /srv/apps/homepage
    [ -f "$SERVICES_FILE" ] || printf '[]\n' > "$SERVICES_FILE"
    [ -f "$SETTINGS_FILE" ] || printf '{}\n' > "$SETTINGS_FILE"
    [ -f "$DOCKER_FILE" ] || printf '{}\n' > "$DOCKER_FILE"
    # Check if config directory exists
    if [ -d "/srv/apps/homepage" ]; then
      # Update settings.yaml if it exists
      if [ -f "$SETTINGS_FILE" ]; then
        echo "Surgically updating Homepage settings..."
        settings_args=(
          title=literal:""
          quicklaunch.hideInternetSearch=literal:true
        )
        ${pkgs.ghostship-config}/bin/ghostship-config set "$SETTINGS_FILE" "''${settings_args[@]}"
        fi
      # Update services.yaml if it exists
      if [ -f "$SERVICES_FILE" ]; then
        echo "Surgically updating Homepage services..."
        
        ${render-homepage-secrets}

        service_args=(
          "[Calendar].[Calendar].icon=literal:sh-fluidcalendar"
          "[Calendar].[Calendar].widget.type=literal:calendar"
          "[Calendar].[Calendar].widget.view=literal:agenda"
          "[Calendar].[Calendar].widget.timezone=literal:Pacific/Honolulu"
        )

        ${pkgs.ghostship-config}/bin/ghostship-config set "$SERVICES_FILE" "''${service_args[@]}"

        ${pkgs.yq-go}/bin/yq -i '
          (.[] | select(has("Services")) | .Services) |= map(select((has("Paseo") or has("OpenChamber") or has("Hermes") or has("Honcho") or has("Firecrawl") or has("Firecrawl Playwright") or has("PriceBuddy") or has("PriceBuddy Scraper") or has("Changedetection") or has("n8n") or has("SearXNG") or has("Windmill") or has("Hatchet") or has("Prefect")) | not))
          | (.[] | select(has("Downloads")) | .Downloads) |= map(select((has("VueTorrent")) | not))
          | (.[] | select(has("Management")) | .Management) |= map(select((has("T3 Code") or has("Codex") or has("Synara") or has("n8n") or has("Changedetection") or has("BookStack") or has("SearXNG") or has("Plex Auto Languages") or has("PriceBuddy Scraper")) | not))
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
        ${pkgs.yq-go}/bin/yq -i 'del(.[] | select(has("logo"))) | . += [{"logo": {"icon": "mdi-home"}}]' "$WIDGETS_FILE"
        ${pkgs.yq-go}/bin/yq -i 'del(.[1].search.suggestionUrl)' "$WIDGETS_FILE"
      fi

      # Update docker.yaml if it exists
      if [ -f "$DOCKER_FILE" ]; then
        echo "Surgically updating Homepage container config..."
        docker_args=(
          chill-penguin.socket=literal:/run/homepage-podman-broker/podman.sock
        )
        ${pkgs.ghostship-config}/bin/ghostship-config set "$DOCKER_FILE" "''${docker_args[@]}"
      fi

      chown -R apps:apps /srv/apps/homepage
      find /srv/apps/homepage -maxdepth 1 -name "*.yaml" -exec chmod 600 {} +
    else
      echo "Homepage config directory not found, skipping activation"
    fi
  '';
}
