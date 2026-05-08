{ config, lib, pkgs, ... }:

let
  cloudflared-secrets = config.ghostship.selfHostedSecrets.projections.cloudflared.path;
  cloudflared-runtime-env = config.ghostship.selfHostedSecrets.projections."cloudflared-runtime".path;
  render-cloudflared-runtime = "${config.ghostship.selfHostedSecrets.render}/bin/ghostship-secret-project cloudflared-runtime";
in

{
  virtualisation.oci-containers.containers."cloudflared" = {
    image = "docker.io/cloudflare/cloudflared:latest";
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

    ${render-cloudflared-runtime}
  '';
}
