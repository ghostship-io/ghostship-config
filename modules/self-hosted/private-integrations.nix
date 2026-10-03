{ config, lib, pkgs, inputs, ... }:
let
  cfg = config.ghostship.privateIntegrations;
  system = pkgs.stdenv.hostPlatform.system;
  agent = inputs.ghostship-private-agent.packages.${system};
  assistant = inputs.ghostship-private-assistant.packages.${system};
  brokerConfig = pkgs.writeText "ghostship-keep-broker.json" (builtins.toJSON {
    owner = "<owner-email>";
    principal = "chatgpt-personal-owner";
    client = "${agent.google-pp-cli}/bin/google-pp-cli";
    profile_socket = "/run/ghostship-personal/ghostship-assistant/profile-broker.sock";
    runtime_dir = "/run/ghostship-personal";
    database = "/var/lib/ghostship-keep/requests.sqlite";
    socket = "/run/ghostship-keep/operations.sock";
    model_uid = 62020;
    policy_root = "${assistant.policy}";
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
    ${config.ghostship.selfHostedSecrets.render}/bin/ghostship-secret-project ghostship-keep-relay
    ${config.ghostship.selfHostedSecrets.render}/bin/ghostship-secret-project ghostship-amazon-relay
    exec ${pkgs.python3}/bin/python3 ${./private-relay-render.py} \
      ${config.ghostship.selfHostedSecrets.projections.ghostship-keep-relay.path} \
      ${config.ghostship.selfHostedSecrets.projections.ghostship-amazon-relay.path} \
      ${agent.private-mcp}/bin/ghostship-mcp
  '';
in {
  options.ghostship.privateIntegrations.enable = lib.mkEnableOption "private Ghostship Keep and Amazon MCP tunnels";
  config = lib.mkIf cfg.enable {
    ghostship.apps.ghostship-keep = {
      name = "Ghostship Keep";
      container = "ghostship-private-integrations";
      description = "Private MCP tunnel; personal account requires reviewed activation and per-action approval";
      hostname = null;
      origin = null;
    };
    ghostship.apps.ghostship-amazon = {
      name = "Ghostship Amazon";
      container = "ghostship-private-integrations";
      description = "Private anonymous shopping reads; partial delivery and pricing coverage";
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
    environment.systemPackages = [ assistant.keep-approve ];
    systemd.tmpfiles.rules = [
      "d /run/ghostship-keep 0750 ghostship-personal ghostship-mcp -"
      "d /run/ghostship-integrations 0750 root ghostship-mcp -"
      "d /srv/apps/ghostship-private-integrations 0700 ghostship-mcp ghostship-mcp -"
      "d /srv/apps/ghostship-private-integrations/keep 0700 ghostship-mcp ghostship-mcp -"
      "d /srv/apps/ghostship-private-integrations/amazon 0700 ghostship-mcp ghostship-mcp -"
    ];
    systemd.services.ghostship-keep-broker = {
      description = "Protected complete-operation personal Keep broker";
      wantedBy = [ "multi-user.target" ];
      serviceConfig = {
        User = "ghostship-personal";
        Group = "ghostship-mcp";
        StateDirectory = "ghostship-keep";
        StateDirectoryMode = "0700";
        RuntimeDirectory = "ghostship-personal";
        RuntimeDirectoryMode = "0700";
        UMask = "0077";
        ExecStart = "${assistant.keep-broker}/bin/ghostship-keep-broker --config ${brokerConfig}";
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
    # The existing protected profile broker starts only after its own explicit
    # activation gate passes. The operation broker does not enable it.
    systemd.services.ghostship-personal-profile-broker = {
      description = "Protected personal browser profile broker";
      after = [ "ghostship-keep-broker.service" "podman-cloakbrowser.service" ];
      requires = [ "ghostship-keep-broker.service" ];
      serviceConfig = {
        User = "ghostship-personal";
        Group = "ghostship-personal";
        Environment = [ "XDG_RUNTIME_DIR=/run/ghostship-personal" "XDG_STATE_HOME=/var/lib/ghostship-keep" ];
        EnvironmentFile = "-/run/ghostship-personal/manager.env";
        ExecStartPre = "+${managerAddress}";
        ExecStart = "${assistant.profile-broker}/bin/ghostship-assistant-profile-broker";
        NoNewPrivileges = true;
        ProtectHome = true;
        ProtectSystem = "strict";
        ReadWritePaths = [ "/run/ghostship-personal" "/var/lib/ghostship-keep" ];
        UMask = "0077";
      };
    };
    systemd.services.ghostship-private-relay-config = {
      description = "Render scoped private MCP relay credentials";
      before = [ "podman-ghostship-private-integrations.service" ];
      requiredBy = [ "podman-ghostship-private-integrations.service" ];
      serviceConfig = { Type = "oneshot"; ExecStart = render; UMask = "0077"; };
    };
    virtualisation.oci-containers.containers.ghostship-private-integrations = {
      image = "ghostship-private-integrations:${agent.private-integration-image.imageTag}";
      imageFile = agent.private-integration-image;
      pull = "never";
      user = "62020:62020";
      volumes = [
        "/run/ghostship-integrations:/run/ghostship-integrations:ro"
        "/run/ghostship-keep:/run/ghostship-keep:ro"
        "/srv/apps/ghostship-private-integrations:/state:rw"
      ];
      extraOptions = [
        "--read-only" "--cap-drop=ALL" "--security-opt=no-new-privileges"
        "--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777"
        "--pids-limit=64" "--memory=512m" "--cpus=2"
        "--health-cmd=test -f /tmp/supervisor-live && test $(( $(date +%s) - $(stat -c %Y /tmp/supervisor-live) )) -lt 10"
        "--health-interval=30s" "--health-timeout=5s" "--health-retries=3"
      ];
    };
    systemd.services.podman-ghostship-private-integrations = {
      after = [ "ghostship-keep-broker.service" ];
      requires = [ "ghostship-keep-broker.service" ];
      # One stdio relay per ID: systemd/Podman stop the old instance first.
      restartIfChanged = true;
    };
  };
}
