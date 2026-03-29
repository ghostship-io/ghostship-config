{ config, pkgs, ... }:

{
  virtualisation.oci-containers.containers."litellm-db" = {
    image = "docker.io/library/postgres:16-alpine";
    extraOptions = [
      "--network=ghostship_net"
    ];
    environment = {
      POSTGRES_USER = "litellm";
      POSTGRES_DB = "litellm";
      POSTGRES_PASSWORD = "env:LITELLM_DB_PASS";
    };
    environmentFiles = [
      config.sops.secrets."litellm-secrets".path
    ];
    volumes = [
      "/srv/apps/litellm-db:/var/lib/postgresql/data"
    ];
  };

  systemd.tmpfiles.rules = [
    "d /srv/apps/litellm-db 0755 apps apps -"
  ];
}
