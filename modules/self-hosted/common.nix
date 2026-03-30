{ config, lib, pkgs, ... }:

let
  dockerhub-secrets = config.sops.secrets."dockerhub-secrets".path;
  dockerhub-auth-file = "/run/containers/0/auth.json";
  dockerhub-legacy-auth-file = "/root/.config/containers/auth.json";
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

  # Common network for all ghostship services
  systemd.services.init-ghostship-net = {
    description = "Create ghostship_net podman network";
    after = [ "network.target" ];
    wantedBy = [ "multi-user.target" ];
    serviceConfig.Type = "oneshot";
    script = ''
      ${pkgs.podman}/bin/podman network inspect ghostship_net >/dev/null 2>&1 || \
      ${pkgs.podman}/bin/podman network create ghostship_net
    '';
  };

  systemd.services.podman-auto-update = {
    description = "Run native Podman auto-update for Ghostship containers";
    after = [ "network-online.target" "init-ghostship-net.service" ];
    wants = [ "network-online.target" "init-ghostship-net.service" ];
    serviceConfig = {
      Type = "oneshot";
      ExecStart = "${pkgs.podman}/bin/podman auto-update";
    };
  };

  systemd.timers.podman-auto-update = {
    description = "Daily native Podman auto-update for Ghostship containers";
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnCalendar = "daily";
      Persistent = true;
      RandomizedDelaySec = "30m";
    };
  };

  system.activationScripts.podman-dockerhub-auth = {
    text = ''
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

      if [ -z "''${DOCKERHUB_USER:-}" ] || [ -z "''${DOCKERHUB_TOKEN:-}" ]; then
        echo "Missing DOCKERHUB_USER or DOCKERHUB_TOKEN in Docker Hub secrets" >&2
        exit 1
      fi

      mkdir -p /run/containers/0 /root/.config/containers
      AUTH="$(${pkgs.coreutils}/bin/printf '%s:%s' "$DOCKERHUB_USER" "$DOCKERHUB_TOKEN" | ${pkgs.coreutils}/bin/base64 -w0)"
      cat > ${dockerhub-auth-file} <<EOF
{"auths":{"https://index.docker.io/v1/":{"auth":"$AUTH"}}}
EOF
      cp ${dockerhub-auth-file} ${dockerhub-legacy-auth-file}
      chmod 600 ${dockerhub-auth-file} ${dockerhub-legacy-auth-file}
    '';
    supportsDryActivation = false;
  };

  # Base directory for all app configurations with strict ownership
  systemd.tmpfiles.rules = [
    "d /srv/apps 0755 apps apps -"
  ];
}
