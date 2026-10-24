{ config, lib, pkgs, inputs, ... }:
let
  cfg = config.ghostship.privateIntegrations;
  system = pkgs.stdenv.hostPlatform.system;
  agent = inputs.ghostship-private-agent;
  tools = agent.packages.${system};
  # The platform owns the runtime and generated service clients; the deployment supplies its icon.
  runtimes = import ./agent-service-runtimes.nix {
    inherit agent;
    inherit system;
    mcpIcon = ./private-integrations/ghostship.png;
  };
  privateAddons = runtimes.private;
  baseImage = import ./service-base-image.nix {
    inherit pkgs; name = "ghostship-private-integrations"; uid = "62020";
    runtimeBins = [ "ghostship-mcp" ];
  };
  # The account the owner signs in as is supplied by the deployment outside
  # this repository; the template keeps only the placeholder name.
  renderOwnerConfig = pkgs.writeShellScriptBin "ghostship-render-owner-config" ''
    exec ${pkgs.python3}/bin/python3 ${./render-owner-config.py} "$@"
  '';
  brokerConfigTemplate = pkgs.writeText "ghostship-keep-broker.json" (builtins.toJSON {
    # Each account names the expected Google identity; the broker verifies the
    # signed-in account on the identity page and resolves its index at session
    # acquisition. No account index is configured or assumed.
    accounts = {
      User = { identity = "personal"; expected_email = "@GHOSTSHIP_KEEP_PERSONAL_EMAIL@"; };
      Agent = { identity = "agent"; expected_email = "@GHOSTSHIP_KEEP_AGENT_EMAIL@"; };
    };
    principal = "chatgpt-personal-owner";
    client = "${tools.google-pp-cli}/bin/google-pp-cli";
    # Public first-party Keep client identifier, matching ghostship-google-web.
    public_client_key = "AIzaSyDE7NHMUZfMoJVu-YNkK-7AXFSuL1Q9gKE"; # gitleaks:allow -- public first-party client identifier
    runtime_dir = "/run/ghostship-personal";
    database = "/var/lib/ghostship-keep/requests.sqlite";
    session_dir = "/var/lib/ghostship-keep/sessions";
    socket = "/run/ghostship-keep/operations.sock";
    model_uid = 62020;
  });
  # Generic service executor (ghostship_services): one dotenv file per
  # credential projection named in ghostship-agent's
  # tools/python/ghostship_services/inventory.py, read at call time from
  # /run/ghostship-secrets/<id>.env inside the container. The MCP server
  # scrubs its environment, so each file also carries the service's base URL
  # (the internal ghostship_net origin). Only executable inventory services
  # are listed, each with only the variables the inventory declares; never
  # add cloudflare-management or other broad projections here.
  apps = config.ghostship.apps;
  serviceCredentials = {
    sonarr = { base = apps.sonarr.origin; secrets.SONARR_API_KEY = { unit = "sonarr"; key = "API_KEY"; }; };
    radarr = { base = apps.radarr.origin; secrets.RADARR_API_KEY = { unit = "radarr"; key = "API_KEY"; }; };
    prowlarr = { base = apps.prowlarr.origin; secrets.PROWLARR_API_KEY = { unit = "prowlarr"; key = "API_KEY"; }; };
    # Bazarr's client keeps /api in its base URL.
    bazarr = { base = apps.bazarr.origin + "/api"; secrets.BAZARR_API_KEY = { unit = "bazarr"; key = "API_KEY"; }; };
    chaptarr = { base = apps.chaptarr.origin; secrets.CHAPTARR_API_KEY = { unit = "chaptarr"; key = "API_KEY"; }; };
    pyload = { base = apps.pyload.origin; secrets.PYLOAD_API_KEY = { unit = "pyload"; key = "API_KEY"; }; };
    # plex-pp-cli sends PLEX_USER_TOKEN as X-Plex-Token; it is the same token
    # Plex Auto Languages uses (plex unit API_KEY).
    plex = { base = apps.plex.origin; secrets.PLEX_USER_TOKEN = { unit = "plex"; key = "API_KEY"; }; };
    tautulli = { base = apps.tautulli.origin; secrets.TAUTULLI_API_KEY = { unit = "tautulli"; key = "API_KEY"; }; };
    # grimmory-pp-cli logs in with these and keeps the JWT in memory; the
    # database credentials stay out.
    grimmory = {
      base = apps.grimmory.origin;
      secrets = {
        GRIMMORY_USERNAME = { unit = "grimmory"; key = "USER"; };
        GRIMMORY_PASSWORD = { unit = "grimmory"; key = "PASS"; };
      };
    };
    # The control server role grants this key its status routes; settings reads
    # (VPN credentials) are gated by the executor.
    gluetun = { base = "http://gluetun:8000"; secrets.GLUETUN_API_KEY = { unit = "gluetun"; key = "HTTP_CONTROL_SERVER_API_KEY"; }; };
    # Tdarr runs without authentication on ghostship_net.
    tdarr = { base = apps.tdarr.origin; secrets = { }; };
    romm = {
      base = apps.romm.origin;
      secrets = {
        ROMM_USERNAME = { unit = "romm"; key = "USER"; };
        ROMM_PASSWORD = { unit = "romm"; key = "PASS"; };
      };
    };
    # qBittorrent trusts ghostship_net (AuthSubnetWhitelist); NZBGet's control
    # password is empty; the ntfy adapter reads only the public health route.
    qbittorrent = { base = apps.qbittorrent.origin; secrets = { }; };
    nzbget = { base = apps.nzbget.origin; secrets = { }; };
    ntfy = { base = apps.ntfy.origin; secrets = { }; };
    # Public cloud API (the health tool's ring data); the token is the owner's personal token.
    ultrahuman = { base = "https://partner.ultrahuman.com"; secrets.ULTRAHUMAN_API_TOKEN = { unit = "ultrahuman"; key = "API_TOKEN"; }; };
    # Wyze scale weigh-ins (health tool) through wyze-sdk: account login plus developer API key.
    wyze = {
      base = "https://api.wyzecam.com";
      secrets = {
        WYZE_EMAIL = { unit = "wyze"; key = "EMAIL"; };
        WYZE_PASSWORD = { unit = "wyze"; key = "PASSWORD"; };
        WYZE_KEY_ID = { unit = "wyze"; key = "KEY_ID"; };
        WYZE_API_KEY = { unit = "wyze"; key = "API_KEY"; };
      };
    };
  };
  serviceProjection = id: "ghostship-service-${id}";
  serviceSecretsDir = "/run/ghostship-secrets/ghostship-services";
  serviceProjections = lib.mapAttrs' (
    id: svc:
    lib.nameValuePair (serviceProjection id) {
      fileName = "ghostship-services/${id}.env";
      owner = "root";
      group = "ghostship-mcp";
      mode = "0440";
      # The inventory's dotenv reader does not unquote shell syntax.
      raw = true;
      fields = svc.secrets // { "${lib.toUpper id}_BASE_URL".value = svc.base; };
    }
  ) serviceCredentials;

  # Post-deploy skills reconciliation (docs/skills-distribution.md in
  # ghostship-agent). The app pins the deployed flake source and revision.
  skillsCli = agent.apps.${system}.ghostship-skills.program;
  waitForMcpHealthy = pkgs.writeShellScript "ghostship-wait-mcp-healthy" ''
    set -eu
    for _ in $(seq 1 60); do
      state=$(${pkgs.podman}/bin/podman inspect --format '{{.State.Health.Status}}' \
        ghostship-private-integrations 2>/dev/null || true)
      [ "$state" = healthy ] && exit 0
      sleep 5
    done
    echo "ghostship-private-integrations did not become healthy" >&2
    exit 1
  '';

  # Seerr generates its API key into its own settings; project it (with the
  # internal base URL) the same way as the agenix-backed service credentials.
  renderSeerr = pkgs.writeText "ghostship-render-seerr.py" ''
    import json, os, sys
    target = sys.argv[1]
    try:
        key = json.load(open("/srv/apps/seerr/settings.json"))["main"]["apiKey"]
    except (OSError, KeyError, ValueError):
        sys.exit(0)  # Seerr not initialized yet; the service stays unconfigured
    tmp = target + ".new"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o440)
    with os.fdopen(fd, "w") as handle:
        handle.write("SEERR_API_KEY=" + key + "\nSEERR_BASE_URL=${apps.seerr.origin}\n")
    os.chown(tmp, 0, 62020)
    os.chmod(tmp, 0o440)  # the render unit's umask drops group read from os.open
    os.replace(tmp, target)
  '';

  # Host operations broker: allowlisted host operations for the MCP container
  # (container lifecycle, MariaDB reads, restic, Recyclarr, Uptime Kuma,
  # read-only Cloudflare, ntfy publish). Host credentials stay on the host.
  hostopsConfigTemplate = pkgs.writeText "ghostship-hostops.json" (builtins.toJSON {
    socket = "/run/ghostship-hostops/ops.sock";
    client_uid = 62020;
    socket_gid = 62020;
    containers = lib.mapAttrs (name: _: {
      restart = !(builtins.elem name [ "t3code" "ghostship-private-integrations" ]);
    }) config.virtualisation.oci-containers.containers;
    databases = {
      romm-db = { container = "romm-db"; password_env = "MYSQL_ROOT_PASSWORD"; };
      grimmory-db = { container = "grimmory-db"; password_env = "MYSQL_ROOT_PASSWORD"; };
    };
    filesystem = {
      nas_mount = "/mnt/share";
      roots = [
        "/mnt/share/Downloads"
        "/mnt/share/Library/TV"
        "/mnt/share/Library/Movies"
        "/mnt/share/Library/Books"
      ];
      access_users = lib.genAttrs [ "sonarr" "radarr" "plex" ] (
        name: config.virtualisation.oci-containers.containers.${name}.user
      ) // {
        grimmory = with config.virtualisation.oci-containers.containers.grimmory.environment;
          "${USER_ID}:${GROUP_ID}";
      };
    };
    ebook_conversion.report = "/var/lib/ghostship-ebook-convert/report.json";
    recyclarr.container = "recyclarr";
    # Config files of services without an API that the MCP may read and replace
    # (atomic, with a timestamped copy). Startup patches only registry-owned
    # entries, so other edits persist.
    config_files = {
      homepage = {
        dir = "/srv/apps/homepage";
        container = "homepage";
        files = [ "services.yaml" "settings.yaml" "bookmarks.yaml" "widgets.yaml" "docker.yaml" "custom.css" "custom.js" ];
      };
      muximux = { dir = "/srv/apps/muximux/www/muximux"; container = "muximux"; files = [ "settings.ini.php" ]; };
      plex-auto-languages = { dir = "/srv/apps/plex-auto-languages"; container = "plex-auto-languages"; files = [ "config.yaml" ]; };
      recyclarr = { dir = "/srv/apps/recyclarr"; container = "recyclarr"; files = [ "recyclarr.yml" "settings.yml" ]; };
    };
    host.mounts = [ "/" "/srv" "/nix" "/mnt/share" ];
    backup = {
      env_file = config.ghostship.selfHostedSecrets.projections.backup.path;
      repository = "/mnt/share/Backups/ghostship/chill-penguin";
      cache_dir = "/var/cache/ghostship-backup";
      host = "chill-penguin";
      jobs = [ "backup" "check" "sample" "prune" ];
      restore_root = "/var/lib/ghostship-backup/restore";
    };
    kuma = {
      container = "uptime-kuma";
      port = 3001;
      # The administrator account name is supplied by the deployment outside
      # this repository.
      username = "@GHOSTSHIP_KUMA_USERNAME@";
      env_file = config.ghostship.selfHostedSecrets.projections.monitoring.path;
    };
    cloudflare.env_file = config.ghostship.selfHostedSecrets.projections.cloudflare-management.path;
    ntfy = {
      container = "ntfy";
      port = 8080;
      username = "publisher";
      env_file = config.ghostship.selfHostedSecrets.projections.monitoring.path;
      topics = [ "security" "operations" "informational" ];
      default_topic = "operations";
    };
  });

  render = pkgs.writeShellScript "ghostship-private-relay-render" ''
    set -eu
    ${config.ghostship.selfHostedSecrets.renderFor "ghostship-relay"}/bin/ghostship-secret-project ghostship-relay
    ${lib.concatMapStringsSep "\n" (name:
      "${config.ghostship.selfHostedSecrets.renderFor name}/bin/ghostship-secret-project ${lib.escapeShellArg name}"
    ) (builtins.attrNames serviceProjections)}
    ${pkgs.python3}/bin/python3 ${renderSeerr} ${serviceSecretsDir}/seerr.env
    exec ${pkgs.python3}/bin/python3 ${./private-relay-render.py} \
      ${config.ghostship.selfHostedSecrets.projections.ghostship-relay.path} \
      ${privateAddons.runtime}/bin/ghostship-mcp
  '';
