{ ... }:

{
  virtualisation.oci-containers.containers."flaresolverr" = {
    image = "ghcr.io/flaresolverr/flaresolverr:latest";
    extraOptions = [
      "--network=ghostship_net"
      "--health-cmd=curl -f http://127.0.0.1:8191 || exit 1"
      "--health-interval=1m"
      "--health-timeout=10s"
      "--health-retries=3"
      "--health-start-period=30s"
    ];
    environment = {
      TZ = "UTC";
      LOG_LEVEL = "info";
    };
  };

  systemd.tmpfiles.rules = [
    "d /srv/apps/flaresolverr 0755 apps apps -"
  ];
}
