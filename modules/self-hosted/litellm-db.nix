{ config, pkgs, ... }:

let
  litellm-secrets = config.sops.secrets."litellm-secrets".path;
in

{
  virtualisation.oci-containers.containers."litellm-db" = {
    image = "docker.io/library/postgres:16-alpine";
    extraOptions = [
      "--network=ghostship_net"
      "--health-cmd=pg_isready -U litellm"
      "--health-interval=10s"
      "--health-timeout=5s"
      "--health-retries=5"
      "--health-start-period=30s"
    ];
    environment = {
      POSTGRES_USER = "litellm";
      POSTGRES_DB = "litellm";
      POSTGRES_PASSWORD = "env:LITELLM_DB_PASS";
    };
    environmentFiles = [
      litellm-secrets
    ];
    volumes = [
      "/srv/apps/litellm-db:/var/lib/postgresql/data"
    ];
  };

  systemd.tmpfiles.rules = [
    "d /srv/apps/litellm-db 0755 apps apps -"
  ];
}
