{ config, lib, pkgs, ... }:

{
  virtualisation.oci-containers.containers."nzbget" = {
    image = "lscr.io/linuxserver/nzbget:latest";
    user = "3000:3000";
    extraOptions = [
      "--network=container:gluetun"
      "--health-cmd=wget -q --spider --tries=1 --timeout=5 http://127.0.0.1:5001/ || exit 1"
      "--health-interval=30s"
      "--health-timeout=10s"
      "--health-retries=5"
      "--health-start-period=1m"
    ];
    environment = {
      TZ = "UTC";
      PUID = "3000";
      PGID = "3000";
      NZBGET_PORT = "5001";
    };
    volumes = [
      "/srv/apps/nzbget:/config"
      "/srv/apps/nzbget/scripts:/scripts"
      "/mnt/share/Downloads:/downloads"
    ];
  };

  systemd.services.podman-nzbget = {
    after = [ "mnt-share.mount" "podman-gluetun.service" ];
    bindsTo = [ "podman-gluetun.service" ];
    wants = [ "mnt-share.mount" ];
  };

  systemd.tmpfiles.rules = [
    "d /srv/apps/nzbget 0755 apps apps -"
    "d /srv/apps/nzbget/scripts 0755 apps apps -"
  ];

  system.activationScripts.nzbget-config = {
    text = ''
      CONFIG_FILE="/srv/apps/nzbget/nzbget.conf"
      SECRETS_FILE="${config.sops.secrets."nzbget-secrets".path}"

      if [ -f "$CONFIG_FILE" ] && [ -f "$SECRETS_FILE" ]; then
        echo "Surgically updating NZBGet config..."
        set -a
        . "$SECRETS_FILE"
        set +a

        nzb_args=(
          --secrets-file "$SECRETS_FILE"
          Server1.Active=literal:yes
          Server1.Name=literal:news.eweka.nl
          Server1.Host=literal:news.eweka.nl
          Server1.Encryption=literal:yes
          Server1.Port=literal:443
          Server1.Username=env:NZBGET_SERVER1_USER
          Server1.Password=env:NZBGET_SERVER1_PASS
          Server1.Connections=literal:25
          Server2.Active=literal:yes
          Server2.Name=literal:eu.usenetprime.com
          Server2.Host=literal:eu.usenetprime.com
          Server2.Encryption=literal:yes
          Server2.Port=literal:443
          Server2.Username=env:NZBGET_SERVER2_USER
          Server2.Password=env:NZBGET_SERVER2_PASS
          Server2.Connections=literal:10
          Server2.Level=literal:99
          Server2.Optional=literal:yes
          Category1.Name=literal:sonarr
          Category1.Unpack=literal:yes
          Category2.Name=literal:radarr
          Category2.Unpack=literal:yes
          Category3.Name=literal:prowlarr
          Category3.Unpack=literal:yes
          ControlUsername=literal:ghostship
          ControlPassword=literal:""
          UpdateCheck=literal:none
          DestDir=literal:/downloads/Usenet
          "InterDir=literal:/downloads/Usenet/.incomplete"
        )

        ${pkgs.ghostship-config}/bin/ghostship-config set "$CONFIG_FILE" "''${nzb_args[@]}"

        chown 3000:3000 "$CONFIG_FILE"
        chmod 644 "$CONFIG_FILE"
      fi
    '';
  };
}
