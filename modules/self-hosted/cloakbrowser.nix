{ pkgs, ... }:

let
  cloakbrowser-startup = pkgs.writeText "cloakbrowser-startup.py" (
    builtins.readFile ./cloakbrowser-startup.py
  );
in
{
  virtualisation.oci-containers.containers."cloakbrowser" = {
    image = "docker.io/cloakhq/cloakbrowser-manager:latest";
    pull = "always";
    labels = {
      "io.containers.autoupdate" = "registry";
    };
    entrypoint = "/usr/local/bin/python3";
    cmd = [ "/cloakbrowser-startup.py" ];
    extraOptions = [
      "--network=ghostship_net"
      "--health-cmd=/usr/local/bin/python3 -c 'import urllib.request; urllib.request.urlopen(\"http://127.0.0.1:8080/\", timeout=5).read(1)' || exit 1"
      "--health-interval=30s"
      "--health-timeout=10s"
      "--health-retries=5"
      "--health-start-period=1m"
      "--health-on-failure=kill"
    ];
    volumes = [
      "/srv/apps/cloakbrowser/data:/data:rw"
      "${cloakbrowser-startup}:/cloakbrowser-startup.py:ro"
    ];
  };

  systemd.tmpfiles.rules = [
    "d /srv/apps/cloakbrowser 0755 apps apps -"
    "d /srv/apps/cloakbrowser/data 0755 apps apps -"
  ];
}
