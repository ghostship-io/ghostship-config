{ ... }:

{
  virtualisation.oci-containers.containers."bentopdf" = {
    image = "bentopdf/bentopdf:latest";
    extraOptions = [
      "--network=ghostship_net"
      "--health-cmd=wget -q --spider http://127.0.0.1:8080 || exit 1"
      "--health-interval=1m"
      "--health-timeout=10s"
      "--health-retries=3"
      "--health-start-period=30s"
    ];
  };

  systemd.tmpfiles.rules = [
    "d /srv/apps/bentopdf 0755 apps apps -"
  ];
}
