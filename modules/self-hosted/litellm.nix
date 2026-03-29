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
    cmd = [
      "--config" "/app/config/config.yaml"
      "--port" "4000"
    ];
    environmentFiles = [
      config.sops.secrets."litellm-secrets".path
    ];
    volumes = [
      "/srv/apps/litellm:/app/config"
    ];
  };

  system.activationScripts.litellm-config = {
    text = ''
      mkdir -p /srv/apps/litellm
      if [ ! -f /srv/apps/litellm/config.yaml ]; then
        echo "model_list: []" > /srv/apps/litellm/config.yaml
      fi
      chown -R apps:apps /srv/apps/litellm
    '';
  };

  systemd.tmpfiles.rules = [
    "d /srv/apps/litellm 0755 apps apps -"
  ];
}
