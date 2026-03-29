{ config, pkgs, ... }:

{
  virtualisation.oci-containers.containers."litellm" = {
    image = "ghcr.io/berriai/litellm:main-latest";
    extraOptions = [
      "--network=ghostship_net"
    ];
    environment = {
      LITELLM_LOG = "DEBUG";
      STORE_MODEL_IN_DB = "True";
      USE_PRISMA_MIGRATE = "True";
      # Production best practices
      PROXY_BATCH_WRITE_AT = "60";
      DATABASE_CONNECTION_POOL_LIMIT = "10";
      ALLOW_REQUESTS_ON_DB_UNAVAILABLE = "True";
      DISABLE_LOAD_DOTENV = "True";
    };
    environmentFiles = [
      config.sops.secrets."litellm-secrets".path
    ];
  };

  systemd.tmpfiles.rules = [
    "d /srv/apps/litellm 0755 apps apps -"
  ];
}
