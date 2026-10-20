{
  config,
  lib,
  pkgs,
  inputs,
  ...
}:

let
  chaptarr-secrets = config.ghostship.selfHostedSecrets.projections.chaptarr.path;
  ebookConverter = inputs.ghostship-private-agent.packages.${pkgs.stdenv.hostPlatform.system}.ebook-converter;
in
{
  ghostship.apps.chaptarr = {
    healthPath = "/ping";
    name = "Chaptarr";
    group = "Automation";
    description = "Book Manager";
    icon = "sh-readarr";
    order = 140;
    hostname = "chaptarr.ghostship.io";
    origin = "http://chaptarr:8789";
    widget = {
      type = "readarr";
      key = "env:CHAPTARR_API_KEY";
    };
    muximux = {
      icon = "fa-book";
      color = "#4f8ef7";
      dropdown = true;
    };
  };

  virtualisation.oci-containers.containers."chaptarr" = {
    podman.sdnotify = "healthy";
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
      "/srv/apps/chaptarr:/config:rw,noexec,nosuid,nodev"
      "/mnt/share/Downloads:/downloads:rw,noexec,nosuid,nodev"
      "/mnt/share/Library/Books:/books:rw,noexec,nosuid,nodev"
      "/mnt/share/Library/Audiobooks:/audiobooks:rw,noexec,nosuid,nodev"
    ];
  };

  systemd.services.podman-chaptarr = {
    after = [ "mnt-share.mount" ];
    wants = [ "mnt-share.mount" ];
  };

  systemd.services.ghostship-ebook-convert = {
    description = "Convert imported books to EPUB while retaining their originals";
    after = [ "mnt-share.mount" ];
    requires = [ "mnt-share.mount" ];
    environment = {
      HOME = "/var/lib/ghostship-ebook-convert";
      CALIBRE_CONFIG_DIRECTORY = "/var/lib/ghostship-ebook-convert/calibre";
    };
    serviceConfig = {
      Type = "oneshot";
      User = "apps";
      Group = "apps";
      StateDirectory = "ghostship-ebook-convert";
      StateDirectoryMode = "0750";
      UMask = "0022";
      ExecStart = "${ebookConverter}/bin/ghostship-ebook-convert --library /mnt/share/Library/Books --state /var/lib/ghostship-ebook-convert --minimum-age 120";
      PrivateNetwork = true;
      PrivateTmp = true;
      ProtectSystem = "strict";
      ProtectHome = true;
      ReadWritePaths = [ "/mnt/share/Library/Books" ];
      InaccessiblePaths = [ "/srv" "-/run/ghostship-secrets" "-/run/agenix" ];
      NoNewPrivileges = true;
      CapabilityBoundingSet = "";
      RestrictSUIDSGID = true;
      MemoryMax = "2G";
      TasksMax = 128;
      CPUQuota = "100%";
      TimeoutStartSec = "35min";
    };
  };

  systemd.timers.ghostship-ebook-convert = {
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnBootSec = "3min";
      OnUnitInactiveSec = "5min";
      Unit = "ghostship-ebook-convert.service";
    };
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
