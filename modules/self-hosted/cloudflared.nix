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
      "exec cloudflared tunnel --no-autoupdate run --token \"$CLOUDFLARED_TUNNEL_TOKEN\""
    ];
    environmentFiles = [
      "/run/secrets/cloudflared-secrets"
    ];
  };
}
