{ ... }:

{
  virtualisation.oci-containers.containers."flaresolverr" = {
    image = "ghcr.io/flaresolverr/flaresolverr:latest";
    pull = "always";
    labels = {
      "io.containers.autoupdate" = "registry";
    };
    extraOptions = [
      "--network=ghostship_net"
      "--health-cmd=curl -f --connect-timeout 5 http://127.0.0.1:8191/ || exit 1"
      "--health-interval=30s"
      "--health-timeout=10s"
      "--health-retries=5"
      "--health-start-period=1m"
      "--health-on-failure=kill"
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
