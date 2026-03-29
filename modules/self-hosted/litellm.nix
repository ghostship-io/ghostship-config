{ config, pkgs, ... }:

{
  virtualisation.oci-containers.containers."litellm" = {
    image = "ghcr.io/berriai/litellm:main-latest";
    extraOptions = [
      "--network=ghostship_net"
    ];
    environment = {
      LITELLM_LOG = "DEBUG";
    };
    environmentFiles = [
      config.sops.secrets."litellm-secrets".path
    ];
    volumes = [
      "/srv/apps/litellm:/app/config"
    ];
  };

  systemd.tmpfiles.rules = [
    "d /srv/apps/litellm 0755 apps apps -"
  ];
}
