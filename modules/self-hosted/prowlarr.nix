{ config, lib, pkgs, ... }:

let
  prowlarr-secrets = config.sops.secrets."prowlarr-secrets".path;
in
{
  virtualisation.oci-containers.containers."prowlarr" = {
    image = "lscr.io/linuxserver/prowlarr:latest";
    user = "3000:3000";
    extraOptions = [
      "--network=ghostship_net"
    ];
    environment = {
      PUID = "3000";
      PGID = "3000";
      TZ = "UTC";
    };
    volumes = [
      "/srv/apps/prowlarr:/config:rw"
    ];
  };

  systemd.tmpfiles.rules = [
    "d /srv/apps/prowlarr 0755 apps apps -"
  ];

  system.activationScripts.prowlarr-config = {
    text = ''
      CONFIG_FILE="/srv/apps/prowlarr/config.xml"
      SECRETS_FILE="${prowlarr-secrets}"
      if [ -f "$CONFIG_FILE" ] && [ -f "$SECRETS_FILE" ]; then
        set -a
        . "$SECRETS_FILE"
        set +a
        ${pkgs.ghostship-config}/bin/ghostship-config set "$CONFIG_FILE" \
          --secrets-file "$SECRETS_FILE" \
          Config.ApiKey=env:PROWLARR_API_KEY \
          Config.AuthenticationMethod=literal:External \
          Config.AuthenticationRequired=literal:DisabledForLocalAddresses \
          Config.InstanceName=literal:"Ghostship Prowlarr" \
          Config.AnalyticsEnabled=literal:False \
          Config.UpdateMechanic=literal:Manual \
          Config.EnableSsl=literal:False \
          Config.LaunchBrowser=literal:False \
          Config.UpdateMechanism=literal:Docker
        chown 3000:3000 "$CONFIG_FILE"
      fi
    '';
  };
}
