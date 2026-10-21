{
  config,
  lib,
  pkgs,
  ...
}:

let
  # Copy only the build context so the image tag and unit change with the
  # container sources, not with every commit to this repository.
  containers-root = builtins.path {
    path = ../../containers/agent-desktop;
    name = "ghostship-agent-desktop-context";
  };
  agent-desktop-image = import ./agent-desktop-image-tag.nix { path = ../../containers/agent-desktop; };
  versions = builtins.fromJSON (builtins.readFile ../../containers/agent-desktop/versions.json);
  build-args = lib.escapeShellArgs [
    "--build-arg=BASE_IMAGE=${versions.base.image}@${versions.base.digest}"
    "--build-arg=CHROME_VERSION=${versions.chrome.version}"
    "--build-arg=CHROME_SHA256_ARM64=${versions.chrome.sha256.arm64}"
    "--build-arg=CHROME_SHA256_AMD64=${versions.chrome.sha256.amd64}"
    "--build-arg=BLADEBRO_VERSION=${versions.bladebro.version}"
    "--build-arg=BLADEBRO_SHA256_ARM64=${versions.bladebro.sha256.arm64}"
    "--build-arg=BLADEBRO_SHA256_AMD64=${versions.bladebro.sha256.amd64}"
  ];
  agent-desktop-image-build = pkgs.writeShellScriptBin "ghostship-build-agent-desktop-image" ''
    set -eu

    image=${lib.escapeShellArg agent-desktop-image}
    if [ "''${FORCE_REBUILD:-0}" != "1" ] && ${pkgs.podman}/bin/podman image exists "$image"; then
      exit 0
    fi

    ${pkgs.podman}/bin/podman build \
      --pull=always \
      ${build-args} \
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
    exec ${
      pkgs.python3.withPackages (ps: [
        ps.json5
        ps.tomli-w
      ])
    }/bin/python3 \
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
    # The desktop serves the agent viewer (/agents/); see the profile file.
    apparmorProfile = "ghostship-agent-desktop";
    apparmorProcessProfiles = [
      "ghostship-agent-desktop"
      "ghostship-desktop-viewer"
      "ghostship-agent-desktop//nginx"
      "ghostship-agent-desktop//sshd"
      "ghostship-agent-desktop//dbus-system"
      "ghostship-agent-desktop//pulseaudio"
      "ghostship-agent-desktop//selkies"
      "ghostship-agent-desktop//pelorus"
      "ghostship-agent-desktop//desktop"
      "ghostship-agent-desktop//api"
      "ghostship-agent-desktop//chrome-control"
      "ghostship-agent-desktop//chrome-agent-launcher"
      "ghostship-agent-desktop//chrome-personal-launcher"
      "ghostship-agent-desktop//chrome-agent"
      "ghostship-agent-desktop//chrome-personal"
      "ghostship-agent-desktop//sway"
      "ghostship-agent-desktop//stage-control"
      "ghostship-agent-desktop//agent-shell"
      "ghostship-agent-desktop//bladebro"
      "ghostship-agent-desktop//sudo"
      "ghostship-agent-desktop//chrome-instance-launcher"
      "ghostship-agent-desktop//chrome-other"
      "ghostship-agent-desktop//healthcheck"
    ];
    apparmorRequiredProcessProfiles = [
      "ghostship-agent-desktop"
      "ghostship-desktop-viewer"
      "ghostship-agent-desktop//nginx"
      "ghostship-agent-desktop//sshd"
      "ghostship-agent-desktop//dbus-system"
      "ghostship-agent-desktop//pulseaudio"
      "ghostship-agent-desktop//selkies"
      "ghostship-agent-desktop//pelorus"
      "ghostship-agent-desktop//desktop"
      "ghostship-agent-desktop//api"
      "ghostship-agent-desktop//chrome-control"
    ];
    # The root is the Access-protected viewer; Selkies' static page is public to the origin.
    healthPath = "/desktop/";
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
      # Selkies serves under /desktop/; the agent viewer owns the site root
      # (nginx-agents-patch.py writes the same prefix into nginx).
      SUBFOLDER = "/desktop/";
      # Agents work in their browser stages, not on this desktop, so the
      # desktop follows the client's screen (phones included).
      SELKIES_ENABLE_RESIZE = "true";
      SELKIES_FRAMERATE = "30-30";
      SELKIES_AUDIO_ENABLED = "true";
      SELKIES_AUDIO_ON_START = "false";
      SELKIES_MICROPHONE_ENABLED = "false";
      SELKIES_WEBCAM_ENABLED = "false";
      NO_WEBCAM = "true";
      NO_GAMEPAD = "true";
      SELKIES_PRINTING_ENABLED = "false";
      SELKIES_VIDEO_STREAMING_MODE = "false";
      SELKIES_USE_CPU = "true";
      AUTO_GPU = "false";
      # Let run-chrome stop Chrome cleanly (cookie and storage flush) when
      # the container stops; s6 kills services after 3 s by default.
      # The agent viewer verifies the Cloudflare Access token on every request.
      VIEWER_ACCESS_TEAM = "ghostshipio.cloudflareaccess.com";
      VIEWER_ACCESS_AUD = "b90856384c6d4120cf5e5905b41cf2aa0655b675f48524237be1068f8fffb276"; # gitleaks:allow -- public Access audience tag, carried in every Access JWT
      S6_SERVICES_GRACETIME = "30000";
      S6_KILL_GRACETIME = "5000";
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
      "--pids-limit=4096"
      "--health-cmd=/usr/bin/curl -fsS --max-time 5 http://127.0.0.1:3000/desktop/ >/dev/null"
      "--health-interval=30s"
      "--health-timeout=10s"
      "--health-retries=5"
      "--health-start-period=3m"
      "--health-on-failure=kill"
      # Chrome flushes cookies and site storage on a clean exit; give s6
      # and run-chrome time to stop it before Podman kills the container.
      "--stop-timeout=60"
    ];
  };

  security.apparmor.policies.ghostship-agent-desktop = {
    state = "complain";
    profile = builtins.readFile ./agent-desktop-apparmor.profile;
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
    # Close app sessions (apps get to save) and save browser sessions before
    # the container stops: Chrome loses cookies written in its last ~30 s
    # unless it shuts down normally.
    preStop = lib.mkBefore ''
      ${pkgs.podman}/bin/podman exec -u abc agent-desktop /opt/ghostship-agent-desktop/app-session close-all || true
      ${pkgs.podman}/bin/podman exec agent-desktop /opt/ghostship-agent-desktop/chrome-stop-all || true
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
    description = "Provision Bladebro SSH access from t3code to the agent desktop";
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
      User = "apps";
      Group = "apps";
      NoNewPrivileges = true;
      ProtectSystem = "strict";
      ProtectHome = true;
      ReadWritePaths = [ "/srv/apps/t3code/home" ];
    };
    script = ''
      exec ${agent-desktop-mcp}/bin/ghostship-agent-desktop-mcp \
        --home /srv/apps/t3code/home \
        --host-key /srv/apps/agent-desktop/config/agent-desktop/ssh/host/ssh_host_ed25519_key.pub
    '';
  };

  systemd.timers.agent-desktop-mcp = {
    description = "Refresh Bladebro SSH access for t3code";
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnBootSec = "10min";
      OnUnitActiveSec = "1d";
      Persistent = true;
    };
  };

  systemd.tmpfiles.rules = [
    "d /srv/apps/agent-desktop 0755 3000 3000 -"
    "d /srv/apps/agent-desktop/config 0755 3000 3000 -"
  ];
}
