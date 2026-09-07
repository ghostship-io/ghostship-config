{
  config,
  lib,
  pkgs,
  ...
}:

let
  prowlarr-secrets = config.ghostship.selfHostedSecrets.projections.prowlarr.path;
in
{
  ghostship.apps.prowlarr = {
    healthPath = "/ping";
    name = "Prowlarr";
    group = "Automation";
    description = "Indexer Manager";
    icon = "sh-prowlarr";
    order = 80;
    hostname = "prowlarr.ghostship.io";
    origin = "http://prowlarr:9696";
    widget = {
      type = "prowlarr";
      key = "env:PROWLARR_API_KEY";
    };
    muximux = {
      icon = "muximux-paw";
      color = "#e45124";
      dropdown = true;
    };
  };

  virtualisation.oci-containers.containers."prowlarr" = {
    image = "lscr.io/linuxserver/prowlarr:latest";
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
      "/srv/apps/prowlarr:/config:rw"
    ];
  };

  systemd.tmpfiles.rules = [
    "d /srv/apps/prowlarr 0700 apps apps -"
  ];

  systemd.services.podman-prowlarr.preStart = lib.mkAfter ''
    CONFIG_FILE="/srv/apps/prowlarr/config.xml"
    SECRETS_FILE="${prowlarr-secrets}"
    if [ ! -f "$CONFIG_FILE" ]; then
      printf '<Config/>\n' > "$CONFIG_FILE"
    fi
    if [ -f "$CONFIG_FILE" ]; then
      set -a
      . "$SECRETS_FILE"
      set +a

      prowlarr_args=(
        --require-secrets
        --secrets-file "$SECRETS_FILE"
        Config.ApiKey=env:PROWLARR_API_KEY
        Config.AuthenticationMethod=literal:External
        Config.AuthenticationRequired=literal:DisabledForLocalAddresses
        Config.InstanceName=literal:"Ghostship Prowlarr"
        Config.AnalyticsEnabled=literal:False
        Config.UpdateMechanic=literal:Manual
        Config.EnableSsl=literal:False
        Config.LaunchBrowser=literal:False
        Config.UpdateMechanism=literal:Docker
      )

      ${pkgs.ghostship-config}/bin/ghostship-config set "$CONFIG_FILE" "''${prowlarr_args[@]}"
      chown 3000:3000 "$CONFIG_FILE"
      chmod 600 "$CONFIG_FILE"
    fi
  '';
}
