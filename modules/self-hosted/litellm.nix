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
      cp ${./litellm-config.yaml} /srv/apps/litellm/config.yaml
      chown -R apps:apps /srv/apps/litellm
    '';
  };

  systemd.tmpfiles.rules = [
    "d /srv/apps/litellm 0755 apps apps -"
  ];
}
