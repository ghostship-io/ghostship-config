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
      User = { identity = "personal"; expected_email = "<owner-email>"; };
      Agent = { identity = "agent"; expected_email = "<agent-email>"; };
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
          "SSL_CERT_FILE=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
          "GHOSTSHIP_BROWSER_DRIVER=desktop"
          "AGENT_DESKTOP_SSH_HOST=10.89.7.2"
          "AGENT_DESKTOP_SSH_PORT=2222"
          "AGENT_DESKTOP_SSH_USER=abc"
          "AGENT_DESKTOP_SSH_KEY=/run/ghostship-integrations/agent-desktop-key"
          "AGENT_DESKTOP_SSH_KNOWN_HOSTS=/run/ghostship-integrations/agent-desktop-known-hosts"
        ];
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
        OnUnitActiveSec = "daily";
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
        # Both networks are required: ghostship_net reaches T3 and
        # agent_desktop_net reaches the persistent Chrome SSH endpoint.
        "--network=ghostship_net"
        "--network=agent_desktop_net"
        "--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777"
        "--pids-limit=64" "--memory=512m" "--cpus=2"
        "--health-cmd=test -f /tmp/supervisor-live && test $(( $(date +%s) - $(stat -c %Y /tmp/supervisor-live) )) -lt 10"
        "--health-interval=30s" "--health-timeout=5s" "--health-retries=3"
      ];
    };
    systemd.services.podman-ghostship-private-integrations = {
      after = [ "ghostship-keep-broker.service" "ghostship-desktop-bridge.service"
                "init-ghostship-net.service" "init-agent-desktop-net.service" ];
      requires = [ "ghostship-keep-broker.service" "ghostship-desktop-bridge.service"
                   "init-ghostship-net.service" "init-agent-desktop-net.service" ];
      # One stdio relay per ID: systemd/Podman stop the old instance first.
      restartIfChanged = true;
    };
  };
}
