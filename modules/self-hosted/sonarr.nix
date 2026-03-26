{ config, lib, pkgs, ... }:

let
  sonarr-secrets = config.sops.secrets."sonarr-secrets".path;
in
{
  virtualisation.oci-containers.containers."sonarr" = {
    image = "lscr.io/linuxserver/sonarr:latest";
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
      "/srv/apps/sonarr:/config:rw"
      "/mnt/share/Downloads:/downloads:rw"
      "/mnt/share/Library/TV:/tv:rw"
    ];
  };

  systemd.services.podman-sonarr = {
    after = [ "mnt-share.mount" ];
    wants = [ "mnt-share.mount" ];
  };

  systemd.tmpfiles.rules = [
    "d /srv/apps/sonarr 0755 apps apps -"
  ];

  system.activationScripts.sonarr-config = {
    text = ''
      CONFIG_FILE="/srv/apps/sonarr/config.xml"
      SECRETS_FILE="${sonarr-secrets}"
      if [ -f "$CONFIG_FILE" ] && [ -f "$SECRETS_FILE" ]; then
        set -a
        . "$SECRETS_FILE"
        set +a
        ${pkgs.ghostship-config}/bin/ghostship-config set "$CONFIG_FILE" \
          --secrets-file "$SECRETS_FILE" \
          Config.ApiKey=env:SONARR_API_KEY \
          Config.AuthenticationMethod=literal:External \
          Config.AuthenticationRequired=literal:DisabledForLocalAddresses \
          Config.InstanceName=literal:"Ghostship Sonarr" \
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
