{ ... }:

{
  virtualisation.oci-containers.containers."rss-bridge" = {
    image = "docker.io/rssbridge/rss-bridge:latest";
    pull = "always";
    labels = {
      "io.containers.autoupdate" = "registry";
    };
    user = "3000:3000";
    extraOptions = [
      "--network=ghostship_net"
      "--health-cmd=php -r 'exit(@file_get_contents(\"http://127.0.0.1/\") === false ? 1 : 0);' || exit 1"
      "--health-interval=30s"
      "--health-timeout=10s"
      "--health-retries=5"
      "--health-start-period=1m"
      "--health-on-failure=kill"
    ];
    volumes = [
      "/srv/apps/rss-bridge:/config:rw"
    ];
  };

  systemd.tmpfiles.rules = [
    "d /srv/apps/rss-bridge 0755 apps apps -"
  ];
}
