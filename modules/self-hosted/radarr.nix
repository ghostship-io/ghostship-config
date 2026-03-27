{ config, lib, pkgs, ... }:

let
  radarr-secrets = config.sops.secrets."radarr-secrets".path;
in
{
  virtualisation.oci-containers.containers."radarr" = {
    image = "lscr.io/linuxserver/radarr:latest";
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
      "/srv/apps/radarr:/config:rw"
      "/mnt/share/Downloads:/downloads:rw"
      "/mnt/share/Library/Movies:/movies:rw"
    ];
  };

  systemd.services.podman-radarr = {
    after = [ "mnt-share.mount" ];
    wants = [ "mnt-share.mount" ];
  };

  systemd.tmpfiles.rules = [
    "d /srv/apps/radarr 0755 apps apps -"
  ];

  system.activationScripts.radarr-config = {
    text = ''
      CONFIG_FILE="/srv/apps/radarr/config.xml"
      SECRETS_FILE="${radarr-secrets}"
      if [ -f "$CONFIG_FILE" ] && [ -f "$SECRETS_FILE" ]; then
        set -a
        . "$SECRETS_FILE"
        set +a

        radarr_args=(
          --secrets-file "$SECRETS_FILE"
          Config.ApiKey=env:RADARR_API_KEY
          Config.AuthenticationMethod=literal:External
          Config.AuthenticationRequired=literal:DisabledForLocalAddresses
          Config.InstanceName=literal:"Ghostship Radarr"
          Config.AnalyticsEnabled=literal:False
          Config.UpdateMechanic=literal:Manual
          Config.EnableSsl=literal:False
          Config.LaunchBrowser=literal:False
          Config.UpdateMechanism=literal:Docker
        )

        ${pkgs.ghostship-config}/bin/ghostship-config set "$CONFIG_FILE" "''${radarr_args[@]}"
        chown 3000:3000 "$CONFIG_FILE"
      fi
    '';
  };
}
