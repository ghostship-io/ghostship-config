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
  # Standalone Direct Profile for testing
  virtualisation.oci-containers.containers."cloak-direct" = {
    image = "cloakhq/cloakbrowser:latest";
    # Use cloakserve to start CDP server.
    # --listen=0.0.0.0:9222 ensures it is reachable from outside.
    # --fingerprint: use a seed for persistence.
    cmd = [ 
      "cloakserve", 
      "--listen=0.0.0.0:9222", 
      "--fingerprint=direct-test",
      "--humanize=True"
    ];
    ports = [ "9222:9222" ];
    extraOptions = [
      "--network=ghostship_net"
    ];
    volumes = [
      "/srv/apps/cloakbrowser-direct:/home/cloak/.config/cloakbrowser"
      "${extensions-json}:/etc/chromium/policies/managed/extensions.json:ro"
      "${ublock-json}:/etc/chromium/policies/managed/ublock-origin.json:ro"
    ];
  };

  # Open port 9222
  networking.firewall.allowedTCPPorts = [ 9222 ];

  systemd.tmpfiles.rules = [
    "d /srv/apps/cloakbrowser-direct 0755 apps apps -"
  ];
}
