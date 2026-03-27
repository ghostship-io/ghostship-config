{ config, lib, pkgs, ... }:

let
  plex-secrets = config.sops.secrets."plex-secrets".path;
in
{
  virtualisation.oci-containers.containers."plex-auto-languages" = {
    image = "ghcr.io/journeydocker/plex-auto-languages:latest";
    user = "3000:3000";
    extraOptions = [
      "--network=ghostship_net"
      "--health-cmd=pgrep -f main.py || exit 1"
      "--health-interval=30s"
      "--health-timeout=10s"
      "--health-retries=5"
      "--health-start-period=1m"
      "--health-on-failure=kill"
    ];
    environment = {
      TZ = "UTC";
    };
    volumes = [
      "/srv/apps/plex-auto-languages:/config:rw"
    ];
  };

  systemd.tmpfiles.rules = [
    "d /srv/apps/plex-auto-languages 0755 apps apps -"
  ];

  system.activationScripts.pal-config = {
    text = ''
      CONFIG_FILE="/srv/apps/plex-auto-languages/config.yaml"
      
      if [ -f "$CONFIG_FILE" ] && [ -f "${plex-secrets}" ]; then
        echo "Surgically updating PAL config..."
        set -a
        . "${plex-secrets}"
        set +a

        pal_args=(
          --secrets-file "${plex-secrets}"
          plexautolanguages.plex.token=env:PLEX_API_KEY
        )

        ${pkgs.ghostship-config}/bin/ghostship-config set "$CONFIG_FILE" "''${pal_args[@]}"
        chown 3000:3000 "$CONFIG_FILE"
      fi
    '';
  };
}
