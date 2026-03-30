{ config, lib, pkgs, ... }:

let
  dockerhub-secrets = config.sops.secrets."dockerhub-secrets".path;
  dockerhub-auth-script = pkgs.writeShellScriptBin "podman-dockerhub-auth" ''
    set -eu

    if [ ! -f "${dockerhub-secrets}" ]; then
      echo "Waiting for Docker Hub secrets at ${dockerhub-secrets}..."
      for _ in $(seq 1 30); do
        if [ -f "${dockerhub-secrets}" ]; then
          break
        fi
        sleep 1
      done
    fi

    if [ ! -f "${dockerhub-secrets}" ]; then
      echo "Missing Docker Hub secrets file at ${dockerhub-secrets}" >&2
      exit 1
    fi

    set -a
    . "${dockerhub-secrets}"
    set +a

    mkdir -p /run/containers/0 /root/.config/containers

    if [ -z "''${DOCKERHUB_USER:-}" ] || [ -z "''${DOCKERHUB_TOKEN:-}" ] || \
       [ "''${DOCKERHUB_USER:-}" = "your-dockerhub-username" ] || \
       [ "''${DOCKERHUB_TOKEN:-}" = "your-dockerhub-api-key" ]; then
      echo "Docker Hub secrets are missing or still placeholder-shaped; writing anonymous auth config" >&2
      cat > /run/containers/0/auth.json <<EOF
{"auths":{}}
EOF
    else
      AUTH="$(${pkgs.coreutils}/bin/printf '%s:%s' "$DOCKERHUB_USER" "$DOCKERHUB_TOKEN" | ${pkgs.coreutils}/bin/base64 -w0)"
      cat > /run/containers/0/auth.json <<EOF
{"auths":{"https://index.docker.io/v1/":{"auth":"$AUTH"}}}
EOF
    fi

    cp /run/containers/0/auth.json /root/.config/containers/auth.json
    chmod 600 /run/containers/0/auth.json /root/.config/containers/auth.json
  '';
  dockerhub-auth-file = "/run/containers/0/auth.json";
  dockerhub-dockerhub-containers =
    lib.attrNames (
      lib.filterAttrs (_: container: builtins.substring 0 10 container.image == "docker.io/") config.virtualisation.oci-containers.containers
    );
in

{
  # Shared configuration for all self-hosted services
  # (Podman is used by default in NixOS)

  # Service user for self-hosted apps
  users.users.apps = {
    isSystemUser = true;
    uid = 3000;
    group = "apps";
    description = "Service user for self-hosted apps";
    shell = "/run/current-system/sw/bin/nologin";
  };
  users.groups.apps.gid = 3000;

  # Common network for all ghostship services and shared Podman update/auth hooks
  systemd.services = lib.mkMerge (
    [
      {
        init-ghostship-net = {
          description = "Create ghostship_net podman network";
          after = [ "network.target" ];
          wantedBy = [ "multi-user.target" ];
          serviceConfig.Type = "oneshot";
          script = ''
            ${pkgs.podman}/bin/podman network inspect ghostship_net >/dev/null 2>&1 || \
            ${pkgs.podman}/bin/podman network create ghostship_net
          '';
        };

        podman-auto-update = {
          description = "Run native Podman auto-update for Ghostship containers";
          after = [ "network-online.target" "init-ghostship-net.service" ];
          wants = [ "network-online.target" "init-ghostship-net.service" ];
          preStart = "${dockerhub-auth-script}/bin/podman-dockerhub-auth";
          environment.REGISTRY_AUTH_FILE = dockerhub-auth-file;
          serviceConfig = {
            Type = "oneshot";
            ExecStart = "${pkgs.podman}/bin/podman auto-update";
          };
        };
      }
    ]
    ++ map
      (name: {
        "podman-${name}" = {
          environment.REGISTRY_AUTH_FILE = dockerhub-auth-file;
          preStart = lib.mkBefore "${dockerhub-auth-script}/bin/podman-dockerhub-auth";
        };
      })
      dockerhub-dockerhub-containers
  );

  systemd.timers.podman-auto-update = {
    description = "Daily native Podman auto-update for Ghostship containers";
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnCalendar = "daily";
      Persistent = true;
      RandomizedDelaySec = "30m";
    };
  };

  # Base directory for all app configurations with strict ownership
  systemd.tmpfiles.rules = [
    "d /srv/apps 0755 apps apps -"
  ];
}
