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

  # Nginx config to strip Origin header and proxy to Manager
  nginx-config = pkgs.writeText "cloakbrowser-proxy.conf" ''
    server {
        listen 8080;
        
        location / {
            proxy_pass http://cloakbrowser:8080;
            proxy_http_version 1.1;
            
            # WebSocket support
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection "upgrade";
            
            # Strip Origin header to bypass CSWSH check
            proxy_set_header Origin "";
            
            # Standard headers
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            
            # Timeouts for long-lived CDP connections
            proxy_read_timeout 3600s;
            proxy_send_timeout 3600s;
        }
    }
  '';

in
{
  # CloakBrowser Manager
  virtualisation.oci-containers.containers."cloakbrowser" = {
    image = "cloakhq/cloakbrowser-manager:latest";
    # We do NOT map 8080 to the host here; the proxy will handle it
    extraOptions = [ "--network=ghostship_net" ];
    volumes = [
      "/srv/apps/cloakbrowser/data:/data"
      # System-wide policy paths
      "${extensions-json}:/etc/chromium/policies/managed/extensions.json:ro"
      "${ublock-json}:/etc/chromium/policies/managed/ublock-origin.json:ro"
      "${extensions-json}:/etc/opt/chrome/policies/managed/extensions.json:ro"
      "${ublock-json}:/etc/opt/chrome/policies/managed/ublock-origin.json:ro"
      # Portable Chromium specific policy path
      "${extensions-json}:/root/.cloakbrowser/chromium-145.0.7632.159.7/policies/managed/extensions.json:ro"
      "${ublock-json}:/root/.cloakbrowser/chromium-145.0.7632.159.7/policies/managed/ublock-origin.json:ro"
    ];
  };

  # Proxy to strip Origin header
  virtualisation.oci-containers.containers."cloakbrowser-proxy" = {
    image = "nginx:alpine";
    ports = [ "8080:8080" ];
    extraOptions = [ "--network=ghostship_net" ];
    volumes = [
      "${nginx-config}:/etc/nginx/conf.d/default.conf:ro"
    ];
  };

  # Automatic profile creation for Manager
  systemd.services."cloakbrowser-init-profiles" = {
    description = "Initialize CloakBrowser profiles";
    after = [ "podman-cloakbrowser.service" ];
    wantedBy = [ "multi-user.target" ];
    script = ''
      # Wait for Manager
      until ${pkgs.curl}/bin/curl -s http://cloakbrowser:8080/api/status > /dev/null; do
        sleep 2
      done
      
      create_profile() {
        NAME=$1; PROXY=$2;
        EXISTS=$(${pkgs.curl}/bin/curl -s http://cloakbrowser:8080/api/profiles | ${pkgs.jq}/bin/jq -r ".[] | select(.name==\"$NAME\") | .id")
        if [ -z "$EXISTS" ]; then
          ${pkgs.curl}/bin/curl -s -X POST http://cloakbrowser:8080/api/profiles -H "Content-Type: application/json" \
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
