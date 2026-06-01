{ lib, pkgs, ... }:

let
  windmillPackage = pkgs.windmill.overrideAttrs (old: {
    buildFeatures = builtins.filter (feature: feature != "jemalloc") old.buildFeatures;
  });
  caddyfile = pkgs.writeText "windmill-caddyfile" ''
    :8000 {
      reverse_proxy host.containers.internal:8001
    }
  '';
in

{
  services.windmill = {
    enable = true;
    package = windmillPackage;
    serverPort = 8001;
    baseUrl = "https://windmill.ghostship.io";
    logLevel = "info";
    database = {
      name = "windmill";
      user = "windmill";
      createLocally = true;
    };
  };

  systemd.services = {
    windmill-worker.environment = {
      DISABLE_NSJAIL = "true";
      ENABLE_UNSHARE_PID = "true";
    };
    windmill-worker-native.environment = {
      DISABLE_NSJAIL = "true";
      ENABLE_UNSHARE_PID = "true";
    };
    podman-windmill = {
      after = [ "windmill-server.service" ];
      wants = [ "windmill-server.service" ];
    };
  };

  virtualisation.oci-containers.containers."windmill" = {
    image = "docker.io/library/caddy:2-alpine";
    pull = "always";
    labels = {
      "io.containers.autoupdate" = "registry";
    };
    extraOptions = [
      "--network=ghostship_net"
      "--health-cmd=wget -q --spider --tries=1 --timeout=5 http://127.0.0.1:8000/ || exit 1"
      "--health-interval=30s"
      "--health-timeout=10s"
      "--health-retries=5"
      "--health-start-period=1m"
      "--health-on-failure=kill"
    ];
    volumes = [
      "${caddyfile}:/etc/caddy/Caddyfile:ro"
    ];
  };
}
