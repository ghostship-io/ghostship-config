{
  config,
  lib,
  pkgs,
  ...
}:

let
  retiredArtifacts = [
    {
      name = "bookstack";
      paths = [
        "/srv/apps/bookstack"
        "/srv/apps/bookstack-db"
      ];
      units = [
        "podman-bookstack"
        "podman-bookstack-db"
      ];
      containers = [
        "bookstack"
        "bookstack-db"
      ];
      imageRefs = [ "lscr.io/linuxserver/bookstack:latest" ];
      imageRepositories = [ "lscr.io/linuxserver/bookstack" ];
      homepageEntries = [
        "BookStack"
        "BookStack DB"
      ];
      muximuxSections = [ "BookStack" ];
    }
    {
      name = "jdownloader";
      paths = [ "/srv/apps/jdownloader" ];
      units = [ "podman-jdownloader" ];
      containers = [ "jdownloader" ];
      imageRefs = [ "docker.io/jlesage/jdownloader-2:latest" ];
      imageRepositories = [ "docker.io/jlesage/jdownloader-2" ];
      homepageEntries = [ "JDownloader2" ];
      muximuxSections = [ "JDownloader2" ];
    }
    {
      name = "agent-zero";
      paths = [ "/srv/apps/agent-zero" ];
      units = [ "podman-agent-zero" ];
      containers = [ "agent-zero" ];
      volumes = [ "agent-zero-nix" ];
      imageRefs = [ "ghcr.io/ghostship-io/ghostship-agent-zero:latest" ];
      imageRepositories = [
        "docker.io/agent0ai/agent-zero"
        "ghcr.io/ghostship-io/ghostship-agent-zero"
        "localhost/ghostship-agent-zero"
      ];
      homepageEntries = [ "Agent Zero" ];
      muximuxSections = [ "Agent Zero" ];
    }
    {
      name = "hermes";
      paths = [ "/srv/apps/hermes" ];
      units = [
        "podman-hermes"
        "hermes-runtime-env-sync"
      ];
      containers = [ "hermes" ];
      imageRefs = [ "ghcr.io/ghostship-io/ghostship-hermes:latest" ];
      imageRepositories = [
        "ghcr.io/ghostship-io/ghostship-hermes"
        "localhost/ghostship-hermes"
        "localhost/ghostship-hermes-workstation"
      ];
      homepageEntries = [ "Hermes" ];
      muximuxSections = [ "Hermes" ];
    }
    {
      name = "firecrawl";
      paths = [ "/srv/apps/firecrawl" ];
      units = [
        "podman-firecrawl-api"
        "podman-firecrawl-playwright"
        "podman-firecrawl-postgres"
        "podman-firecrawl-rabbitmq"
        "podman-firecrawl-redis"
      ];
      containers = [
        "firecrawl-api"
        "firecrawl-playwright"
        "firecrawl-postgres"
        "firecrawl-rabbitmq"
        "firecrawl-redis"
      ];
      imageRefs = [ "ghcr.io/firecrawl/firecrawl:latest" ];
      imageRepositories = [
        "ghcr.io/firecrawl/firecrawl"
        "ghcr.io/firecrawl/nuq-postgres"
        "ghcr.io/firecrawl/playwright-service"
        "localhost/ghostship-firecrawl-playwright-cloakbrowser"
        "localhost/ghostship-firecrawl-nuq-postgres"
      ];
      homepageEntries = [
        "Firecrawl"
        "Firecrawl Playwright"
        "Firecrawl Postgres"
        "Firecrawl RabbitMQ"
        "Firecrawl Redis"
      ];
      muximuxSections = [ "Firecrawl" ];
    }
    {
      name = "honcho";
      paths = [ "/srv/apps/honcho" ];
      units = [
        "podman-honcho"
        "podman-honcho-db"
        "podman-honcho-redis"
      ];
      containers = [
        "honcho"
        "honcho-db"
        "honcho-redis"
      ];
      imageRefs = [ ];
      imageRepositories = [
        "localhost/ghostship-honcho"
        "localhost/honcho"
        "ghcr.io/ghostship-io/honcho"
      ];
      homepageEntries = [
        "Honcho"
        "Honcho DB"
        "Honcho Redis"
      ];
      muximuxSections = [ "Honcho" ];
    }
    {
      name = "litellm";
      paths = [ "/srv/apps/litellm" ];
      units = [
        "podman-litellm"
        "podman-litellm-db"
      ];
      containers = [
        "litellm"
        "litellm-db"
      ];
      imageRefs = [ ];
      imageRepositories = [
        "ghcr.io/berriai/litellm"
        "docker.io/berriai/litellm"
      ];
      homepageEntries = [
        "LiteLLM"
        "LiteLLM DB"
      ];
      muximuxSections = [ "LiteLLM" ];
    }
    {
      name = "bentopdf";
      paths = [ "/srv/apps/bentopdf" ];
      units = [ "podman-bentopdf" ];
      containers = [ "bentopdf" ];
      imageRefs = [ "docker.io/bentopdf/bentopdf:latest" ];
      imageRepositories = [ "docker.io/bentopdf/bentopdf" ];
      homepageEntries = [ "BentoPDF" ];
      muximuxSections = [ "BentoPDF" ];
    }
    {
      name = "convertx";
      paths = [ "/srv/apps/convertx" ];
      units = [ "podman-convertx" ];
      containers = [ "convertx" ];
      imageRefs = [ "ghcr.io/c4illin/convertx:latest" ];
      imageRepositories = [ "ghcr.io/c4illin/convertx" ];
      homepageEntries = [ "ConvertX" ];
      muximuxSections = [ "ConvertX" ];
    }
    {
      name = "it-tools";
      units = [ "podman-it-tools" ];
      containers = [ "it-tools" ];
      imageRefs = [ "docker.io/corentinth/it-tools:latest" ];
      imageRepositories = [ "docker.io/corentinth/it-tools" ];
      homepageEntries = [ "IT-Tools" ];
      muximuxSections = [ "IT Tools" ];
    }
    {
      name = "metube";
      units = [ "podman-metube" ];
      containers = [ "metube" ];
      imageRefs = [ "ghcr.io/alexta69/metube:latest" ];
      imageRepositories = [ "ghcr.io/alexta69/metube" ];
      homepageEntries = [ "MeTube" ];
      muximuxSections = [ "MeTube" ];
    }
    {
      name = "omnitools";
      units = [ "podman-omni-tools" ];
      containers = [ "omni-tools" ];
      imageRefs = [ "docker.io/iib0011/omni-tools:latest" ];
      imageRepositories = [ "docker.io/iib0011/omni-tools" ];
      homepageEntries = [ "OmniTools" ];
      muximuxSections = [ "OmniTools" ];
    }
    {
      name = "changedetection";
      paths = [ "/srv/apps/changedetection" ];
      units = [
        "podman-changedetection"
        "changedetection-local-image-refresh"
      ];
      timers = [ "changedetection-local-image-refresh" ];
      containers = [ "changedetection" ];
      imageRefs = [ ];
      imageRepositories = [
        "ghcr.io/dgtlmoon/changedetection.io"
        "localhost/ghostship-changedetection-cloakbrowser"
      ];
      homepageEntries = [ "Changedetection" ];
      muximuxSections = [ "Changedetection" ];
    }
    {
      name = "pricebuddy";
      paths = [
        "/srv/apps/pricebuddy"
        "/srv/apps/pricebuddy-db"
      ];
      units = [
        "podman-pricebuddy"
        "podman-pricebuddy-db"
        "podman-pricebuddy-scraper"
        "pricebuddy-scraper-local-image-refresh"
      ];
      timers = [ "pricebuddy-scraper-local-image-refresh" ];
      containers = [
        "pricebuddy"
        "pricebuddy-db"
        "pricebuddy-scraper"
      ];
      imageRefs = [
        "docker.io/jez500/pricebuddy:latest"
        "docker.io/library/mysql:8.2"
      ];
      imageRepositories = [
        "docker.io/jez500/pricebuddy"
        "localhost/ghostship-pricebuddy-scraper-cloakbrowser"
      ];
      homepageEntries = [
        "PriceBuddy"
        "PriceBuddy DB"
        "PriceBuddy Scraper"
      ];
      muximuxSections = [ "PriceBuddy" ];
    }
    {
      name = "n8n";
      paths = [ "/srv/apps/n8n" ];
      units = [ "podman-n8n" ];
      containers = [ "n8n" ];
      imageRefs = [ "docker.n8n.io/n8nio/n8n:latest" ];
      imageRepositories = [ "docker.n8n.io/n8nio/n8n" ];
      homepageEntries = [ "n8n" ];
      muximuxSections = [ "N8N" ];
    }
    {
      name = "searxng";
      paths = [
        "/srv/apps/searxng"
        "/srv/apps/searxng-cache"
        "/srv/apps/searxng-valkey"
      ];
      units = [
        "podman-searxng"
        "podman-searxng-valkey"
      ];
      containers = [
        "searxng"
        "searxng-valkey"
      ];
      imageRefs = [
        "docker.io/searxng/searxng:latest"
        "docker.io/valkey/valkey:latest"
      ];
      imageRepositories = [
        "docker.io/searxng/searxng"
        "docker.io/valkey/valkey"
      ];
      homepageEntries = [
        "SearXNG"
        "SearXNG Cache"
      ];
      muximuxSections = [ "SearXNG" ];
    }
    {
      name = "windmill-container-app";
      paths = [ "/srv/apps/windmill" ];
      units = [
        "podman-windmill-db"
        "podman-windmill-worker"
      ];
      containers = [
        "windmill-db"
        "windmill-worker"
      ];
      imageRefs = [
        "docker.io/library/postgres:16-alpine"
        "ghcr.io/windmill-labs/windmill:main"
      ];
      imageRepositories = [ "ghcr.io/windmill-labs/windmill" ];
    }
  ];

  renderCommands =
    field: command:
    lib.concatMapStringsSep "\n" (
      artifact: lib.concatMapStringsSep "\n" command (artifact.${field} or [ ])
    ) retiredArtifacts;

  homepageEntries = lib.unique (
    lib.concatMap (artifact: artifact.homepageEntries or [ ]) retiredArtifacts
  );
  muximuxSections = lib.unique (
    lib.concatMap (artifact: artifact.muximuxSections or [ ]) retiredArtifacts
  );
