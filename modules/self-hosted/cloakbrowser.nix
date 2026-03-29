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

  # Runtime entrypoint to setup proxy AND run original entrypoint
  patch-script = pkgs.writeShellScript "cloakbrowser-patch" ''
    # Install mitmproxy if not present
    if ! command -v mitmdump &> /dev/null; then
      apt-get update && apt-get install -y mitmproxy
    fi

    # Start mitmproxy in background to strip Origin header
    # Listen on 8080 (external), forward to 8081 (manager)
    mitmdump -s ${strip-origin-py} --mode reverse:http://localhost:8081 --listen-port 8080 --set termlog_level=error &

    # The original entrypoint starts uvicorn on 8080.
    # We must patch the original entrypoint script to use 8081 instead.
    sed -i 's/--port 8080/--port 8081/g' /entrypoint.sh

    # Execute the original entrypoint
    exec /entrypoint.sh
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
    # Use our patch script as the entrypoint
    entrypoint = "${patch-script}";
    volumes = [
      "/srv/apps/cloakbrowser/data:/data"
      "${extensions-json}:/etc/chromium/policies/managed/extensions.json:ro"
      "${ublock-json}:/etc/chromium/policies/managed/ublock-origin.json:ro"
      "${extensions-json}:/etc/opt/chrome/policies/managed/extensions.json:ro"
      "${ublock-json}:/etc/opt/chrome/policies/managed/ublock-origin.json:ro"
    ];
  };

  # Automatic profile creation for Manager
  systemd.services."cloakbrowser-init-profiles" = {
    description = "Initialize CloakBrowser profiles";
    after = [ "podman-cloakbrowser.service" ];
    wantedBy = [ "multi-user.target" ];
    script = ''
      # We must use 8081 here because 8080 (mitmproxy) might not be ready
      # but the manager on 8081 will be.
      until ${pkgs.curl}/bin/curl -s http://localhost:8081/api/status > /dev/null; do sleep 2; done
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

  # Open ports
  networking.firewall.allowedTCPPorts = [ 8080 5100 5101 ];

  systemd.tmpfiles.rules = [
    "d /srv/apps/cloakbrowser 0755 apps apps -"
    "d /srv/apps/cloakbrowser/data 0755 apps apps -"
  ];
}
