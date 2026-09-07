{
  config,
  lib,
  pkgs,
  ...
}:

let
  sonarr-secrets = config.ghostship.selfHostedSecrets.projections.sonarr.path;
in
{
  ghostship.apps.sonarr = {
    healthPath = "/ping";
    name = "Sonarr";
    group = "Automation";
    description = "TV Series Manager";
    icon = "sh-sonarr";
    order = 60;
    hostname = "sonarr.ghostship.io";
    origin = "http://sonarr:8989";
    widget = {
      type = "sonarr";
      key = "env:SONARR_API_KEY";
    };
    muximux = {
      icon = "muximux-sonarr";
      color = "#35c5f4";
      dropdown = true;
    };
  };

  virtualisation.oci-containers.containers."sonarr" = {
    image = "lscr.io/linuxserver/sonarr:latest";
    pull = "always";
    labels = {
      "io.containers.autoupdate" = "registry";
    };
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
    "d /srv/apps/sonarr 0700 apps apps -"
  ];

  systemd.services.podman-sonarr.preStart = lib.mkAfter ''
    CONFIG_FILE="/srv/apps/sonarr/config.xml"
    SECRETS_FILE="${sonarr-secrets}"
    if [ ! -f "$CONFIG_FILE" ]; then
      printf '<Config/>\n' > "$CONFIG_FILE"
    fi
    if [ -f "$CONFIG_FILE" ]; then
      set -a
      . "$SECRETS_FILE"
      set +a

      sonarr_args=(
        --require-secrets
        --secrets-file "$SECRETS_FILE"
        Config.ApiKey=env:SONARR_API_KEY
        Config.AuthenticationMethod=literal:External
        Config.AuthenticationRequired=literal:DisabledForLocalAddresses
        Config.InstanceName=literal:"Ghostship Sonarr"
        Config.AnalyticsEnabled=literal:False
        Config.UpdateMechanic=literal:Manual
        Config.EnableSsl=literal:False
        Config.LaunchBrowser=literal:False
        Config.UpdateMechanism=literal:Docker
      )

      ${pkgs.ghostship-config}/bin/ghostship-config set "$CONFIG_FILE" "''${sonarr_args[@]}"
      chown 3000:3000 "$CONFIG_FILE"
      chmod 600 "$CONFIG_FILE"
    fi
  '';
}
