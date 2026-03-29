{ config, lib, pkgs, ... }:

let
  # mitmproxy script to strip Origin header from all requests including WebSockets
  strip-origin-py = pkgs.writeText "strip-origin.py" ''
    from mitmproxy import http

    def request(flow: http.HTTPFlow) -> None:
        if "Origin" in flow.request.headers:
            flow.request.headers.pop("Origin")
        if "origin" in flow.request.headers:
            flow.request.headers.pop("origin")
  '';

  # Runtime entrypoint to setup proxy AND run original entrypoint
  patch-script = pkgs.writeShellScript "cloakbrowser-patch" ''
    # Install mitmproxy if not present
    if ! command -v mitmdump &> /dev/null; then
      apt-get update && apt-get install -y mitmproxy
    fi

    # Start mitmproxy in background to strip Origin header
    # Listen on 8080 (external), forward to 8081 (manager)
    # Using --web-open-browser false to prevent issues
    mitmdump -s ${strip-origin-py} --mode reverse:http://localhost:8081 --listen-port 8080 --set termlog_level=error &

    # The original entrypoint starts uvicorn on 8080.
    # We must patch the original entrypoint script to use 8081 instead.
    sed -i 's/--port 8080/--port 8081/g' /entrypoint.sh

    # Execute the original entrypoint
    exec /entrypoint.sh
  '';

in
{
  # CloakBrowser Manager
  virtualisation.oci-containers.containers."cloakbrowser" = {
    image = "cloakhq/cloakbrowser-manager:latest";
    ports = [ 
      "8080:8080"
    ];
    extraOptions = [ "--network=ghostship_net" ];
    # Use our patch script as the entrypoint
    entrypoint = "${patch-script}";
    volumes = [
      "/srv/apps/cloakbrowser/data:/data"
    ];
  };

  # Automatic profile creation for Manager
  systemd.services."cloakbrowser-init-profiles" = {
    description = "Initialize CloakBrowser profiles";
    after = [ "podman-cloakbrowser.service" ];
    wantedBy = [ "multi-user.target" ];
    script = ''
      # Wait for Manager directly on 8081
      until ${pkgs.curl}/bin/curl -s http://localhost:8081/api/status > /dev/null; do
        sleep 2
      done
      
      create_profile() {
        NAME=$1; PROXY=$2;
        EXISTS=$(${pkgs.curl}/bin/curl -s http://localhost:8081/api/profiles | ${pkgs.jq}/bin/jq -r ".[] | select(.name==\"$NAME\") | .id")
        if [ -z "$EXISTS" ]; then
          ${pkgs.curl}/bin/curl -s -X POST http://localhost:8081/api/profiles -H "Content-Type: application/json" \
            -d "{\"name\": \"$NAME\", \"proxy\": $PROXY, \"humanize\": true, \"geoip\": true, \"platform\": \"windows\"}"
        fi
      }
      create_profile "VPN" "\"http://gluetun:8888\""
      create_profile "Direct" "null"
    '';
    serviceConfig = { Type = "oneshot"; RemainAfterExit = true; };
  };

  # Open port 8080 (CDP ports remain internal to ghostship_net)
  networking.firewall.allowedTCPPorts = [ 8080 ];

  systemd.tmpfiles.rules = [
    "d /srv/apps/cloakbrowser 0755 apps apps -"
    "d /srv/apps/cloakbrowser/data 0755 apps apps -"
  ];
}
