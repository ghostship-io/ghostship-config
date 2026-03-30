{ config, lib, pkgs, ... }:

let
  gluetun-secrets = config.sops.secrets."gluetun-secrets".path;
  gluetun-runtime-env = "/run/secrets/gluetun-runtime.env";
in

{
  virtualisation.oci-containers.containers."gluetun" = {
    image = "docker.io/qmcgaw/gluetun:latest";
    pull = "always";
    labels = {
      "io.containers.autoupdate" = "registry";
    };
    user = "0:3000";
    # Gluetun usually needs some root capabilities for network management
    # but we will try to restrict it where possible.
    extraOptions = [
      "--cap-add=NET_ADMIN"
      "--device=/dev/net/tun:/dev/net/tun"
      "--network=ghostship_net"
    ];
    environment = {
      VPN_TYPE = "openvpn";
      VPN_SERVICE_PROVIDER = "private internet access";
      SERVER_REGIONS = "CA Vancouver";
      OPENVPN_PROTOCOL = "udp";
      VPN_PORT_FORWARDING = "on";
      HTTPPROXY = "on";
      VPN_PORT_FORWARDING_DOWN_COMMAND = ''/bin/sh -c 'wget -O- --retry-connrefused --post-data "json={\"listen_port\":0,\"current_network_interface\":\"lo\"}" http://127.0.0.1:5000/api/v2/app/setPreferences 2>&1' '';
      VPN_PORT_FORWARDING_UP_COMMAND = ''/bin/sh -c 'wget -O- --retry-connrefused --post-data "json={\"listen_port\":{{PORT}},\"current_network_interface\":\"{{VPN_INTERFACE}}\",\"random_port\":false,\"upnp\":false}" http://127.0.0.1:5000/api/v2/app/setPreferences 2>&1' '';
      DNS_ADDRESS = "10.89.0.1";
      UPDATER_PERIOD = "24h";
      TZ = "UTC";
    };
    environmentFiles = [
      gluetun-secrets
      gluetun-runtime-env
    ];
    volumes = [
      "/srv/apps/gluetun:/gluetun"
    ];
  };

  systemd.services.podman-gluetun.serviceConfig.Restart = lib.mkForce "always";

  systemd.services.podman-gluetun.preStart = ''
    if [ ! -f "${gluetun-secrets}" ]; then
      echo "Waiting for Gluetun secrets at ${gluetun-secrets}..."
      for _ in $(seq 1 30); do
        if [ -f "${gluetun-secrets}" ]; then
          break
        fi
        sleep 1
      done
    fi

    if [ ! -f "${gluetun-secrets}" ]; then
      echo "Missing Gluetun secrets file at ${gluetun-secrets}" >&2
      exit 1
    fi

    set -a
    . "${gluetun-secrets}"
    set +a

    OPENVPN_PASSWORD_COMPAT="''${OPENVPN_PASSWORD:-''${OPENVPN_PASS:-}}"
    API_KEY="$HTTP_CONTROL_SERVER_API_KEY"
    mkdir -p /run/secrets
    cat > ${gluetun-runtime-env} <<EOF
OPENVPN_PASSWORD=$OPENVPN_PASSWORD_COMPAT
GLUETUN_API_KEY=$API_KEY
HTTP_CONTROL_SERVER_AUTH_DEFAULT_ROLE={"auth":"apikey","apikey":"$API_KEY","routes":["GET /v1/publicip/ip","GET /v1/openvpn/portforwarded"]}
EOF
    chmod 600 ${gluetun-runtime-env}
  '';

  systemd.services.gluetun-network-monitor = {
    description = "Monitor Gluetun IP and restart dependents on change";
    after = [ "podman-gluetun.service" ];
    wantedBy = [ "multi-user.target" ];
    serviceConfig = {
      Type = "simple";
      ExecStart = "${pkgs.writeShellScript "gluetun-monitor" ''
        set -eu

        LAST_IP=""
        if [ ! -f "${gluetun-secrets}" ]; then
          echo "Waiting for Gluetun secrets at ${gluetun-secrets}..."
          for _ in $(seq 1 30); do
            if [ -f "${gluetun-secrets}" ]; then
              break
            fi
            sleep 1
          done
        fi

        if [ ! -f "${gluetun-secrets}" ]; then
          echo "Missing Gluetun secrets file at ${gluetun-secrets}" >&2
          exit 1
        fi

        set -a
        . "${gluetun-secrets}"
        set +a
        API_KEY="$HTTP_CONTROL_SERVER_API_KEY"
        
        while true; do
          # 1. Wait for containers to be running
          if ! ${pkgs.podman}/bin/podman ps --filter "name=gluetun" --filter "status=running" | grep -q gluetun; then
            sleep 10
            continue
          fi

          # 2. Get current public IP
          CURRENT_IP=$(${pkgs.podman}/bin/podman exec gluetun wget -qO- --header "X-API-Key: $API_KEY" http://127.0.0.1:8000/v1/publicip/ip 2>/dev/null | ${pkgs.jq}/bin/jq -r .public_ip 2>/dev/null || true)
          
          if [ -n "$CURRENT_IP" ] && [ "$CURRENT_IP" != "null" ] && [ "$CURRENT_IP" != "" ]; then
            
            # Check for IP change
            if [ "$CURRENT_IP" != "$LAST_IP" ]; then
              if [ -n "$LAST_IP" ]; then
                echo "Gluetun IP changed from $LAST_IP to $CURRENT_IP. Restarting dependents..."
                systemctl restart podman-nzbget.service podman-vuetorrent.service
              else
                echo "Gluetun IP initialized to $CURRENT_IP."
              fi
              LAST_IP="$CURRENT_IP"
            fi

            # 3. Ensure VueTorrent port is correct (handles manual service restarts)
            # Fetch forwarded port from Gluetun
            FORWARDED_PORT=$(${pkgs.podman}/bin/podman exec gluetun wget -qO- --header "X-API-Key: $API_KEY" http://127.0.0.1:8000/v1/openvpn/portforwarded 2>/dev/null | ${pkgs.jq}/bin/jq -r .port 2>/dev/null || true)
            
            if [ -n "$FORWARDED_PORT" ] && [ "$FORWARDED_PORT" != "null" ] && [ "$FORWARDED_PORT" != "0" ]; then
              # Check if VueTorrent API is responsive
              if ${pkgs.podman}/bin/podman exec gluetun wget -qO- http://127.0.0.1:5000/api/v2/app/version >/dev/null 2>&1; then
                # Get current VueTorrent listen port
                CURRENT_VT_PORT=$(${pkgs.podman}/bin/podman exec gluetun wget -qO- http://127.0.0.1:5000/api/v2/app/preferences 2>/dev/null | ${pkgs.jq}/bin/jq -r .listen_port 2>/dev/null || true)
                
                if [ "$CURRENT_VT_PORT" != "$FORWARDED_PORT" ]; then
                  echo "VueTorrent port mismatch (Current: $CURRENT_VT_PORT, Forwarded: $FORWARDED_PORT). Updating..."
                  ${pkgs.podman}/bin/podman exec gluetun wget -qO- --post-data "json={\"listen_port\":$FORWARDED_PORT,\"random_port\":false,\"upnp\":false}" http://127.0.0.1:5000/api/v2/app/setPreferences >/dev/null 2>&1 || true
                fi
              fi
            fi
          fi
          sleep 30
        done
      ''}";
      Restart = "always";
    };
  };

  systemd.tmpfiles.rules = [
    "d /srv/apps/gluetun 0755 apps apps -"
  ];
}
