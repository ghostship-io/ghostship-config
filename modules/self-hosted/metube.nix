{ ... }:

{
  virtualisation.oci-containers.containers."metube" = {
    image = "ghcr.io/alexta69/metube:latest";
    user = "3000:3000";
    extraOptions = [
      "--network=ghostship_net"
      "--health-cmd=curl -f --connect-timeout 5 http://127.0.0.1:8081/ || exit 1"
      "--health-interval=30s"
      "--health-timeout=10s"
      "--health-retries=5"
      "--health-start-period=1m"
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
