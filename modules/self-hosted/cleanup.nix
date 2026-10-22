{
  config,
  lib,
  pkgs,
  ...
}:

let
  retiredArtifacts = [
    {
      name = "cloakbrowser";
      # Fully retired: the Agent Desktop carries its bookmarks; profiles and
      # extensions move to /srv/retired-apps.
      paths = [ "/srv/apps/cloakbrowser" ];
      units = [
        "podman-cloakbrowser"
        "cloakbrowser-extensions"
      ];
      timers = [ "cloakbrowser-extensions" ];
      containers = [ "cloakbrowser" ];
      imageRefs = [ "docker.io/cloakhq/cloakbrowser-manager:latest" ];
      imageRepositories = [ "docker.io/cloakhq/cloakbrowser-manager" ];
      homepageEntries = [ "CloakBrowser" ];
      muximuxSections = [ "CloakBrowser" ];
    }
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
      imageRefs = [ "ghcr.io/@GHOSTSHIP_GITHUB_ACCOUNT@/ghostship-agent-zero:latest" ];
      imageRepositories = [
        "docker.io/agent0ai/agent-zero"
        "ghcr.io/@GHOSTSHIP_GITHUB_ACCOUNT@/ghostship-agent-zero"
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
      imageRefs = [ "ghcr.io/@GHOSTSHIP_GITHUB_ACCOUNT@/ghostship-hermes:latest" ];
      imageRepositories = [
        "ghcr.io/@GHOSTSHIP_GITHUB_ACCOUNT@/ghostship-hermes"
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
        "ghcr.io/@GHOSTSHIP_GITHUB_ACCOUNT@/honcho"
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
      name = "vuetorrent";
      units = [
        "podman-vuetorrent"
        "vuetorrent-auto-resume"
      ];
      timers = [ "vuetorrent-auto-resume" ];
      containers = [ "vuetorrent" ];
      homepageEntries = [ "VueTorrent" ];
      muximuxSections = [ "VueTorrent" ];
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
      name = "hatchet";
      paths = [ "/srv/apps/hatchet" ];
      units = [
        "hatchet-setup"
        "podman-hatchet"
        "podman-hatchet-db"
        "podman-hatchet-engine"
      ];
      containers = [
        "hatchet"
        "hatchet-db"
        "hatchet-engine"
      ];
      imageRefs = [
        "ghcr.io/hatchet-dev/hatchet/hatchet-admin:latest"
        "ghcr.io/hatchet-dev/hatchet/hatchet-dashboard:latest"
        "ghcr.io/hatchet-dev/hatchet/hatchet-engine:latest"
        "ghcr.io/hatchet-dev/hatchet/hatchet-migrate:latest"
      ];
      imageRepositories = [
        "ghcr.io/hatchet-dev/hatchet/hatchet-admin"
        "ghcr.io/hatchet-dev/hatchet/hatchet-dashboard"
        "ghcr.io/hatchet-dev/hatchet/hatchet-engine"
        "ghcr.io/hatchet-dev/hatchet/hatchet-migrate"
      ];
      homepageEntries = [ "Hatchet" ];
      muximuxSections = [ "Hatchet" ];
    }
    {
      name = "windmill";
      paths = [ "/srv/apps/windmill" ];
      units = [
        "podman-windmill"
        "podman-windmill-db"
        "podman-windmill-worker"
      ];
      containers = [
        "windmill"
        "windmill-db"
        "windmill-worker"
      ];
      imageRepositories = [
        "localhost/ghostship-windmill"
      ];
      homepageEntries = [ "Windmill" ];
      muximuxSections = [ "Windmill" ];
    }
    {
      name = "prefect";
      paths = [ "/srv/apps/prefect" ];
      units = [
        "podman-prefect"
        "podman-prefect-db"
        "podman-prefect-redis"
        "podman-prefect-services"
        "podman-prefect-worker"
      ];
      containers = [
        "prefect"
        "prefect-db"
        "prefect-redis"
        "prefect-services"
        "prefect-worker"
      ];
      imageRefs = [
        "docker.io/library/postgres:16-alpine"
        "docker.io/library/redis:7-alpine"
      ];
      imageRepositories = [
        "docker.io/prefecthq/prefect"
      ];
      homepageEntries = [
        "Prefect"
        "Prefect DB"
        "Prefect Redis"
        "Prefect Services"
        "Prefect Worker"
      ];
      muximuxSections = [ "Prefect" ];
    }
    {
      name = "rss-bridge";
      paths = [ "/srv/apps/rss-bridge" ];
      units = [ "podman-rss-bridge" ];
      containers = [ "rss-bridge" ];
      imageRefs = [ "docker.io/rssbridge/rss-bridge:latest" ];
      imageRepositories = [ "docker.io/rssbridge/rss-bridge" ];
      homepageEntries = [ "RSS-Bridge" ];
      muximuxSections = [ "RSS-Bridge" ];
    }
    {
      name = "openchamber";
      paths = [ "/srv/apps/openchamber" ];
      units = [
        "podman-openchamber"
        "openchamber-deploy-when-idle"
      ];
      timers = [ "openchamber-deploy-when-idle" ];
      containers = [ "openchamber" ];
      imageRefs = [ "localhost/ghostship-openchamber:openchamber" ];
      imageRepositories = [
        "localhost/ghostship-openchamber"
        "ghcr.io/@GHOSTSHIP_GITHUB_ACCOUNT@/ghostship-openchamber"
      ];
      homepageEntries = [ "OpenChamber" ];
      muximuxSections = [ "OpenChamber" ];
    }
    {
      name = "synara";
      paths = [ "/srv/apps/synara" ];
      units = [ "podman-synara" ];
      containers = [ "synara" ];
      # Synara reused the shared T3 Code image; never remove that repository,
      # because the primary container still runs from it.
      imageRefs = [ ];
      imageRepositories = [ ];
      homepageEntries = [ "Synara" ];
      muximuxSections = [ "Synara" ];
    }
    {
      name = "chatgpt-workstation";
      paths = [
        "/srv/apps/chatgpt"
        "/srv/apps/codex"
      ];
      units = [ "podman-codex" ];
      containers = [ "codex" ];
      imageRefs = [ "localhost/ghostship-codex:codex-runtime" ];
      imageRepositories = [ "localhost/ghostship-codex" ];
      homepageEntries = [
        "Codex"
        "ChatGPT"
      ];
      muximuxSections = [ "Codex" ];
    }
    {
      name = "nzbget-edge-proxy";
      paths = [ ];
      units = [ "podman-nzbget-edge-proxy" ];
      containers = [ "nzbget-edge-proxy" ];
      imageRefs = [ ];
      imageRepositories = [ ];
      homepageEntries = [ "NZBGet Edge Proxy" ];
      muximuxSections = [ ];
    }
  ];

  eligibleArtifacts = lib.filter (
    artifact:
    !(lib.any (name: builtins.hasAttr name config.virtualisation.oci-containers.containers) (
      artifact.containers or [ ]
    ))
  ) retiredArtifacts;

  commands =
    field: artifact: command:
    lib.concatMapStringsSep "\n" command (artifact.${field} or [ ]);
in
lib.mkIf (config.networking.hostName == "chill-penguin") {
  # A full switch is authoritative: runtime drop-ins and unit links left by
  # targeted activations or session guards would otherwise keep shadowing the
  # generated units (a stale relay renderer once pinned a removed MCP runtime).
  system.activationScripts.clear-runtime-unit-overrides = {
    deps = [ "etc" ];
    text = ''
      PATH=${lib.makeBinPath [ pkgs.coreutils ]}:$PATH ${pkgs.bash}/bin/bash \
        ${./clear-runtime-unit-overrides.sh} /run/systemd/system /etc/systemd/system
    '';
  };

  # A system service starts after switch-to-configuration has stopped units
  # removed by the new generation. Activation scripts run too early and would
  # preserve those still-active retired containers until a second rebuild.
  systemd.services.chill-penguin-retired-artifact-cleanup = {
    description = "Quarantine retired self-hosted application artifacts";
    requires = [ "podman-t3code.service" ];
    after = [ "podman-t3code.service" ];
    wantedBy = [ "multi-user.target" ];
    serviceConfig.Type = "oneshot";
    script = ''
      # The retired images were published in the owner's container registry
      # account. The account name is supplied by the deployment in a file
      # outside this repository.
      owner_identity_file="/etc/ghostship/owner-identity.env"
      if [ -r "$owner_identity_file" ]; then
        set -a
        . "$owner_identity_file"
        set +a
      fi
      retirement_dir="/srv/retired-apps/$(${pkgs.coreutils}/bin/date -u +%Y%m%dT%H%M%SZ)"
      masks_removed=false

      # Preserve every missing OpenChamber repository before its source tree is
      # quarantined. Existing T3 projects remain authoritative and untouched.
      imported_openchamber=false
      if [ -d /srv/apps/openchamber/workspace ] && [ -d /srv/apps/t3code/workspace ]; then
        for source in /srv/apps/openchamber/workspace/*; do
          [ -d "$source" ] || continue
          if [ -L "$source" ] || ${pkgs.util-linux}/bin/mountpoint -q "$source"; then
            printf 'warning: refusing linked or mounted OpenChamber project %s\n' "$source" >&2
            continue
          fi
          name="$(${pkgs.coreutils}/bin/basename "$source")"
          destination="/srv/apps/t3code/workspace/$name"
          [ ! -e "$destination" ] || continue
          staging="$(${pkgs.coreutils}/bin/mktemp -d /srv/apps/t3code/workspace/.import.XXXXXX)"
          ${pkgs.coreutils}/bin/cp -a --reflink=auto "$source/." "$staging/"
          ${pkgs.coreutils}/bin/chown -R 3000:3000 "$staging"
          ${pkgs.coreutils}/bin/mv "$staging" "$destination"
          imported_openchamber=true
        done
      fi
      if [ "$imported_openchamber" = true ]; then
        t3_ready=false
        for _ in $(${pkgs.coreutils}/bin/seq 1 60); do
          if ${pkgs.podman}/bin/podman exec t3code \
            systemctl is-active --quiet t3code-server.service 2>/dev/null \
            && ${pkgs.podman}/bin/podman exec t3code \
              test -x /bin/t3code-project-bootstrap; then
            t3_ready=true
            break
          fi
          sleep 5
        done
        if [ "$t3_ready" != true ]; then
          printf 'error: T3 did not become ready for imported project registration\n' >&2
          exit 1
        fi
        ${pkgs.podman}/bin/podman exec --user 3000:3000 t3code \
          /bin/t3code-project-bootstrap
      fi

      # Masks that stopped a unit before its retirement outlive the unit.
      remove_runtime_mask() {
        mask="/run/systemd/system/$1"
        if [ -L "$mask" ] && [ "$(${pkgs.coreutils}/bin/readlink "$mask")" = /dev/null ]; then
          ${pkgs.coreutils}/bin/rm -f "$mask"
          masks_removed=true
        fi
      }

      cleanup_retired_path() {
        path="$1"
        [ -e "$path" ] || return 0
        # Never follow a link or move a mount out from under an application.
        if [ -L "$path" ] || ${pkgs.util-linux}/bin/mountpoint -q "$path"; then
          printf 'warning: refusing linked or mounted retirement path %s\n' "$path" >&2
          return 0
        fi
        case "$path" in
          /srv/apps/*)
            ${pkgs.coreutils}/bin/install -d -m0700 "$retirement_dir"
            ${pkgs.coreutils}/bin/mv -T --no-clobber -- "$path" "$retirement_dir/''${path##*/}"
            ;;
          *) printf 'warning: refusing retirement path %s\n' "$path" >&2 ;;
        esac
      }

      # The retired images were published in the owner's container registry
      # account. The account name is supplied by the deployment outside this
      # repository; an unset account is a deployment mistake, not a default.
      expand_owner_account() {
        case "$1" in
          *@GHOSTSHIP_GITHUB_ACCOUNT@*)
            if [ -z "''${GHOSTSHIP_GITHUB_ACCOUNT:-}" ]; then
              printf 'error: GHOSTSHIP_GITHUB_ACCOUNT is not set; the owner identity file must define it\n' >&2
              exit 1
            fi
            printf '%s' "$(printf '%s' "$1" | sed "s|@GHOSTSHIP_GITHUB_ACCOUNT@/$GHOSTSHIP_GITHUB_ACCOUNT|g")"
            ;;
          *) printf '%s' "$1" ;;
        esac
      }

      remove_image_ref() {
        image="$(expand_owner_account "$1")"

        if ${pkgs.podman}/bin/podman image exists "$image" >/dev/null 2>&1; then
          ${pkgs.podman}/bin/podman rmi "$image" >/dev/null 2>&1 || true
        fi
      }

      remove_image_repository() {
        repository="$(expand_owner_account "$1")"

        ${pkgs.podman}/bin/podman images --format '{{.Repository}}:{{.Tag}}' \
          | while IFS= read -r image; do
              case "$image" in
                "$repository":*)
                  ${pkgs.podman}/bin/podman rmi "$image" >/dev/null 2>&1 || true
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

      ${lib.concatMapStringsSep "\n" (artifact: ''
        protected=false
        ${commands "units" artifact (unit: ''
          state="$(${pkgs.systemd}/bin/systemctl show -p ActiveState --value ${lib.escapeShellArg "${unit}.service"} 2>/dev/null || true)"
          case "$state" in
            active|activating|reloading|deactivating) protected=true ;;
          esac
        '')}
        ${commands "containers" artifact (name: ''
          if [ "$(${pkgs.podman}/bin/podman inspect --format '{{.State.Running}}' ${lib.escapeShellArg name} 2>/dev/null || true)" = true ]; then
            protected=true
          fi
        '')}
        if [ "$protected" = true ]; then
          echo ${lib.escapeShellArg "warning: preserving active retired service ${artifact.name}"} >&2
        else
          ${commands "timers" artifact (timer: ''
            ${pkgs.systemd}/bin/systemctl stop ${lib.escapeShellArg "${timer}.timer"} >/dev/null 2>&1 || true
          '')}
          ${commands "containers" artifact (name: ''
            if ! ${pkgs.podman}/bin/podman rm ${lib.escapeShellArg name} >/dev/null 2>&1; then
              if ${pkgs.podman}/bin/podman container exists ${lib.escapeShellArg name}; then
                protected=true
              fi
            fi
          '')}
          if [ "$protected" = false ]; then
          ${commands "paths" artifact (path: "cleanup_retired_path ${lib.escapeShellArg path}")}
          ${commands "units" artifact (unit: "remove_runtime_mask ${lib.escapeShellArg "${unit}.service"}")}
          ${commands "timers" artifact (timer: "remove_runtime_mask ${lib.escapeShellArg "${timer}.timer"}")}
          ${commands "imageRefs" artifact (ref: "remove_image_ref ${lib.escapeShellArg ref}")}
          ${commands "imageRepositories" artifact (
            ref: "remove_image_repository ${lib.escapeShellArg ref}"
          )}
          ${commands "homepageEntries" artifact (entry: "prune_homepage_entry ${lib.escapeShellArg entry}")}
          ${commands "muximuxSections" artifact (
            section: "prune_muximux_section ${lib.escapeShellArg section}"
          )}
          else
            echo "warning: retirement cancelled because a container could not be removed" >&2
          fi
          # Named volumes and quarantine data require explicit operator removal.
        fi
      '') eligibleArtifacts}
      if [ "$masks_removed" = true ]; then
        ${pkgs.systemd}/bin/systemctl daemon-reload
      fi
    '';
  };
}
