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
  # We use writeText so we can control the exact #! interpreter path inside the container
  patch-script = pkgs.writeText "cloakbrowser-patch.sh" ''
    #!/bin/bash
    set -e

    # Install mitmproxy, curl, and jq if not present
    if ! command -v mitmdump &> /dev/null; then
      apt-get update && apt-get install -y curl jq wget tar
      wget -qO /tmp/mitm.tar.gz https://downloads.mitmproxy.org/10.2.4/mitmproxy-10.2.4-linux-aarch64.tar.gz
      tar -xzf /tmp/mitm.tar.gz -C /usr/local/bin mitmdump
      rm /tmp/mitm.tar.gz
    fi

    # Start mitmproxy in background to strip Origin header
    # Listen on 8080 (external), forward to 8081 (manager)
    mitmdump -s /strip-origin.py --mode reverse:http://127.0.0.1:8081 --listen-port 8080 --set termlog_level=error &

    # The original entrypoint starts uvicorn on 8080.
    # We must patch the original entrypoint script to use 8081 instead.
    sed -i 's/--port 8080/--port 8081/g' /entrypoint.sh

    # Start the manager in the background so we can configure it
    /entrypoint.sh &
    MANAGER_PID=$!

    # Wait for the manager to be ready
    until curl -s http://127.0.0.1:8081/api/status > /dev/null; do
      sleep 2
    done

    # Create profiles if they do not exist
    create_profile() {
      NAME=$1; PROXY=$2;
      EXISTS=$(curl -s http://127.0.0.1:8081/api/profiles | jq -r ".[] | select(.name==\"$NAME\") | .id")
      if [ -z "$EXISTS" ]; then
        curl -s -X POST http://127.0.0.1:8081/api/profiles -H "Content-Type: application/json" \
          -d "{\"name\": \"$NAME\", \"proxy\": $PROXY, \"humanize\": true, \"geoip\": true, \"platform\": \"windows\"}"
      fi
    }
    create_profile "VPN" "\"http://gluetun:8888\""
    create_profile "Direct" "null"

    # Wait for the manager process
    wait $MANAGER_PID
  '';

in
{
  # CloakBrowser Manager
  virtualisation.oci-containers.containers."cloakbrowser" = {
    image = "cloakhq/cloakbrowser-manager:latest";
    extraOptions = [ "--network=ghostship_net" ];
    
    # We execute bash directly to run our mounted script
    entrypoint = "/bin/bash";
    cmd = [ "/cloakbrowser-patch.sh" ];

    volumes = [
      "/srv/apps/cloakbrowser/data:/data"
      "${patch-script}:/cloakbrowser-patch.sh:ro"
      "${strip-origin-py}:/strip-origin.py:ro"
    ];
  };

  systemd.tmpfiles.rules = [
    "d /srv/apps/cloakbrowser 0755 apps apps -"
    "d /srv/apps/cloakbrowser/data 0755 apps apps -"
  ];
}
