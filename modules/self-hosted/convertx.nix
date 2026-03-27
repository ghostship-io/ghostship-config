{ ... }:

{
  virtualisation.oci-containers.containers."convertx" = {
    image = "ghcr.io/c4illin/convertx:latest";
    user = "3000:3000";
    extraOptions = [
      "--network=ghostship_net"
      "--health-cmd=curl -f --connect-timeout 5 http://127.0.0.1:3000/ || exit 1"
      "--health-interval=30s"
      "--health-timeout=10s"
      "--health-retries=5"
      "--health-start-period=1m"
      "--health-on-failure=kill"
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
