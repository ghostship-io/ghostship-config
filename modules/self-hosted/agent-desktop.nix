{
  config,
  lib,
  pkgs,
  ...
}:

let
  containers-root = ../../containers/agent-desktop;
  containers-root-str = toString containers-root;
  containers-hash = builtins.substring 11 12 containers-root-str;
  agent-desktop-image = "localhost/ghostship-agent-desktop:${containers-hash}";
  agent-desktop-image-build = pkgs.writeShellScriptBin "ghostship-build-agent-desktop-image" ''
    set -eu

    image=${lib.escapeShellArg agent-desktop-image}
    if [ "''${FORCE_REBUILD:-0}" != "1" ] && ${pkgs.podman}/bin/podman image exists "$image"; then
      exit 0
    fi

    ${pkgs.podman}/bin/podman build \
      --pull=always \
      --tag "$image" \
      --file ${containers-root}/Containerfile \
      ${containers-root}
  '';

  agent-desktop-env = config.ghostship.selfHostedSecrets.projections.agent-desktop.containerPath;

  agent-desktop-ssh-provision = pkgs.writeShellScriptBin "ghostship-agent-desktop-ssh-provision" ''
    set -eu

    data=/srv/apps/agent-desktop/config/agent-desktop
    keydir=/var/lib/ghostship/agent-desktop

    ${pkgs.coreutils}/bin/install -d -o 3000 -g 3000 -m 0755 /srv/apps/agent-desktop /srv/apps/agent-desktop/config
    ${pkgs.coreutils}/bin/install -d -o 3000 -g 3000 -m 0700 "$data" "$data/ssh" "$data/chrome" "$data/bladebro"
    ${pkgs.coreutils}/bin/install -d -m 0700 "$keydir"
    ${pkgs.coreutils}/bin/install -d -o 3000 -g 3000 -m 0700 /srv/apps/t3code/home/.ssh

    if [ ! -f "$keydir/id_ed25519_t3code" ]; then
      ${pkgs.openssh}/bin/ssh-keygen -q -t ed25519 -N "" \
        -C t3code-agent-desktop -f "$keydir/id_ed25519_t3code"
    fi

    ${pkgs.coreutils}/bin/install -o 3000 -g 3000 -m 0600 \
      "$keydir/id_ed25519_t3code" /srv/apps/t3code/home/.ssh/id_agent_desktop
    ${pkgs.coreutils}/bin/install -o 3000 -g 3000 -m 0644 \
      "$keydir/id_ed25519_t3code.pub" /srv/apps/t3code/home/.ssh/id_agent_desktop.pub

    ${pkgs.coreutils}/bin/cat "$keydir/id_ed25519_t3code.pub" > "$data/ssh/authorized_keys"
    ${pkgs.coreutils}/bin/chown 3000:3000 "$data/ssh/authorized_keys"
    ${pkgs.coreutils}/bin/chmod 0600 "$data/ssh/authorized_keys"

    ${pkgs.coreutils}/bin/touch "$data/ssh/authorized_keys.local"
    ${pkgs.coreutils}/bin/chown 3000:3000 "$data/ssh/authorized_keys.local"
    ${pkgs.coreutils}/bin/chmod 0600 "$data/ssh/authorized_keys.local"
  '';

  agent-desktop-mcp = pkgs.writeShellScriptBin "ghostship-agent-desktop-mcp" ''
    exec ${pkgs.python3.withPackages (ps: [ ps.json5 ps.tomli-w ])}/bin/python3 \
      ${./agent-desktop-mcp.py} "$@"
  '';
