{ config, lib, pkgs, ... }:

let
  cloudflared-secrets = config.sops.secrets."cloudflared-secrets".path;
  cloudflared-runtime-env = "/run/secrets/cloudflared-runtime.env";
in

{
  virtualisation.oci-containers.containers."cloudflared" = {
    image = "cloudflare/cloudflared:latest";
    pull = "always";
    labels = {
      "io.containers.autoupdate" = "registry";
    };
    user = "3000:3000";
    extraOptions = [
      "--network=ghostship_net"
    ];
    environmentFiles = [
      cloudflared-secrets
      cloudflared-runtime-env
    ];
    cmd = [
      "tunnel"
      "run"
    ];
  };

  systemd.services.podman-cloudflared.preStart = ''
    if [ ! -f "${cloudflared-secrets}" ]; then
      echo "Waiting for Cloudflared secrets at ${cloudflared-secrets}..."
      for _ in $(seq 1 30); do
        if [ -f "${cloudflared-secrets}" ]; then
          break
        fi
        sleep 1
      done
    fi

    if [ ! -f "${cloudflared-secrets}" ]; then
      echo "Missing Cloudflared secrets file at ${cloudflared-secrets}" >&2
      exit 1
    fi

    set -a
    . "${cloudflared-secrets}"
    set +a

    mkdir -p /run/secrets
    cat > ${cloudflared-runtime-env} <<EOF
TUNNEL_TOKEN=$CLOUDFLARED_TUNNEL_TOKEN
EOF
    chmod 600 ${cloudflared-runtime-env}
  '';
}
