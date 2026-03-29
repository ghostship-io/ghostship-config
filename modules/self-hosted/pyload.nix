{ pkgs, ... }:

{
  virtualisation.oci-containers.containers."pyload" = {
    image = "lscr.io/linuxserver/pyload-ng:latest";
    extraOptions = [
      "--network=ghostship_net"
    ];
    environment = {
      PUID = "3000";
      PGID = "3000";
      TZ = "UTC";
    };
    volumes = [
      "/srv/apps/pyload:/config"
      "/srv/apps/pyload/downloads:/downloads"
    ];
  };

  systemd.tmpfiles.rules = [
    "d /srv/apps/pyload 0755 apps apps -"
    "d /srv/apps/pyload/downloads 0755 apps apps -"
  ];
}