in
{
  ghostship.apps.agent-desktop = {
    name = "Agent Desktop";
    group = "Management";
    description = "Persistent GUI workstation for agent automation";
    icon = "sh-webtop";
    order = 111;
    hostname = "desktop.ghostship.io";
    origin = "http://agent-desktop:3000";
    healthPath = "/";
    muximux = {
      icon = "muximux-desktop";
      color = "#0ea5e9";
      dropdown = false;
    };
  };

  virtualisation.oci-containers.containers."agent-desktop" = {
    podman.sdnotify = "healthy";
    image = agent-desktop-image;
    pull = "never";
    environment = {
      PUID = "3000";
      PGID = "3000";
      # Match the egress network location (Hawaiian Telcom) so browser
      # timezone checks stay coherent; update if the host's uplink changes.
      TZ = "Pacific/Honolulu";
      TITLE = "Ghostship Desktop";
      START_DOCKER = "false";
      PELORUS = "true";
      SELKIES_MANUAL_WIDTH = "1600";
      SELKIES_MANUAL_HEIGHT = "900";
      SELKIES_MANUAL_RESOLUTION = "true";
      SELKIES_ENABLE_RESIZE = "false";
      SELKIES_FRAMERATE = "30-30";
      SELKIES_AUDIO_ENABLED = "false";
      SELKIES_MICROPHONE_ENABLED = "false";
      SELKIES_WEBCAM_ENABLED = "false";
      NO_WEBCAM = "true";
      NO_GAMEPAD = "true";
      SELKIES_PRINTING_ENABLED = "false";
      SELKIES_VIDEO_STREAMING_MODE = "false";
      SELKIES_USE_CPU = "true";
      AUTO_GPU = "false";
    };
    environmentFiles = [ agent-desktop-env ];
    volumes = [
      "/srv/apps/agent-desktop/config:/config:rw"
    ];
    extraOptions = [
      "--network=agent_desktop_net:ip=10.89.7.2"
      "--network=ghostship_net"
      "--device=/dev/dri"
      "--shm-size=1g"
      "--memory=16g"
      "--health-cmd=/usr/bin/curl -fsS --max-time 5 http://127.0.0.1:3000/ >/dev/null"
      "--health-interval=30s"
      "--health-timeout=10s"
      "--health-retries=5"
      "--health-start-period=3m"
      "--health-on-failure=kill"
    ];
  };

  systemd.services.init-agent-desktop-net = {
    description = "Create agent_desktop_net podman network";
    after = [ "network.target" ];
    before = [
      "podman-agent-desktop.service"
      "podman-t3code.service"
    ];
    wantedBy = [ "multi-user.target" ];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
    };
    script = ''
      ${pkgs.podman}/bin/podman network inspect agent_desktop_net >/dev/null 2>&1 || \
      ${pkgs.podman}/bin/podman network create --subnet 10.89.7.0/24 agent_desktop_net
    '';
  };

  systemd.services.podman-agent-desktop = {
    after = [ "init-agent-desktop-net.service" ];
    requires = [ "init-agent-desktop-net.service" ];
    preStart = lib.mkBefore ''
      ${agent-desktop-image-build}/bin/ghostship-build-agent-desktop-image
    '';
  };

  systemd.services.agent-desktop-ssh = {
    description = "Provision the agent desktop SSH automation key";
    before = [ "podman-agent-desktop.service" ];
    wantedBy = [ "multi-user.target" ];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      UMask = "0077";
    };
    script = "${agent-desktop-ssh-provision}/bin/ghostship-agent-desktop-ssh-provision";
  };

  systemd.services.agent-desktop-mcp = {
    description = "Provision Bladebro MCP access from t3code to the agent desktop";
    after = [
      "agent-desktop-ssh.service"
      "podman-agent-desktop.service"
    ];
    wants = [ "podman-agent-desktop.service" ];
    wantedBy = [ "multi-user.target" ];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      Restart = "on-failure";
      RestartSec = 15;
      UMask = "0077";
    };
    script = ''
      exec ${agent-desktop-mcp}/bin/ghostship-agent-desktop-mcp \
        --home /srv/apps/t3code/home \
        --host-key /srv/apps/agent-desktop/config/agent-desktop/ssh/host/ssh_host_ed25519_key.pub
    '';
  };

  systemd.timers.agent-desktop-mcp = {
    description = "Refresh Bladebro MCP access for all t3code agents";
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnBootSec = "10min";
      OnUnitActiveSec = "daily";
      Persistent = true;
    };
  };

  systemd.tmpfiles.rules = [
    "d /srv/apps/agent-desktop 0755 3000 3000 -"
    "d /srv/apps/agent-desktop/config 0755 3000 3000 -"
  ];
}
