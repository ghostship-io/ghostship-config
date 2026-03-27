{ ... }:

{
  virtualisation.oci-containers.containers."searxng-valkey" = {
    image = "valkey/valkey:latest";
    user = "3000:3000";
    extraOptions = [
      "--network=ghostship_net"
      "--health-cmd=valkey-cli ping || exit 1"
      "--health-interval=30s"
      "--health-timeout=10s"
      "--health-retries=5"
      "--health-start-period=1m"
      "--health-on-failure=kill"
    ];
    cmd = [
      "valkey-server"
      "--maxmemory" "256mb"
      "--maxmemory-policy" "allkeys-lru"
      "--save" "60" "1"
    ];
    volumes = [
      "/srv/apps/searxng-valkey:/data:rw"
    ];
  };

  systemd.tmpfiles.rules = [
    "d /srv/apps/searxng-valkey 0755 apps apps -"
  ];
}
