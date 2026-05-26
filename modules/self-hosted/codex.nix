{ config, pkgs, ... }:

let
  codex-state-dir = "/srv/apps/codex";
  containers-root = ../../containers;
  containers-root-str = toString containers-root;
  containers-hash = builtins.substring 11 12 containers-root-str;
  codex-image = "localhost/ghostship-codex:${containers-hash}";
  codex-secrets = config.ghostship.selfHostedSecrets.projections.codex.path;
  render-codex-secrets = "${config.ghostship.selfHostedSecrets.render}/bin/ghostship-secret-project codex";
  codex-build = pkgs.writeShellScriptBin "ghostship-build-codex-image" ''
    set -eu

    image="${codex-image}"
    dockerfile="${containers-root}/codex/Dockerfile"
    context_dir="${containers-root}/codex"

    if [ "''${1:-}" != "--force" ] && ${pkgs.podman}/bin/podman image exists "$image"; then
      exit 0
    fi

    ${pkgs.podman}/bin/podman build \
      --pull=always \
      --tag "$image" \
      --file "$dockerfile" \
      "$context_dir"
  '';
in
{
  virtualisation.oci-containers.containers."codex" = {
    image = codex-image;
    pull = "never";
    labels = {
      "io.containers.autoupdate" = "disabled";
    };
    extraOptions = [
      "--network=ghostship_net"
      "--privileged"
      "--shm-size=2g"
      "--health-cmd=curl -fsS --max-time 5 http://127.0.0.1:5900/ >/dev/null || exit 1"
      "--health-interval=30s"
      "--health-timeout=10s"
      "--health-retries=5"
      "--health-start-period=3m"
      "--health-on-failure=kill"
    ];
    environment = {
      HOME = "/home/codexapp";
      CODEX_HOME = "/home/codexapp/.codex";
      CODEXUI_CODEX_COMMAND = "/usr/local/bin/codex";
      NPM_CONFIG_PREFIX = "/usr/local";
      npm_config_prefix = "/usr/local";
    };
    environmentFiles = [ codex-secrets ];
    volumes = [
      "${codex-state-dir}/home:/home/codexapp:rw"
      "codex-nix:/nix:rw,copy"
      "codex-docker:/var/lib/docker:rw"
    ];
  };

  systemd.tmpfiles.rules = [
    "d ${codex-state-dir} 0755 root root -"
    "d ${codex-state-dir}/home 0755 root root -"
  ];

  systemd.services = {
    podman-codex = {
      preStart = ''
        ${render-codex-secrets}

        if [ ! -f "${codex-secrets}" ]; then
          echo "Missing Codex secret source at ${codex-secrets}" >&2
          exit 1
        fi

        install -d -m0755 -o root -g root \
          ${codex-state-dir} \
          ${codex-state-dir}/home

        ${codex-build}/bin/ghostship-build-codex-image
      '';
    };

    codex-auto-update = {
      description = "Refresh the Codex web container image and npm runtime";
      after = [
        "network-online.target"
        "init-ghostship-net.service"
      ];
      wants = [
        "network-online.target"
        "init-ghostship-net.service"
      ];
      serviceConfig.Type = "oneshot";
      script = ''
        ${codex-build}/bin/ghostship-build-codex-image --force
        ${pkgs.systemd}/bin/systemctl restart podman-codex.service
      '';
    };
  };

  systemd.timers.codex-auto-update = {
    description = "Daily Codex web container refresh";
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnCalendar = "daily";
      Persistent = true;
      RandomizedDelaySec = "30m";
    };
  };
}
