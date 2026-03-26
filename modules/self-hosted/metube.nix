{ ... }:

{
  virtualisation.oci-containers.containers."metube" = {
    image = "ghcr.io/alexta69/metube:latest";
    user = "3000:3000";
    extraOptions = [
      "--network=ghostship_net"
      "--health-cmd=curl -f http://127.0.0.1:8081 || exit 1"
      "--health-interval=1m"
      "--health-timeout=10s"
      "--health-retries=3"
      "--health-start-period=30s"
    ];
    environment = {
      UID = "3000";
      GID = "3000";
    };
    volumes = [
      "/mnt/share/Downloads/MeTube:/downloads:rw"
    ];
  };
}