in
lib.mkIf (config.networking.hostName == "chill-penguin") {
  system.activationScripts.chill-penguin-retired-artifact-cleanup = {
    deps = [
      "homepage-config"
      "muximux-config"
    ];
    text = ''
      cleanup_retired_path() {
        path="$1"

        case "$path" in
          /srv/apps/*)
            ${pkgs.coreutils}/bin/rm -rf -- "$path"
            ;;
          *)
            printf 'warning: refusing retired artifact cleanup path outside /srv/apps: %s\n' "$path" >&2
            ;;
        esac
      }

      remove_image_ref() {
        image="$1"

        if ${pkgs.podman}/bin/podman image exists "$image" >/dev/null 2>&1; then
          ${pkgs.podman}/bin/podman rmi -f "$image" >/dev/null 2>&1 || true
        fi
      }

      remove_image_repository() {
        repository="$1"

        ${pkgs.podman}/bin/podman images --format '{{.Repository}}:{{.Tag}}' \
          | while IFS= read -r image; do
              case "$image" in
                "$repository":*)
                  ${pkgs.podman}/bin/podman rmi -f "$image" >/dev/null 2>&1 || true
                  ;;
              esac
            done
      }

      prune_homepage_entry() {
        entry="$1"
        services_file="/srv/apps/homepage/services.yaml"

        if [ -f "$services_file" ]; then
          export entry
          ${pkgs.yq-go}/bin/yq -i \
            '(.[] | .[]) |= map(select(has(strenv(entry)) | not))' \
            "$services_file"
        fi
      }

      prune_muximux_section() {
        section="$1"
        config_file="/srv/apps/muximux/www/muximux/settings.ini.php"

        if [ -f "$config_file" ]; then
          temp_file="$(${pkgs.coreutils}/bin/mktemp)"
          ${pkgs.gawk}/bin/awk -v retired_section="$section" '
            BEGIN { skip = 0 }
            /^\[/ {
              current = $0
              sub(/^\[/, "", current)
              sub(/\]$/, "", current)
              skip = current == retired_section
            }
            !skip { print }
          ' "$config_file" > "$temp_file"
          ${pkgs.coreutils}/bin/mv "$temp_file" "$config_file"
          ${pkgs.coreutils}/bin/chown apps:apps "$config_file" || true
        fi
      }

      ${renderCommands "units" (unit: ''
        if [ -d /run/systemd/system ]; then
          ${pkgs.systemd}/bin/systemctl stop ${lib.escapeShellArg "${unit}.service"} >/dev/null 2>&1 || true
        fi
      '')}

      ${renderCommands "timers" (timer: ''
        if [ -d /run/systemd/system ]; then
          ${pkgs.systemd}/bin/systemctl stop ${lib.escapeShellArg "${timer}.timer"} >/dev/null 2>&1 || true
        fi
      '')}

      ${renderCommands "containers" (container: ''
        ${pkgs.podman}/bin/podman rm -f ${lib.escapeShellArg container} >/dev/null 2>&1 || true
      '')}

      ${renderCommands "volumes" (volume: ''
        ${pkgs.podman}/bin/podman volume rm -f ${lib.escapeShellArg volume} >/dev/null 2>&1 || true
      '')}

      ${renderCommands "paths" (path: ''
        cleanup_retired_path ${lib.escapeShellArg path}
      '')}

      ${renderCommands "imageRefs" (image: ''
        remove_image_ref ${lib.escapeShellArg image}
      '')}

      ${renderCommands "imageRepositories" (repository: ''
        remove_image_repository ${lib.escapeShellArg repository}
      '')}

      ${lib.concatMapStringsSep "\n" (entry: ''
        entry=${lib.escapeShellArg entry} prune_homepage_entry ${lib.escapeShellArg entry}
      '') homepageEntries}

      ${lib.concatMapStringsSep "\n" (section: ''
        prune_muximux_section ${lib.escapeShellArg section}
      '') muximuxSections}
    '';
  };
}
