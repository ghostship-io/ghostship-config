{ pkgs, ... }:

let
  egressRules = pkgs.writeText "flaresolverr-egress.nft" (
    builtins.readFile ./flaresolverr-egress.nft
  );
in

{
  ghostship.apps.flaresolverr = {
    healthPath = "/";
    name = "FlareSolverr";
    group = "Utilities";
    description = "Proxy Server";
    icon = "sh-flaresolverr";
    order = 250;
    hostname = "flaresolverr.ghostship.io";
    origin = "http://flaresolverr:8191";
    muximux.enable = false;
  };

  virtualisation.oci-containers.containers."flaresolverr" = {
    podman.sdnotify = "healthy";
    image = "ghcr.io/flaresolverr/flaresolverr:latest";
    pull = "always";
    labels = {
      "io.containers.autoupdate" = "registry";
    };
    extraOptions = [
      "--network=ghostship_net"
      "--ip=10.89.0.16"
      "--mac-address=02:89:00:00:00:16"
      "--cap-drop=NET_RAW,NET_ADMIN"
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

  # Keep the internal API reachable, but deny new outbound connections to
  # private services. Bridge filtering also covers peers on the same network.
  systemd.services.flaresolverr-egress = {
    before = [ "podman-flaresolverr.service" ];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      ExecStart = "${pkgs.nftables}/bin/nft -f ${egressRules}";
      ExecStop = "${pkgs.nftables}/bin/nft destroy table inet ghostship_flaresolverr";
      ExecStopPost = "${pkgs.nftables}/bin/nft destroy table bridge ghostship_flaresolverr";
    };
  };
  systemd.services.podman-flaresolverr = {
    requires = [ "flaresolverr-egress.service" ];
    after = [ "flaresolverr-egress.service" ];
    bindsTo = [ "flaresolverr-egress.service" ];
  };

  systemd.tmpfiles.rules = [
    "d /srv/apps/flaresolverr 0755 apps apps -"
  ];
}
