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

  # CDP Bridge using socat to expose CDP ports from container localhost to host 0.0.0.0
  # This avoids the Manager's WebSocket proxy origin check entirely.
  systemd.services."cloakbrowser-cdp-bridge-direct" = {
    description = "Bridge CloakBrowser Direct CDP Port";
    after = [ "podman-cloakbrowser.service" ];
    wantedBy = [ "multi-user.target" ];
    script = ''
      # Map host 9222 to container localhost 5100
      ${pkgs.socat}/bin/socat TCP-LISTEN:9222,fork,reuseaddr TCP:127.0.0.1:5100
    '';
    serviceConfig = { Restart = "always"; RestartSec = 5; };
  };

  systemd.services."cloakbrowser-cdp-bridge-vpn" = {
    description = "Bridge CloakBrowser VPN CDP Port";
    after = [ "podman-cloakbrowser.service" ];
    wantedBy = [ "multi-user.target" ];
    script = ''
      # Map host 9223 to container localhost 5101
      ${pkgs.socat}/bin/socat TCP-LISTEN:9223,fork,reuseaddr TCP:127.0.0.1:5101
    '';
    serviceConfig = { Restart = "always"; RestartSec = 5; };
  };

  # Open ports
  networking.firewall.allowedTCPPorts = [ 8080 9222 9223 ];

  systemd.tmpfiles.rules = [
    "d /srv/apps/cloakbrowser 0755 apps apps -"
    "d /srv/apps/cloakbrowser/data 0755 apps apps -"
  ];
}
