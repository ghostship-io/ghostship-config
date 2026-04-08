{ config, lib, pkgs, ... }:

let
  chaptarr-secrets = config.sops.secrets."chaptarr-secrets".path;
in
{
  virtualisation.oci-containers.containers."chaptarr" = {
    image = "docker.io/robertlordhood/chaptarr:latest";
    pull = "always";
    labels = {
      "io.containers.autoupdate" = "registry";
    };
    user = "3000:3000";
    extraOptions = [
      "--network=ghostship_net"
      "--health-cmd=wget -q -O - --tries=1 --timeout=5 http://127.0.0.1:8789/ping | grep -q '\"status\": \"OK\"' || exit 1"
      "--health-interval=30s"
      "--health-timeout=10s"
      "--health-retries=5"
      "--health-start-period=2m"
      "--health-on-failure=kill"
    ];
    environment = {
      PUID = "3000";
      PGID = "3000";
      TZ = "UTC";
    };
    volumes = [
      "/srv/apps/chaptarr:/config:rw"
      "/mnt/share/Downloads:/downloads:rw"
      "/mnt/share/Library/Books:/books:rw"
      "/mnt/share/Library/Audiobooks:/audiobooks:rw"
    ];
  };

  systemd.services.podman-chaptarr = {
    after = [ "mnt-share.mount" ];
    wants = [ "mnt-share.mount" ];
  };

  systemd.tmpfiles.rules = [
    "d /srv/apps/chaptarr 0755 apps apps -"
  ];

  system.activationScripts.chaptarr-config = {
    text = ''
      CONFIG_FILE="/srv/apps/chaptarr/config.xml"
      SECRETS_FILE="${chaptarr-secrets}"
      if [ -f "$CONFIG_FILE" ] && [ -f "$SECRETS_FILE" ]; then
        set -a
        . "$SECRETS_FILE"
        set +a

        chaptarr_args=(
          --secrets-file "$SECRETS_FILE"
          Config.ApiKey=env:CHAPTARR_API_KEY
          Config.AuthenticationMethod=literal:External
          Config.AuthenticationRequired=literal:DisabledForLocalAddresses
          Config.InstanceName=literal:"Ghostship Chaptarr"
          Config.AnalyticsEnabled=literal:False
          Config.UpdateMechanic=literal:Manual
          Config.EnableSsl=literal:False
          Config.LaunchBrowser=literal:False
          Config.UpdateMechanism=literal:Docker
        )

        ${pkgs.ghostship-config}/bin/ghostship-config set "$CONFIG_FILE" "''${chaptarr_args[@]}"
        chown 3000:3000 "$CONFIG_FILE"
      fi
    '';
  };
}
