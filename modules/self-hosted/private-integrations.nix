{ config, lib, pkgs, inputs, ... }:
let
  cfg = config.ghostship.privateIntegrations;
  system = pkgs.stdenv.hostPlatform.system;
  agent = inputs.ghostship-private-agent;
  tools = agent.packages.${system};
  # The deployment owns the shopping overlay (destination and retailer
  # enablement), supplied to the shared tools at runtime. Technical routing
  # lives in ghostship-tools and is not copied here. The Keep broker is now an
  # agent package, so the deployment has one platform input.
  privateAddons = agent.lib.mkPrivateIntegrations {
    inherit system;
    shoppingConfig = {
      overlay = ./private-integrations/shopping-overlay.json;
    };
    mcpIcon = ./private-integrations/ghostship.png;
  };
  brokerConfig = pkgs.writeText "ghostship-keep-broker.json" (builtins.toJSON {
    # Each account names the expected Google identity; the broker verifies the
    # signed-in account on the identity page and resolves its index at session
    # acquisition. No account index is configured or assumed.
    accounts = {
      User = { profile_id = "f0fae36e-2475-4dd9-8e02-ac4bc576d7b1"; expected_email = "<owner-email>"; };
      Agent = { profile_id = "50a1343a-ca9b-4c08-93f0-d0c69eae6643"; expected_email = "<agent-email>"; };
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
  managerAddress = pkgs.writeShellScript "ghostship-personal-manager-address" ''
    set -eu
    address=$(${pkgs.podman}/bin/podman inspect --format '{{(index .NetworkSettings.Networks "ghostship_net").IPAddress}}' cloakbrowser)
    ${pkgs.python3}/bin/python3 - "$address" <<'PYTHON'
    import ipaddress, os, sys
    address = str(ipaddress.ip_address(sys.argv[1]))
    path = "/run/ghostship-personal/manager.env"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o400)
    with os.fdopen(fd, "w") as handle:
        handle.write("GHOSTSHIP_PERSONAL_MANAGER_URL=http://" + address + ":8080\n")
    os.chown(path, 62021, 62021)
    PYTHON
  '';
  render = pkgs.writeShellScript "ghostship-private-relay-render" ''
    set -eu
    ${config.ghostship.selfHostedSecrets.render}/bin/ghostship-secret-project ghostship-relay
    exec ${pkgs.python3}/bin/python3 ${./private-relay-render.py} \
      ${config.ghostship.selfHostedSecrets.projections.ghostship-relay.path} \
      ${privateAddons.runtime}/bin/ghostship-mcp
  '';
in {
  options.ghostship.privateIntegrations.enable = lib.mkEnableOption "private Ghostship Keep and Amazon MCP gateway";
  config = lib.mkIf cfg.enable {
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
    systemd.tmpfiles.rules = [
      "d /run/ghostship-keep 0750 ghostship-personal ghostship-mcp -"
      "d /run/ghostship-integrations 0750 root ghostship-mcp -"
      "d /srv/apps/ghostship-private-integrations 0700 ghostship-mcp ghostship-mcp -"
      "d /srv/apps/ghostship-private-integrations/ghostship 0700 ghostship-mcp ghostship-mcp -"
    ];
    systemd.services.ghostship-keep-broker = {
      description = "Keep API execution service with authentication-only browser access";
      wantedBy = [ "multi-user.target" ];
      serviceConfig = {
        User = "ghostship-personal";
        Group = "ghostship-mcp";
        StateDirectory = "ghostship-keep";
        StateDirectoryMode = "0700";
        RuntimeDirectory = "ghostship-personal";
        RuntimeDirectoryMode = "0700";
        UMask = "0077";
        Environment = [ "SSL_CERT_FILE=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt" ];
        EnvironmentFile = "-/run/ghostship-personal/manager.env";
        ExecStartPre = "+${managerAddress}";
        ExecStart = "${tools.keep-broker}/bin/ghostship-keep-broker --config ${brokerConfig}";
        Restart = "on-failure";
        RestartSec = 3;
        NoNewPrivileges = true;
        ProtectSystem = "strict";
        ProtectHome = true;
        PrivateTmp = true;
        ReadWritePaths = [ "/run/ghostship-keep" ];
        RestrictAddressFamilies = [ "AF_UNIX" "AF_INET" "AF_INET6" ];
        CapabilityBoundingSet = "";
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
    systemd.services.ghostship-t3-bridge = {
      description = "Publish the T3 bridge endpoint and session token for the ChatGPT MCP";
      wantedBy = [ "multi-user.target" ];
      after = [ "podman-t3code.service" ];
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
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
    virtualisation.oci-containers.containers.ghostship-private-integrations = {
      image = "ghostship-private-integrations:${privateAddons.image.imageTag}";
      imageFile = privateAddons.image;
      pull = "never";
      user = "62020:62020";
      volumes = [
        "/run/ghostship-integrations:/run/ghostship-integrations:ro"
        "/run/ghostship-keep:/run/ghostship-keep:ro"
        "/srv/apps/ghostship-private-integrations:/state:rw"
      ];
      extraOptions = [
        "--read-only" "--cap-drop=ALL" "--security-opt=no-new-privileges"
        # Join ghostship_net so the T3 bridge can reach the `t3code` access
        # proxy; the container keeps its own state on mounted volumes.
        "--network=ghostship_net"
        "--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777"
        "--pids-limit=64" "--memory=512m" "--cpus=2"
        "--health-cmd=test -f /tmp/supervisor-live && test $(( $(date +%s) - $(stat -c %Y /tmp/supervisor-live) )) -lt 10"
        "--health-interval=30s" "--health-timeout=5s" "--health-retries=3"
      ];
    };
    systemd.services.podman-ghostship-private-integrations = {
      after = [ "ghostship-keep-broker.service" "init-ghostship-net.service" ];
      requires = [ "ghostship-keep-broker.service" "init-ghostship-net.service" ];
      # One stdio relay per ID: systemd/Podman stop the old instance first.
      restartIfChanged = true;
    };
  };
}
