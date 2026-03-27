{ ... }:

{
  virtualisation.oci-containers.containers."bentopdf" = {
    image = "bentopdf/bentopdf:latest";
    extraOptions = [
      "--network=ghostship_net"
      "--health-cmd=wget -q --spider --tries=1 --timeout=5 http://127.0.0.1:8080/ || exit 1"
      "--health-interval=30s"
      "--health-timeout=10s"
      "--health-retries=5"
      "--health-start-period=1m"
    ];
  };

  systemd.tmpfiles.rules = [
    "d /srv/apps/bentopdf 0755 apps apps -"
  ];
}
