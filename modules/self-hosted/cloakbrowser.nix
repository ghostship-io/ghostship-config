{ config, lib, pkgs, ... }:

let
  # uBlock Origin Extension ID
  ublock-id = "cjpalhdlnbpafiamejdnhcphjbkeiagm";
  
  # Policy for force-installing uBlock Origin
  extensions-policy = {
    ExtensionInstallForcelist = [
      "${ublock-id};https://clients2.google.com/service/update2/crx"
    ];
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
  # Standalone Direct Profile for testing (Directly accessible via 9222)
  virtualisation.oci-containers.containers."cloak-direct" = {
    image = "cloakhq/cloakbrowser:latest";
    cmd = [ 
      "cloakserve", 
      "--listen=0.0.0.0:9222", 
      "--fingerprint=direct-test",
      "--humanize=True"
    ];
    ports = [ "9222:9222" ];
    extraOptions = [ "--network=ghostship_net" ];
    volumes = [
      "/srv/apps/cloakbrowser-direct:/home/cloak/.config/cloakbrowser"
      "${extensions-json}:/etc/chromium/policies/managed/extensions.json:ro"
      "${ublock-json}:/etc/chromium/policies/managed/ublock-origin.json:ro"
    ];
  };

  # Manager for VPN and multi-profile management
  virtualisation.oci-containers.containers."cloakbrowser-manager" = {
    image = "cloakhq/cloakbrowser-manager:latest";
    ports = [ 
      "8080:8080"
      "5100-5102:5100-5102"
    ];
    extraOptions = [ "--network=ghostship_net" ];
    volumes = [
      "/srv/apps/cloakbrowser-manager/data:/data"
      "${extensions-json}:/etc/chromium/policies/managed/extensions.json:ro"
      "${ublock-json}:/etc/chromium/policies/managed/ublock-origin.json:ro"
    ];
  };

  # Automatic profile creation for Manager
  systemd.services."cloakbrowser-init-profiles" = {
    description = "Initialize CloakBrowser profiles";
    after = [ "podman-cloakbrowser-manager.service" ];
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
  networking.firewall.allowedTCPPorts = [ 8080 9222 5100 5101 5102 ];

  systemd.tmpfiles.rules = [
    "d /srv/apps/cloakbrowser-direct 0755 apps apps -"
    "d /srv/apps/cloakbrowser-manager 0755 apps apps -"
    "d /srv/apps/cloakbrowser-manager/data 0755 apps apps -"
  ];
}
