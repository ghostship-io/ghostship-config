{
  config,
  lib,
  pkgs,
  ...
}:

let
  jdownloader-secrets = config.ghostship.selfHostedSecrets.projections.jdownloader.path;
  jdownloader-prestart = pkgs.writeShellScriptBin "jdownloader-prestart" ''
    set -eu

    install -d -m0755 -o apps -g apps /srv/apps/jdownloader
    install -d -m0775 -o apps -g apps /mnt/share/Downloads/JDownloader2
  '';
in
{
  virtualisation.oci-containers.containers."jdownloader" = {
    image = "docker.io/jlesage/jdownloader-2:latest";
    pull = "always";
    labels = {
      "io.containers.autoupdate" = "registry";
    };
    extraOptions = [
      "--network=ghostship_net"
      "--health-cmd=sh -c 'ps | grep -v grep | grep -Eq \"[j]downloader|[J]Downloader|[j]ava\" || exit 1'"
      "--health-interval=30s"
      "--health-timeout=10s"
      "--health-retries=5"
      "--health-start-period=3m"
      "--health-on-failure=kill"
    ];
    environment = {
      USER_ID = "3000";
      GROUP_ID = "3000";
      TZ = "UTC";
      JDOWNLOADER_HEADLESS = "1";
      WEB_LISTENING_PORT = "-1";
      VNC_LISTENING_PORT = "-1";
    };
    environmentFiles = [ jdownloader-secrets ];
    volumes = [
      "/srv/apps/jdownloader:/config:rw"
      "/mnt/share/Downloads/JDownloader2:/output:rw"
    ];
  };

  systemd.services.podman-jdownloader = {
    after = [ "mnt-share.mount" ];
    wants = [ "mnt-share.mount" ];
    preStart = lib.mkAfter ''
      ${jdownloader-prestart}/bin/jdownloader-prestart
    '';
  };

  systemd.tmpfiles.rules = [
    "d /srv/apps/jdownloader 0755 apps apps -"
  ];
}
