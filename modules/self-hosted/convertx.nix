{ ... }:

{
  virtualisation.oci-containers.containers."convertx" = {
    image = "ghcr.io/c4illin/convertx:latest";
    user = "3000:3000";
    extraOptions = [
      "--network=ghostship_net"
      "--health-cmd=curl -f http://127.0.0.1:3000 || exit 1"
      "--health-interval=1m"
      "--health-timeout=10s"
      "--health-retries=3"
      "--health-start-period=30s"
    ];
    environment = {
      HTTP_ALLOWED = "true";
      ACCOUNT_REGISTRATION = "false";
      ALLOW_UNAUTHENTICATED = "true";
      HIDE_HISTORY = "true";
    };
    volumes = [
      "/srv/apps/convertx:/app/data:rw"
    ];
  };

  systemd.tmpfiles.rules = [
    "d /srv/apps/convertx 0755 apps apps -"
  ];
}
