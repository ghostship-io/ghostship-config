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
      "--health-on-failure=kill"
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
          DestDir=literal:/downloads/Usenet
          InterDir=literal:/downloads/Usenet/.incomplete
          Server1.Active=literal:yes
          Server1.Name=literal:news.eweka.nl
          Server1.Host=literal:news.eweka.nl
          Server1.Encryption=literal:yes
          Server1.Port=literal:443
          Server1.Username=env:NZBGET_SERVER1_USER
          Server1.Password=env:NZBGET_SERVER1_PASS
          Server1.Cipher=literal:TLS_AES_256_GCM_SHA384
          Server1.Connections=literal:30
          Server2.Active=literal:yes
          Server2.Name=literal:eu.usenetprime.com
          Server2.Host=literal:eu.usenetprime.com
          Server2.Encryption=literal:yes
          Server2.Port=literal:443
          Server2.Username=env:NZBGET_SERVER2_USER
          Server2.Password=env:NZBGET_SERVER2_PASS
          Server2.Cipher=literal:TLS_AES_256_GCM_SHA384
          Server2.Connections=literal:10
          Server2.Level=literal:99
          Server2.Optional=literal:yes
          FakeDetector:BannedExtensions=literal:.exe,.dll,.msi,.bat,.cmd,.ps1,.vbs,.vbe,.js,.jse,.scr,.pif,.application,.gadget,.jar,.com
          DirectUnpack=literal:yes
          ArticleCache=literal:500
          PostStrategy=literal:aggressive
          DirectWrite=literal:no
          WriteBuffer=literal:512
          ParBuffer=literal:128
          PasswordDetector:PassAction=literal:markbad
          DetailTarget=literal:none
          ControlUsername=literal:ghostship
          ControlPassword=literal:""
          UpdateCheck=literal:none
          Category1.Name=literal:sonarr
          Category1.Unpack=literal:yes
          Category2.Name=literal:radarr
          Category2.Unpack=literal:yes
          Category3.Name=literal:prowlarr
          Category3.Unpack=literal:yes
        )

        ${pkgs.ghostship-config}/bin/ghostship-config set "$CONFIG_FILE" "''${nzb_args[@]}"

        chown 3000:3000 "$CONFIG_FILE"
        chmod 644 "$CONFIG_FILE"
      fi
    '';
  };
}
