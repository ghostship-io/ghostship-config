{ config, lib, pkgs, inputs, ... }:
let
  cfg = config.ghostship.privateIntegrations;
  system = pkgs.stdenv.hostPlatform.system;
  agent = inputs.ghostship-private-agent;
  tools = agent.packages.${system};
  # The platform owns the runtime and generated service clients; the deployment supplies its icon.
  runtimes = import ./agent-service-runtimes.nix {
    nativeAgent = inputs.ghostship-native-agent;
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
  # The publisher drives the Agent Desktop through the Python desktop stack,
  # which needs its own login user; the rollout itself runs as root so it can
  # read the connector over podman. runuser changes only the uid for this
  # child, not the service or its grants.
  skillsOwner = pkgs.writeShellScript "ghostship-skills-owner" ''
    set -eu
    exec ${pkgs.util-linux}/bin/runuser -u ghostship-mcp -- \
      ${pkgs.coreutils}/bin/env \
        HOME=/var/lib/ghostship-skills XDG_STATE_HOME=/var/lib/ghostship-skills \
        SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt GHOSTSHIP_BROWSER_DRIVER=desktop \
        AGENT_DESKTOP_SSH_HOST=10.89.7.2 AGENT_DESKTOP_SSH_PORT=2222 AGENT_DESKTOP_SSH_USER=abc \
        AGENT_DESKTOP_SSH_KEY=/run/ghostship-integrations/agent-desktop-key \
        AGENT_DESKTOP_SSH_KNOWN_HOSTS=/run/ghostship-integrations/agent-desktop-known-hosts \
        ${skillsCli} "$@"
  '';
  # A failed attempt must not leave the prior success visible. The connector's
  # desktop probe runs once at startup; wait for the contract and give a failed
  # probe one container restart before the rollout reads the catalogue.
  activatePrepare = pkgs.writeShellScript "ghostship-activate-prepare" ''
    set -eu
    install -d -m 0700 -o ghostship-mcp -g ghostship-mcp /var/lib/ghostship-skills
    rm -f /var/lib/ghostship-skills/activate.json
    for _ in $(${pkgs.coreutils}/bin/seq 1 30); do
      ${pkgs.openssh}/bin/ssh -i /run/ghostship-integrations/agent-desktop-key -p 2222 \
        -o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=5 \
        -o UserKnownHostsFile=/run/ghostship-integrations/agent-desktop-known-hosts \
        -o StrictHostKeyChecking=yes abc@10.89.7.2 true >/dev/null 2>&1 && break
      sleep 2
    done
    if ! ${pkgs.podman}/bin/podman logs ghostship-private-integrations 2>&1 | ${pkgs.gnugrep}/bin/grep -q '"desktop.enabled"'; then
      ${pkgs.podman}/bin/podman restart ghostship-private-integrations >/dev/null
      for _ in $(${pkgs.coreutils}/bin/seq 1 60); do
        [ "$(${pkgs.podman}/bin/podman inspect --format '{{.State.Health.Status}}' ghostship-private-integrations 2>/dev/null || true)" = healthy ] && break
        sleep 5
      done
    fi
  '';
  # The rollout compares the consumer with the connector; these families are
  # the owner's required surface, so their absence is an explicit partial even
  # when app and connector agree.
  activateVerify = pkgs.writeShellScript "ghostship-activate-verify" ''
    exec ${pkgs.python3}/bin/python3 -c '
import json, sys
d = json.load(open("/var/lib/ghostship-skills/activate.json"))
tools = set((d.get("stages", {}).get("consumer") or {}).get("consumer_tools") or [])
missing = [n for n in ("desktop_see", "keep_list_notes") if n not in tools]
if not d.get("ok") or missing:
    print(json.dumps({"ok": False, "pending": d.get("pending"), "missing_required": missing}))
    sys.exit(3)
'
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
  # The connector container sees only /run/ghostship-native-mcp. Publish the
  # already scoped projections it needs into that directory, atomically and
  # owning only uid 62020. A missing source removes the target so revoked
  # access fails closed instead of leaving a stale credential.
  project = pkgs.writeShellScript "ghostship-mcp-projections" ''
    set -eu
    umask 077
    target=/run/ghostship-native-mcp
    install -d -m 0750 -o root -g ghostship-mcp "$target"
    for name in agent-desktop-key agent-desktop-known-hosts agent-desktop-host; do
      source=/run/ghostship-integrations/$name
      if [ -s "$source" ]; then
        install -m 0400 -o 62020 -g 62020 "$source" "$target/$name.new"
        mv "$target/$name.new" "$target/$name"
      else
        rm -f "$target/$name"
      fi
    done
    for pair in \
      "github:/srv/apps/t3code/home/.local/state/ghostship-controller/state/github.token" \
      "workspace:/var/lib/ghostship-workspace/write-token"; do
      name=''${pair%%:*}
      source=''${pair#*:}
      if [ -s "$source" ]; then
        install -m 0400 -o 62020 -g 62020 "$source" "$target/$name-token.new"
        mv "$target/$name-token.new" "$target/$name-token"
      else
        rm -f "$target/$name-token"
      fi
    done
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
      "d /srv/apps/ghostship-private-integrations/native-auth 0700 62020 62020 -"
      "d /run/ghostship-native-mcp 0750 root ghostship-mcp -"
      # Podman refuses --env-file for a missing path. Create the private retail
      # settings file empty and root-owned; the deployer fills it in place and
      # tmpfiles never overwrites existing content.
      "f /etc/ghostship/retail-store.env 0600 root root -"
      "d ${serviceSecretsDir} 0750 root ghostship-mcp -"
      "d /run/ghostship-keep 0750 ghostship-personal ghostship-mcp -"
      "d /run/ghostship-integrations 0750 root ghostship-mcp -"
      "d /srv/apps/ghostship-private-integrations 0700 ghostship-mcp ghostship-mcp -"
      "d /srv/apps/ghostship-private-integrations/ghostship 0700 ghostship-mcp ghostship-mcp -"
    ];
    # One server-held workspace write gate, generated once outside the Nix
    # store. It is the connector's A2 mutation credential and is never shown to
    # a model. The ACL grants only uid 62020 inside the approved workspace
    # root, adds rather than replaces existing ACLs, and default entries keep
    # future children inheriting it. No group membership and no other host path
    # changes.
    system.activationScripts.ghostship-workspace = {
      deps = [ "users" ];
      text = ''
        install -d -m 0750 -o root -g ghostship-mcp /var/lib/ghostship-workspace
        if [ ! -s /var/lib/ghostship-workspace/write-token ]; then
          (umask 077; head -c 32 /dev/urandom | ${pkgs.coreutils}/bin/base64 | tr -d '\n' > /var/lib/ghostship-workspace/write-token)
        fi
        chmod 0600 /var/lib/ghostship-workspace/write-token
        if [ -d /srv/ghostship/workspace ]; then
          ${pkgs.acl}/bin/setfacl -R -m u:62020:rwX /srv/ghostship/workspace
          ${pkgs.acl}/bin/setfacl -R -d -m u:62020:rwX /srv/ghostship/workspace
        fi
      '';
    };
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
      after = [ "ghostship-desktop-bridge.service" ];
      serviceConfig = { Type = "oneshot"; UMask = "0077"; ExecStartPre = project; ExecStart = render; };
    };
    # Agent Desktop bridge remains available to the existing Keep broker and
    # installed CLI tooling. Its credentials do not enter the native T3 MCP.
    # This unit
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
    # The existing owner-side bridge maintains native OAuth grants. The MCP
    # receives only its private scoped projection, never local issuer access.
    systemd.services.ghostship-t3-bridge = {
      description = "Maintain the shared native T3 MCP authorization";
      after = [ "podman-t3code.service" "ghostship-private-relay-config.service" ];
      serviceConfig = {
        Type = "oneshot";
        ExecStart = pkgs.writeShellScript "ghostship-native-t3-authorization" ''
          set -eu
          umask 077
          request=/srv/apps/ghostship-private-integrations/native-auth/request
          trap 'rm -f "$request"' EXIT
          ${pkgs.nix}/bin/nix copy --no-check-sigs \
            --to local?root=/srv/apps/t3code/nix-root ${runtimes.private.runtime}
          install -d -m 0755 /srv/apps/t3code/nix-root/nix/var/nix/gcroots/ghostship-native-mcp
          ln -sfn ${runtimes.private.runtime} \
            /srv/apps/t3code/nix-root/nix/var/nix/gcroots/ghostship-native-mcp/runtime
          ${pkgs.podman}/bin/podman exec --user 3000:3000 \
            -e HOME=/home/t3code -e T3CODE_HOME=/home/t3code/.t3 t3code \
            ${runtimes.private.runtime}/bin/ghostship-mcp --maintain-auth \
            --native-t3 /home/t3code/.local/bin/t3 --native-home /home/t3code/.t3 \
            --native-access full-access --upstream http://127.0.0.1:3774/mcp \
            --oauth-issuer https://${config.ghostship.apps.t3code.hostname} \
            --token-file /home/t3code/.local/state/ghostship-connector/t3-native-client.json
          canonical=/srv/apps/t3code/home/.local/state/ghostship-connector/t3-native-client.json
          target=/run/ghostship-native-mcp
          install -d -m 0750 -o root -g ghostship-mcp "$target"
          install -m 0400 -o 62020 -g 62020 "$canonical" "$target/t3-token.new"
          mv "$target/t3-token.new" "$target/t3-token"
          for name in ghostship.key ghostship.yaml; do
            install -m 0400 -o 62020 -g 62020 \
              "/run/ghostship-integrations/$name" "$target/$name.new"
            mv "$target/$name.new" "$target/$name"
          done
        '';
        UMask = "0077";
        TimeoutStartSec = 150;
      };
    };
    systemd.timers.ghostship-t3-bridge = {
      wantedBy = [ "multi-user.target" ];
      timerConfig = {
        OnBootSec = "2min";
        OnCalendar = "hourly";
        Persistent = true;
        RandomizedDelaySec = 60;
      };
    };
    systemd.paths.ghostship-t3-bridge = {
      wantedBy = [ "multi-user.target" ];
      pathConfig = {
        PathExists = "/srv/apps/ghostship-private-integrations/native-auth/request";
        Unit = "ghostship-t3-bridge.service";
      };
    };
    # Host CLI picker runs as root or a service account; the explicit path keeps
    # it on the T3 home store instead of guessing HOME (#403).
    environment.variables.GHOSTSHIP_MODEL_EVIDENCE_PATH =
      "/srv/apps/t3code/home/.local/state/ghostship/model-evidence/model-evidence.jsonl";
    ghostship.containerRuntimes.ghostship-private-integrations = {
      runtime = runtimes.integrations;
      extraPackages = [ runtimes.private.openssh ];
    };
    virtualisation.oci-containers.containers.ghostship-private-integrations = {
      image = "ghostship-private-integrations:${baseImage.imageTag}";
      imageFile = baseImage;
      pull = "never";
      user = "62020:62020";
      environment = {
        GHOSTSHIP_MCP_IMAGE_VERSION = "ghostship-private-integrations:${baseImage.imageTag}";
        GHOSTSHIP_MCP_SOCKET = runtimes.private.sharedSocket;
        GHOSTSHIP_T3_MCP_ENDPOINT = "${config.ghostship.apps.t3code.origin}/mcp";
        GHOSTSHIP_T3_MCP_ISSUER = "https://${config.ghostship.apps.t3code.hostname}";
        GHOSTSHIP_T3_MCP_PRIVATE_HTTP = "1";
        GHOSTSHIP_T3_MCP_TOKEN_FILE = "/run/ghostship-integrations/t3-token";
        GHOSTSHIP_T3_MCP_AUTH_WAKE_FILE = "/state/native-auth/request";
        # Controller-owned GitHub surface: the connector receives only the
        # per-repository scoped token, never the owner PAT.
        GHOSTSHIP_GITHUB_ENDPOINT = "http://t3code:37111";
        GHOSTSHIP_GITHUB_TOKEN_FILE = "/run/ghostship-integrations/github-token";
        # The host workspace is mounted at /workspace. Mutations are gated by
        # the server-held write credential; agents never present it.
        GHOSTSHIP_WORKSPACE_ROOT = "/workspace";
        GHOSTSHIP_WORKSPACE_WRITE_TOKEN_FILE = "/run/ghostship-integrations/workspace-token";
        # The existing Agent Desktop contract is a path contract; the
        # projection files hold the key and pinned host key.
        AGENT_DESKTOP_SSH_HOST = "10.89.7.2";
        AGENT_DESKTOP_SSH_PORT = "2222";
        AGENT_DESKTOP_SSH_USER = "abc";
        AGENT_DESKTOP_SSH_KEY = "/run/ghostship-integrations/agent-desktop-key";
        AGENT_DESKTOP_SSH_KNOWN_HOSTS = "/run/ghostship-integrations/agent-desktop-known-hosts";
        # The owner's existing Keep broker; the connector holds no Google
        # credential and only relays its allow-listed operations.
        GHOSTSHIP_KEEP_SOCKET = "/run/ghostship-keep/operations.sock";
        # Restore the legacy browser_window/browser_op/browser_raw names the
        # owner's ChatGPT workflows already use; they map onto the same
        # desktop lease and add no second implementation.
        GHOSTSHIP_DESKTOP_COMPAT = "1";
      };
      volumes = [
        # Native T3/relay credentials, the controller-derived scoped GitHub
        # token, the Agent Desktop contract and the workspace write gate.
        "/run/ghostship-native-mcp:/run/ghostship-integrations:ro"
        # One private Unix socket owned by ghostship-mcp: the broker enforces
        # the caller uid; no Google session or browser credential is mounted.
        "/run/ghostship-keep:/run/ghostship-keep:rw"
        "/srv/apps/ghostship-private-integrations:/state:rw,noexec,nosuid,nodev"
        # Same source as the t3code container's /workspace; repo layout kept.
        "/srv/ghostship/workspace:/workspace"
      ];
      extraOptions = [
        "--read-only" "--cap-drop=ALL" "--security-opt=no-new-privileges"
        "--network=ghostship_net"
        # Agent Desktop's pinned host key is [10.89.7.2]:2222 on its own net.
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
      after = [ "ghostship-t3-bridge.service" "init-ghostship-net.service" ];
      requires = [ "init-ghostship-net.service" ];
      wants = [ "ghostship-t3-bridge.service" ];
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
    # Runs for either selected agent/native MCP source, after container health.
    # Publishes only on a content change, then refreshes and reads back the
    # real ChatGPT consumer; an unverified consumer stays partial (exit 3).
    # Needs: the Agent Desktop SSH contract
    # published by ghostship-desktop-bridge (key, known_hosts, 10.89.7.2:2222),
    # a signed-in ChatGPT session on the `personal` (Assistant) identity, and
    # the plugin id committed in config/skills/chatgpt-plugin.json.
    systemd.services.ghostship-skills-reconcile = {
      description = "Publish the MCP plugin and verify the real ChatGPT consumer";
      wantedBy = [ "multi-user.target" ];
      wants = [ "network-online.target" "podman-ghostship-private-integrations.service" "ghostship-desktop-bridge.service" ];
      after = [ "network-online.target" "podman-ghostship-private-integrations.service"
                "ghostship-desktop-bridge.service" ];
      restartTriggers = [ agent.outPath inputs.ghostship-native-agent.outPath ];
      path = [ pkgs.openssh pkgs.coreutils pkgs.git pkgs.podman ];
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
        UMask = "0077";
        ReadWritePaths = [ "/var/lib/ghostship-skills" ];
        ExecStartPre = activatePrepare;
        ExecStartPost = activateVerify;
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
        ExecStart = lib.escapeShellArgs [
          "${runtimes.private.runtime}/bin/ghostship-rollout" "activate"
          "--skills-cli" skillsOwner
          "--repo" (toString inputs.ghostship-native-agent)
          "--source-sha" inputs.ghostship-native-agent.rev
          "--app-id" ((builtins.fromJSON (builtins.readFile (inputs.ghostship-private-agent + "/config/skills/chatgpt-plugin.json"))).app_binding.id)
          "--state" "/var/lib/ghostship-skills"
          "--bridge" "podman exec -i ghostship-private-integrations /bin/ghostship-mcp ghostship"
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
