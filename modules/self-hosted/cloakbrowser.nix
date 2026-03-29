{ config, lib, pkgs, ... }:

let
  # uBlock Origin Extension ID
  ublock-id = "cjpalhdlnbpafiamejdnhcphjbkeiagm";
  
  # Policy for force-installing uBlock Origin
  extensions-policy = {
    ExtensionInstallForcelist = [
      "${ublock-id};https://clients2.google.com/service/update2/crx"
    ];
    HomepageLocation = "https://nixos.org";
    ShowHomeButton = true;
  };

  # uBlock Origin Managed Storage (Configuration)
  ublock-policy = {
    toOverwrite = {
      filterLists = [
        "user-filters"
        "ublock-filters"
        "ublock-badware"
        "ublock-privacy"
        "ublock-unbreak"
        "ublock-quick-fixes"
        "easylist"
        "easyprivacy"
        "urlhaus-1"
        "plowe-0"
        "adguard-generic"
        "ublock-cookies-easylist"
        "fanboy-cookiemonster"
        "easylist-notifications"
        "easylist-annoyances"
        "adguard-popup-overlays"
        "fanboy-social"
        "easylist-chat"
        "fanboy-ai-suggestions"
      ];
      userSettings = {
        advancedSettings = true;
        dynamicFilteringEnabled = true;
      };
    };
  };

  # Helper to write JSON files for mounting
  extensions-json = pkgs.writeText "extensions.json" (builtins.toJSON extensions-policy);
  ublock-json = pkgs.writeText "ublock-origin.json" (builtins.toJSON ublock-policy);

  # mitmproxy script to strip Origin header
  strip-origin-py = pkgs.writeText "strip-origin.py" ''
    from mitmproxy import http

    def request(flow: http.HTTPFlow) -> None:
        if "Origin" in flow.request.headers:
            del flow.request.headers["Origin"]
  '';

  # Runtime entrypoint to setup proxy and manager
  entrypoint-script = pkgs.writeShellScript "cloakbrowser-entrypoint" ''
    # Install mitmproxy if not present
    if ! command -v mitmdump &> /dev/null; then
      apt-get update && apt-get install -y mitmproxy
    fi

    # Start mitmproxy in background to strip Origin header
    # Listen on 8080 (external), forward to 8081 (manager)
    mitmdump -s ${strip-origin-py} --mode reverse:http://localhost:8081 --listen-port 8080 --set termlog_level=error &

    # Start the manager on 8081
    # We override the command parts from the original entrypoint.sh
    export DISPLAY=:100 # default
    cd /app
    exec uvicorn backend.main:app --host 0.0.0.0 --port 8081 --log-level warning
  '';

in
{
  # CloakBrowser Manager (renamed to cloakbrowser)
  virtualisation.oci-containers.containers."cloakbrowser" = {
    image = "cloakhq/cloakbrowser-manager:latest";
    ports = [ 
      "8080:8080"
      "5100-5101:5100-5101"
    ];
    extraOptions = [ "--network=ghostship_net" ];
    # Use our custom entrypoint
    entrypoint = "${entrypoint-script}";
    volumes = [
      "/srv/apps/cloakbrowser/data:/data"
      "${extensions-json}:/etc/chromium/policies/managed/extensions.json:ro"
      "${ublock-json}:/etc/chromium/policies/managed/ublock-origin.json:ro"
      "${extensions-json}:/etc/opt/chrome/policies/managed/extensions.json:ro"
      "${ublock-json}:/etc/opt/chrome/policies/managed/ublock-origin.json:ro"
    ];
  };

  # Automatic profile creation for Manager
  # Note: curl now points to localhost:8081 inside the container, 
  # or localhost:8080 through the proxy.
  systemd.services."cloakbrowser-init-profiles" = {
    description = "Initialize CloakBrowser profiles";
    after = [ "podman-cloakbrowser.service" ];
    wantedBy = [ "multi-user.target" ];
    script = ''
      until ${pkgs.curl}/bin/curl -s http://localhost:8080/api/status > /dev/null; do sleep 2; done
      create_profile() {
        NAME=$1; PROXY=$2;
        EXISTS=$(${pkgs.curl}/bin/curl -s http://localhost:8080/api/profiles | ${pkgs.jq}/bin/jq -r ".[] | select(.name==\"$NAME\") | .id")
        if [ -z "$EXISTS" ]; then
          ${pkgs.curl}/bin/curl -s -X POST http://localhost:8080/api/profiles -H "Content-Type: application/json" \
            -d "{\"name\": \"$NAME\", \"proxy\": $PROXY, \"humanize\": true, \"geoip\": true, \"platform\": \"windows\"}"
        fi
      }
      create_profile "VPN" "\"http://gluetun:8888\""
      create_profile "Direct" "null"
    '';
    serviceConfig = { Type = "oneshot"; RemainAfterExit = true; };
  };

  # Open ports
  networking.firewall.allowedTCPPorts = [ 8080 5100 5101 ];

  systemd.tmpfiles.rules = [
    "d /srv/apps/cloakbrowser 0755 apps apps -"
    "d /srv/apps/cloakbrowser/data 0755 apps apps -"
  ];
}
