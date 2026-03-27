{ config, lib, pkgs, ... }:

{
  virtualisation.oci-containers.containers."cloudflared" = {
    image = "cloudflare/cloudflared:latest";
    user = "3000:3000";
    extraOptions = [
      "--network=ghostship_net"
    ];
    cmd = [
      "sh"
      "-lc"
      "export TUNNEL_TOKEN=\"$CLOUDFLARED_TUNNEL_TOKEN\"; exec cloudflared tunnel --no-autoupdate run"
    ];
    environmentFiles = [
      "/run/secrets/cloudflared-secrets"
    ];
  };
}
