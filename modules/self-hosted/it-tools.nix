{ ... }:

{
  virtualisation.oci-containers.containers."it-tools" = {
    image = "corentinth/it-tools:latest";
    extraOptions = [
      "--network=ghostship_net"
      "--health-cmd=wget -q --spider http://127.0.0.1:80 || exit 1"
      "--health-interval=1m"
      "--health-timeout=10s"
      "--health-retries=3"
      "--health-start-period=30s"
    ];
  };
}