in {
  options.ghostship.privateIntegrations.enable = lib.mkEnableOption "private Ghostship Keep and Amazon MCP gateway";
  options.ghostship.privateIntegrations.skillsReconcile.enable = lib.mkEnableOption ''
    unattended ChatGPT skills publication after each ghostship-agent deploy
    (package, publish-chatgpt, verify-chatgpt on the Assistant/personal
    identity through the Agent Desktop). Off until the user approves
    unattended publication from the host'';
  config = lib.mkIf cfg.enable (lib.mkMerge [ {
    ghostship.apps.ghostship = {
      name = "Ghostship";
      container = "ghostship-private-integrations";
      description = "Private Keep and Amazon tools with configured account/profile routing";
      hostname = null;
      origin = null;
    };
    users.groups.ghostship-mcp.gid = 62020;
    users.groups.ghostship-personal.gid = 62021;
    users.users.ghostship-mcp = { isSystemUser = true; uid = 62020; group = "ghostship-mcp"; };
    users.users.ghostship-personal = {
      isSystemUser = true; uid = 62021; group = "ghostship-personal";
      extraGroups = [ "ghostship-mcp" ];
    };
    ghostship.secretProjections = serviceProjections;
    systemd.tmpfiles.rules = [
      "d ${serviceSecretsDir} 0750 root ghostship-mcp -"
      "d /run/ghostship-keep 0750 ghostship-personal ghostship-mcp -"
      "d /run/ghostship-integrations 0750 root ghostship-mcp -"
      "d /srv/apps/ghostship-private-integrations 0700 ghostship-mcp ghostship-mcp -"
      "d /srv/apps/ghostship-private-integrations/ghostship 0700 ghostship-mcp ghostship-mcp -"
    ];
    # Root because the operations drive podman, systemctl and restic; every
    # operation is a fixed argv from the allowlist in the agent's
    # ghostship_hostops.ops, and only uid 62020 (the MCP container) may connect.
    systemd.services.ghostship-hostops-broker = {
      description = "Allowlisted host operations for the Ghostship MCP container";
      wantedBy = [ "multi-user.target" ];
      after = [ "podman.socket" "network-online.target" ];
      wants = [ "network-online.target" ];
      path = [ pkgs.podman pkgs.systemd pkgs.restic pkgs.coreutils ];
      environment.SSL_CERT_FILE = "/etc/ssl/certs/ca-certificates.crt";
      serviceConfig = {
        ExecStartPre = "${renderOwnerConfig}/bin/ghostship-render-owner-config ${hostopsConfigTemplate} /run/ghostship-hostops/hostops.json";
        ExecStart = "${tools.hostops-broker}/bin/ghostship-hostops-broker --config /run/ghostship-hostops/hostops.json";
        RuntimeDirectory = "ghostship-hostops";
        RuntimeDirectoryMode = "0750";
        # The MCP container bind-mounts this directory. Removing it on stop left
        # the container on the deleted directory, so host operations failed as
        # "not reachable" after every broker restart until the container restarted.
        RuntimeDirectoryPreserve = "yes";
        Group = "ghostship-mcp";
        UMask = "0007";
        Restart = "on-failure";
        RestartSec = 3;
        NoNewPrivileges = true;
        PrivateTmp = true;
        # The owner identity values are supplied by the deployment outside this
        # repository.
        EnvironmentFile = [ "/etc/ghostship/owner-identity.env" ];
      };
    };
    systemd.services.ghostship-keep-broker = {
      description = "Keep API execution service with Agent Desktop authentication";
      # Keep SSH available independently of the pinned agent package revision.
      path = [ pkgs.openssh pkgs.coreutils ];
      wantedBy = [ "multi-user.target" ];
      after = [ "ghostship-desktop-bridge.service" ];
      requires = [ "ghostship-desktop-bridge.service" ];
      serviceConfig = {
        User = "ghostship-personal";
        Group = "ghostship-mcp";
        StateDirectory = "ghostship-keep";
        StateDirectoryMode = "0700";
        RuntimeDirectory = "ghostship-personal";
        RuntimeDirectoryMode = "0700";
        UMask = "0077";
        # The broker is host-side, not in the MCP container: supply the same
        # mounted desktop SSH key/host contract explicitly. No manager or
        # secondary browser is needed for authenticated Keep operations.
        Environment = [
          "SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt"
          "GHOSTSHIP_BROWSER_DRIVER=desktop"
          "AGENT_DESKTOP_SSH_HOST=10.89.7.2"
          "AGENT_DESKTOP_SSH_PORT=2222"
          "AGENT_DESKTOP_SSH_USER=abc"
          "AGENT_DESKTOP_SSH_KEY=/run/ghostship-integrations/agent-desktop-key"
          "AGENT_DESKTOP_SSH_KNOWN_HOSTS=/run/ghostship-integrations/agent-desktop-known-hosts"
        ];
        ExecStartPre = "${renderOwnerConfig}/bin/ghostship-render-owner-config ${brokerConfigTemplate} /run/ghostship-personal/keep-broker.json";
        ExecStart = "${tools.keep-broker}/bin/ghostship-keep-broker --config /run/ghostship-personal/keep-broker.json";
        Restart = "on-failure";
        RestartSec = 3;
        NoNewPrivileges = true;
        ProtectSystem = "strict";
        ProtectHome = true;
        PrivateTmp = true;
        ReadWritePaths = [
          "/run/ghostship-keep"
          "/run/ghostship-personal"
        ];
        RestrictAddressFamilies = [ "AF_UNIX" "AF_INET" "AF_INET6" ];
        CapabilityBoundingSet = "";
        # The owner identity values are supplied by the deployment outside this
        # repository.
        EnvironmentFile = [ "/etc/ghostship/owner-identity.env" ];
      };
    };
    systemd.services.ghostship-private-relay-config = {
      description = "Render scoped private MCP relay credentials";
      before = [ "podman-ghostship-private-integrations.service" ];
      requiredBy = [ "podman-ghostship-private-integrations.service" ];
      serviceConfig = { Type = "oneshot"; ExecStart = render; UMask = "0077"; };
    };
    # T3 bridge: the isolated ChatGPT MCP reads /run/ghostship-integrations/
    # {t3-server.json,t3-token} and can then call the t3_* capabilities. T3 Code
    # runs inside the `t3code` container on ghostship_net, reachable by name
    # through its access proxy at t3code:3773; this one unit publishes the URL
    # and a scoped session token. Update = bump the agent flake pin only.
    #
    # Agent Desktop bridge: the same isolated MCP runs the parallel Bladebro
    # worker transport, so it needs the desktop SSH contract. This unit
    # publishes the t3code desktop key, its pinned host key, and the desktop
    # address into /run/ghostship-integrations; the MCP wrapper reads them by
    # file. The address is the agent_desktop_net IP because the desktop's
    # pinned known_hosts entry is `[10.89.7.2]:2222`; the desktop also answers
    # on ghostship_net (10.89.0.213) but the host key entry would not match.
    systemd.services.ghostship-desktop-bridge = {
      description = "Publish the Agent Desktop SSH contract for the ChatGPT MCP";
      wantedBy = [ "multi-user.target" ];
      after = [ "agent-desktop-ssh.service" "agent-desktop-mcp.service" ];
      requires = [ "agent-desktop-ssh.service" "agent-desktop-mcp.service" ];
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
        ExecStart = pkgs.writeShellScript "ghostship-desktop-bridge" ''
          set -eu
          umask 077
          install -d -m 0750 -o root -g ghostship-mcp /run/ghostship-integrations
          install -m 0440 -o root -g ghostship-mcp \
            /srv/apps/t3code/home/.ssh/known_hosts_agent_desktop \
            /run/ghostship-integrations/agent-desktop-known-hosts.new
          install -m 0440 -o root -g ghostship-mcp \
            /srv/apps/t3code/home/.ssh/id_agent_desktop \
            /run/ghostship-integrations/agent-desktop-key.new
          printf '10.89.7.2' > /run/ghostship-integrations/agent-desktop-host.new
          chmod 0444 /run/ghostship-integrations/agent-desktop-host.new
          mv /run/ghostship-integrations/agent-desktop-known-hosts.new \
             /run/ghostship-integrations/agent-desktop-known-hosts
          mv /run/ghostship-integrations/agent-desktop-key.new \
             /run/ghostship-integrations/agent-desktop-key
          mv /run/ghostship-integrations/agent-desktop-host.new \
             /run/ghostship-integrations/agent-desktop-host
        '';
        UMask = "0077";
      };
    };
    systemd.timers.ghostship-desktop-bridge = {
      wantedBy = [ "timers.target" ];
      timerConfig = {
        OnBootSec = "20min";
        OnUnitActiveSec = "1d";
        Persistent = true;
        RandomizedDelaySec = 300;
      };
    };
    systemd.services.ghostship-t3-bridge = {
      description = "Publish the T3 bridge endpoint and session token for the ChatGPT MCP";
      wantedBy = [ "multi-user.target" ];
      after = [ "podman-t3code.service" ];
      serviceConfig = {
        Type = "oneshot";
        ExecStart = pkgs.writeShellScript "ghostship-t3-bridge" ''
          set -eu
          umask 077
          printf 'http://t3code:3773' > /run/ghostship-integrations/t3-server.json.new
          chmod 0444 /run/ghostship-integrations/t3-server.json.new
          mv /run/ghostship-integrations/t3-server.json.new /run/ghostship-integrations/t3-server.json
          for attempt in $(seq 1 30); do
            if token=$(${pkgs.podman}/bin/podman exec t3code \
                env HOME=/home/t3code T3CODE_HOME=/home/t3code/.t3 \
                /home/t3code/.local/bin/t3 auth session issue \
                --ttl 30d --label ghostship-chatgpt-mcp --token-only 2>/dev/null) \
                && [ -n "$token" ]; then
              printf '%s' "$token" > /run/ghostship-integrations/t3-token.new
              chown 62020:62020 /run/ghostship-integrations/t3-token.new
              chmod 0400 /run/ghostship-integrations/t3-token.new
              mv /run/ghostship-integrations/t3-token.new /run/ghostship-integrations/t3-token
              exit 0
            fi
            sleep 10
          done
          echo "could not issue a T3 session token from the t3code container" >&2
          exit 1
        '';
        UMask = "0077";
      };
    };
    systemd.timers.ghostship-t3-bridge = {
      wantedBy = [ "timers.target" ];
      timerConfig = {
        OnBootSec = "10min";
        OnCalendar = "daily";
        Persistent = true;
        RandomizedDelaySec = 600;
      };
    };
    # Host CLI picker runs as root or a service account; the explicit path keeps
    # it on the T3 home store instead of guessing HOME (#403).
    environment.variables.GHOSTSHIP_MODEL_EVIDENCE_PATH =
      "/srv/apps/t3code/home/.local/state/ghostship/model-evidence.jsonl";
    # The evidence file is 0600 for the T3 home owner. Grant the integrations
    # uid (62020) read on the directory and on future files via a default ACL,
    # the same pattern the coordinator review store uses.
    systemd.services.podman-ghostship-private-integrations.preStart = lib.mkBefore ''
      evidence=/srv/apps/t3code/home/.local/state/ghostship
      if [ -d "$evidence" ]; then
        ${pkgs.acl}/bin/setfacl -m u:62020:rx "$evidence"
        ${pkgs.acl}/bin/setfacl -m d:u:62020:rX "$evidence"
        if [ -f "$evidence/model-evidence.jsonl" ]; then
          ${pkgs.acl}/bin/setfacl -m u:62020:r "$evidence/model-evidence.jsonl"
        fi
      fi
    '';
    ghostship.containerRuntimes.ghostship-private-integrations.runtime = runtimes.integrations;
    virtualisation.oci-containers.containers.ghostship-private-integrations = {
      image = "ghostship-private-integrations:${baseImage.imageTag}";
      imageFile = baseImage;
      pull = "never";
      user = "62020:62020";
      environment = {
        GHOSTSHIP_MCP_IMAGE_VERSION = "ghostship-private-integrations:${baseImage.imageTag}";
        # The MCP picker must read the same model-probe evidence the T3 home
        # writes; HOME here is scrubbed, so name the store explicitly (#403).
        GHOSTSHIP_MODEL_EVIDENCE_PATH = "/run/ghostship-model-evidence/model-evidence.jsonl";
      };
      # The MCP runtime's account settings come from a root-owned file outside the
      # repository: GHOSTSHIP_GOOGLE_OWNER_ACCOUNT, GHOSTSHIP_GOOGLE_AGENT_ACCOUNT
      # and GHOSTSHIP_HEALTH_DOCUMENT_FOLDERS (the only Drive folders, and their
      # subfolders, the health op reads, so other people's records in a shared
      # folder stay out). A missing setting fails closed in the tool that needs it.
      environmentFiles = [ "/etc/ghostship/mcp-identity.env" ];
      volumes = [
        "/run/ghostship-integrations:/run/ghostship-integrations:ro"
        # Read-only view of the one model-evidence store; the pre-start grants
        # this runtime's uid read through an ACL (#403).
        "/srv/apps/t3code/home/.local/state/ghostship:/run/ghostship-model-evidence:ro"
        "/run/ghostship-keep:/run/ghostship-keep:ro"
        "/run/ghostship-hostops:/run/ghostship-hostops:ro"
        # Service executor credentials: the runtime's default directory.
        "${serviceSecretsDir}:/run/ghostship-secrets:ro"
        "/srv/apps/ghostship-private-integrations:/state:rw,noexec,nosuid,nodev"
      ];
      extraOptions = [
        "--read-only" "--cap-drop=ALL" "--security-opt=no-new-privileges"
        # Both networks are required: ghostship_net reaches T3 and
        # agent_desktop_net reaches the Agent Desktop SSH endpoint, which
        # starts on-demand Chrome with chrome-ensure.
        "--network=ghostship_net"
        "--network=agent_desktop_net"
        "--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777"
        # Each agent window drives parallel tabs through a pool of up to 8
        # Bladebro workers per identity (an SSH client plus reader threads
        # each); the pids limit counts threads.
        "--pids-limit=512" "--memory=4g" "--cpus=2"
        # The shared supervisor drains workers for up to 100s, then reaps
        # descendants for 2s. Podman's default 10s kills it during shutdown.
        "--stop-timeout=110"
        "--health-cmd=test -f /tmp/supervisor-live && test $(( $(date +%s) - $(stat -c %Y /tmp/supervisor-live) )) -lt 10"
        "--health-interval=30s" "--health-timeout=5s" "--health-retries=3"
      ];
    };
    systemd.services.podman-ghostship-private-integrations = {
      after = [ "ghostship-keep-broker.service" "ghostship-desktop-bridge.service"
                "ghostship-hostops-broker.service"
                "init-ghostship-net.service" "init-agent-desktop-net.service" ];
      requires = [ "ghostship-keep-broker.service" "ghostship-desktop-bridge.service"
                   "init-ghostship-net.service" "init-agent-desktop-net.service" ];
      wants = [ "ghostship-hostops-broker.service" ];
      # One stdio relay per ID: systemd/Podman stop the old instance first.
      restartIfChanged = true;
      # Include Podman's drain window plus container cleanup overhead.
      serviceConfig.TimeoutStopSec = lib.mkForce 130;
    };
  }
  (lib.mkIf cfg.skillsReconcile.enable {
    assertions = [ {
      assertion = (agent.apps.${system} or { }) ? ghostship-skills;
      message = "skillsReconcile needs a ghostship-agent pin that provides apps.ghostship-skills.";
    } ];
    # Runs once per deployed ghostship-agent revision (restart trigger), after
    # the MCP container is healthy. Needs: the Agent Desktop SSH contract
    # published by ghostship-desktop-bridge (key, known_hosts, 10.89.7.2:2222),
    # a signed-in ChatGPT session on the `personal` (Assistant) identity, and
    # the plugin id committed in config/skills/chatgpt-plugin.json.
    systemd.services.ghostship-skills-reconcile = {
      description = "Package, publish and verify Ghostship skills on ChatGPT after deploy";
      wantedBy = [ "multi-user.target" ];
      wants = [ "network-online.target" ];
      after = [ "network-online.target" "podman-ghostship-private-integrations.service"
                "ghostship-desktop-bridge.service" ];
      requires = [ "podman-ghostship-private-integrations.service" "ghostship-desktop-bridge.service" ];
      restartTriggers = [ agent.outPath ];
      path = [ pkgs.openssh pkgs.coreutils pkgs.git ];
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
        User = "ghostship-mcp";
        Group = "ghostship-mcp";
        StateDirectory = "ghostship-skills";
        StateDirectoryMode = "0700";
        UMask = "0077";
        Environment = [
          "HOME=/var/lib/ghostship-skills"
          "XDG_STATE_HOME=/var/lib/ghostship-skills"
          "SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt"
          "GHOSTSHIP_BROWSER_DRIVER=desktop"
          "AGENT_DESKTOP_SSH_HOST=10.89.7.2"
          "AGENT_DESKTOP_SSH_PORT=2222"
          "AGENT_DESKTOP_SSH_USER=abc"
          "AGENT_DESKTOP_SSH_KEY=/run/ghostship-integrations/agent-desktop-key"
          "AGENT_DESKTOP_SSH_KNOWN_HOSTS=/run/ghostship-integrations/agent-desktop-known-hosts"
        ];
        # podman inspect needs root; the publication itself does not.
        ExecStartPre = "+${waitForMcpHealthy}";
        ExecStart = [
          "${skillsCli} package"
          "${skillsCli} publish-chatgpt"
          "${skillsCli} verify-chatgpt"
        ];
        TimeoutStartSec = "30min";
        NoNewPrivileges = true;
        ProtectSystem = "strict";
        ProtectHome = true;
        PrivateTmp = true;
      };
    };
  })
  ]);
}
