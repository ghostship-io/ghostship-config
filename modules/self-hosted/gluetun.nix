{ config, lib, pkgs, ... }:

let
  gluetun-secrets = config.sops.secrets."gluetun-secrets".path;
  gluetun-runtime-env = "/run/secrets/gluetun-runtime.env";
  gluetun-state-dir = "/srv/apps/gluetun";
  gluetun-selection-cache = "${gluetun-state-dir}/pia-wireguard-selection.json";
  pia-ca-cert = ./gluetun/ca.rsa.4096.crt;
  # Live benchmark winner on chill-penguin as of 2026-04-08.
  # At selector time we dynamically enumerate the current endpoints for this
  # region instead of pinning a static server list in the repo.
  gluetun-primary-region = "ca_vancouver";
  gluetun-selection-script = pkgs.writeShellApplication {
    name = "gluetun-pia-selector";
    runtimeInputs = with pkgs; [
      bash
      coreutils
      curl
      findutils
      gawk
      gnused
      jq
      wireguard-tools
    ];
    text = ''
      set -euo pipefail

      secrets_file="$1"
      state_dir="$2"
      cache_file="$3"
      ca_cert="$4"

      if [ ! -f "$secrets_file" ]; then
        echo "Missing Gluetun secrets file at $secrets_file" >&2
        exit 1
      fi

      set -a
      eval "$(grep -Ev "^(#|$)" "$secrets_file")"
      set +a

      pia_user="''${PIA_USER:-''${OPENVPN_USER:-''${USER:-}}}"
      pia_pass="''${PIA_PASS:-''${OPENVPN_PASSWORD:-''${OPENVPN_PASS:-''${PASSWORD:-}}}}"

      if [ -z "$pia_user" ] || [ -z "$pia_pass" ]; then
        echo "Missing PIA credentials in $secrets_file" >&2
        exit 1
      fi

      mkdir -p "$state_dir"
      tmp_dir="$(mktemp -d)"
      trap 'rm -rf "$tmp_dir"' EXIT

      serverlist="$tmp_dir/serverlist.json"
      curl -fsSL https://serverlist.piaservers.net/vpninfo/servers/v6 | sed -n '1p' > "$serverlist"

      token="$(
        curl -fsSL --request POST \
          https://www.privateinternetaccess.com/api/client/v2/token \
          --form "username=$pia_user" \
          --form "password=$pia_pass" \
        | jq -r '.token // empty'
      )"

      if [ -z "$token" ]; then
        echo "Failed to obtain PIA token for server selection" >&2
        exit 1
      fi

      jq -r         --arg primaryRegion '${gluetun-primary-region}' '
          .regions[]
          | select(.id == $primaryRegion)
          | select(.port_forward == true)
          | . as $region
          | (($region.servers.meta // [])[] | { cn: .cn, meta_ip: .ip }) as $meta
          | (($region.servers.wg // [])[] | select(.cn == $meta.cn))
          | [
              $region.id,
              $region.name,
              $region.country,
              $meta.meta_ip,
              .ip,
              .cn
            ]
          | @tsv
        ' "$serverlist" > "$tmp_dir/candidates.tsv"

      if [ ! -s "$tmp_dir/candidates.tsv" ]; then
        jq -r '
            .regions[]
            | select(.port_forward == true)
            | . as $region
            | (($region.servers.meta // [])[] | { cn: .cn, meta_ip: .ip }) as $meta
            | (($region.servers.wg // [])[] | select(.cn == $meta.cn))
            | [
                $region.id,
                $region.name,
                $region.country,
                $meta.meta_ip,
                .ip,
                .cn
              ]
            | @tsv
          ' "$serverlist" > "$tmp_dir/candidates.tsv"
      fi

      : > "$tmp_dir/latency.tsv"
      while IFS=$'\t' read -r region_id region_name country meta_ip wg_ip wg_host; do
        [ -n "$region_id" ] || continue
        connect_time="$(
          curl -4 -o /dev/null -sS \
            --connect-timeout 1.5 \
            --max-time 2 \
            --write-out '%{time_connect}' \
            "http://$meta_ip:443" 2>/dev/null || true
        )"
        if [ -n "$connect_time" ]; then
          printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
            "$connect_time" "$region_id" "$region_name" "$country" "$meta_ip" "$wg_ip" "$wg_host" \
            >> "$tmp_dir/latency.tsv"
        fi
      done < "$tmp_dir/candidates.tsv"

      if [ ! -s "$tmp_dir/latency.tsv" ]; then
        echo "No PF-capable PIA WireGuard endpoints responded during latency probing" >&2
        exit 1
      fi

      sort -n "$tmp_dir/latency.tsv" > "$tmp_dir/top.tsv"

      : > "$tmp_dir/bench.jsonl"
      while IFS=$'\t' read -r connect_time region_id region_name country meta_ip wg_ip wg_host; do
        private_key="$(${pkgs.wireguard-tools}/bin/wg genkey)"
        public_key="$(printf '%s' "$private_key" | ${pkgs.wireguard-tools}/bin/wg pubkey)"

        addkey_metrics="$(
          curl -4 -sS -o "$tmp_dir/addkey-$wg_host.json" \
            --connect-to "$wg_host::$wg_ip:" \
            --cacert "$ca_cert" \
            --get \
            --data-urlencode "pt=$token" \
            --data-urlencode "pubkey=$public_key" \
            --write-out '%{time_connect}\t%{time_starttransfer}\t%{time_total}\t%{size_download}' \
            --max-time 6 \
            "https://$wg_host:1337/addKey" 2>/dev/null || true
        )"

        status="$(jq -r '.status // empty' "$tmp_dir/addkey-$wg_host.json" 2>/dev/null || true)"
        if [ "$status" != "OK" ]; then
          continue
        fi

        addkey_total="$(printf '%s' "$addkey_metrics" | awk -F'\t' '{print $3}')"
        addkey_size="$(printf '%s' "$addkey_metrics" | awk -F'\t' '{print $4}')"
        score="$(awk "BEGIN { printf \"%.6f\", ($connect_time * 0.5) + ($addkey_total * 0.5) }")"

        jq -n \
          --arg region_id "$region_id" \
          --arg region_name "$region_name" \
          --arg country "$country" \
          --arg meta_ip "$meta_ip" \
          --arg wg_ip "$wg_ip" \
          --arg wg_host "$wg_host" \
          --argjson connect_time "$connect_time" \
          --argjson addkey_total "$addkey_total" \
          --argjson addkey_size "''${addkey_size:-0}" \
          --argjson score "$score" \
          '{
            region_id: $region_id,
            region_name: $region_name,
            country: $country,
            meta_ip: $meta_ip,
            wg_ip: $wg_ip,
            wg_host: $wg_host,
            connect_time: $connect_time,
            addkey_total: $addkey_total,
            addkey_size: $addkey_size,
            score: $score
          }' >> "$tmp_dir/bench.jsonl"
      done < "$tmp_dir/top.tsv"

      if [ ! -s "$tmp_dir/bench.jsonl" ]; then
        echo "No PIA WireGuard PF candidates survived the addKey probe" >&2
        exit 1
      fi

      jq -s '
        sort_by(.score)
        | {
            selected_at: (now | todateiso8601),
            winner: .[0],
            fallbacks: (.[1:4] // [])
          }
      ' "$tmp_dir/bench.jsonl" > "$cache_file.tmp"
      mv "$cache_file.tmp" "$cache_file"
      chmod 600 "$cache_file"
    '';
  };
  gluetun-bootstrap-script = pkgs.writeShellApplication {
    name = "gluetun-pia-bootstrap";
    runtimeInputs = with pkgs; [
      bash
      coreutils
      curl
      jq
      wireguard-tools
    ];
    text = ''
      set -euo pipefail

      secrets_file="$1"
      state_dir="$2"
      cache_file="$3"
      runtime_env="$4"
      ca_cert="$5"

      if [ ! -f "$secrets_file" ]; then
        echo "Missing Gluetun secrets file at $secrets_file" >&2
        exit 1
      fi

      if [ ! -s "$cache_file" ]; then
        echo "Missing cached PIA selection file at $cache_file" >&2
        exit 1
      fi

      set -a
      eval "$(grep -Ev "^(#|$)" "$secrets_file")"
      set +a

      pia_user="''${PIA_USER:-''${OPENVPN_USER:-''${USER:-}}}"
      pia_pass="''${PIA_PASS:-''${OPENVPN_PASSWORD:-''${OPENVPN_PASS:-''${PASSWORD:-}}}}"
      api_key="''${HTTP_CONTROL_SERVER_API_KEY:-}"

      if [ -z "$pia_user" ] || [ -z "$pia_pass" ]; then
        echo "Missing PIA credentials in $secrets_file" >&2
        exit 1
      fi

      if [ -z "$api_key" ]; then
        echo "Missing HTTP_CONTROL_SERVER_API_KEY in $secrets_file" >&2
        exit 1
      fi

      wg_ip="$(jq -r '.winner.wg_ip' "$cache_file")"
      wg_host="$(jq -r '.winner.wg_host' "$cache_file")"
      if [ -z "$wg_ip" ] || [ "$wg_ip" = "null" ] || [ -z "$wg_host" ] || [ "$wg_host" = "null" ]; then
        echo "Cached PIA selection file is missing WireGuard winner data" >&2
        exit 1
      fi

      token="$(
        curl -fsSL --request POST \
          https://www.privateinternetaccess.com/api/client/v2/token \
          --form "username=$pia_user" \
          --form "password=$pia_pass" \
        | jq -r '.token // empty'
      )"
      if [ -z "$token" ]; then
        echo "Failed to obtain PIA token for Gluetun bootstrap" >&2
        exit 1
      fi

      private_key_file="$state_dir/pia-wireguard-private.key"
      if [ ! -s "$private_key_file" ]; then
        umask 077
        ${pkgs.wireguard-tools}/bin/wg genkey > "$private_key_file"
      fi
      private_key="$(tr -d '\n' < "$private_key_file")"
      public_key="$(printf '%s' "$private_key" | ${pkgs.wireguard-tools}/bin/wg pubkey)"

      wireguard_json="$(
        curl -4 -fsSL \
          --connect-to "$wg_host::$wg_ip:" \
          --cacert "$ca_cert" \
          --get \
          --data-urlencode "pt=$token" \
          --data-urlencode "pubkey=$public_key" \
          "https://$wg_host:1337/addKey"
      )"

      if [ "$(printf '%s' "$wireguard_json" | jq -r '.status // empty')" != "OK" ]; then
        echo "PIA WireGuard bootstrap failed for $wg_host" >&2
        exit 1
      fi

      peer_ip="$(printf '%s' "$wireguard_json" | jq -r '.peer_ip')"
      server_key="$(printf '%s' "$wireguard_json" | jq -r '.server_key')"
      server_port="$(printf '%s' "$wireguard_json" | jq -r '.server_port')"
      if [ -z "$peer_ip" ] || [ -z "$server_key" ] || [ -z "$server_port" ]; then
        echo "PIA WireGuard bootstrap returned incomplete settings" >&2
        exit 1
      fi

      mkdir -p "$(dirname "$runtime_env")"
      cat > "$runtime_env" <<INNER_EOF
VPN_SERVICE_PROVIDER=custom
VPN_TYPE=wireguard
WIREGUARD_ENDPOINT_IP=$wg_ip
WIREGUARD_ENDPOINT_PORT=$server_port
WIREGUARD_PUBLIC_KEY=$server_key
WIREGUARD_PRIVATE_KEY=$private_key
WIREGUARD_ADDRESSES=$peer_ip
VPN_PORT_FORWARDING=on
VPN_PORT_FORWARDING_PROVIDER=private internet access
VPN_PORT_FORWARDING_USERNAME=$pia_user
VPN_PORT_FORWARDING_PASSWORD=$pia_pass
SERVER_NAMES=$wg_host
GLUETUN_API_KEY=$api_key
HTTP_CONTROL_SERVER_AUTH_DEFAULT_ROLE={"auth":"apikey","apikey":"$api_key","routes":["GET /v1/publicip/ip","GET /v1/portforward","GET /v1/vpn/status"]}
INNER_EOF
      chmod 600 "$runtime_env"
    '';
  };
in

{
  virtualisation.oci-containers.containers."gluetun" = {
    image = "docker.io/qmcgaw/gluetun:latest";
    pull = "always";
    labels = {
      "io.containers.autoupdate" = "registry";
    };
    user = "0:3000";
    extraOptions = [
      "--cap-add=NET_ADMIN"
      "--device=/dev/net/tun:/dev/net/tun"
      "--network=ghostship_net"
      "--health-cmd=/gluetun-entrypoint healthcheck"
      "--health-interval=30s"
      "--health-timeout=10s"
      "--health-retries=5"
      "--health-start-period=1m"
      "--health-on-failure=kill"
    ];
    environment = {
      VPN_SERVICE_PROVIDER = "custom";
      VPN_TYPE = "wireguard";
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
      "${gluetun-state-dir}:/gluetun"
    ];
  };

  systemd.services.podman-gluetun.serviceConfig.Restart = lib.mkForce "always";

  systemd.services.gluetun-pia-selector = {
    description = "Select the preferred PIA WireGuard server for Gluetun";
    serviceConfig = {
      Type = "oneshot";
      ExecStart = "${gluetun-selection-script}/bin/gluetun-pia-selector ${gluetun-secrets} ${gluetun-state-dir} ${gluetun-selection-cache} ${pia-ca-cert}";
    };
  };

  systemd.timers.gluetun-pia-selector = {
    description = "Refresh the preferred PIA WireGuard server daily";
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnBootSec = "10m";
      OnUnitActiveSec = "1d";
      Persistent = true;
    };
  };

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

    install -d -m0755 -o apps -g apps "${gluetun-state-dir}"

    cache_missing=0
    if [ ! -s "${gluetun-selection-cache}" ]; then
      cache_missing=1
    elif [ "$(${pkgs.findutils}/bin/find "${gluetun-selection-cache}" -mtime +1 -print -quit 2>/dev/null)" = "${gluetun-selection-cache}" ]; then
      cache_missing=1
    fi

    if [ "$cache_missing" -eq 1 ]; then
      ${gluetun-selection-script}/bin/gluetun-pia-selector "${gluetun-secrets}" "${gluetun-state-dir}" "${gluetun-selection-cache}" "${pia-ca-cert}"
    fi

    ${gluetun-bootstrap-script}/bin/gluetun-pia-bootstrap "${gluetun-secrets}" "${gluetun-state-dir}" "${gluetun-selection-cache}" "${gluetun-runtime-env}" "${pia-ca-cert}"
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
        PF_FAILURES=0
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
          if ! ${pkgs.podman}/bin/podman ps --filter "name=gluetun" --filter "status=running" | grep -q gluetun; then
            sleep 10
            continue
          fi

          CURRENT_IP=$(${pkgs.podman}/bin/podman exec gluetun wget -qO- --header "X-API-Key: $API_KEY" http://127.0.0.1:8000/v1/publicip/ip 2>/dev/null | ${pkgs.jq}/bin/jq -r .public_ip 2>/dev/null || true)

          if [ -n "$CURRENT_IP" ] && [ "$CURRENT_IP" != "null" ] && [ "$CURRENT_IP" != "" ]; then
            if [ "$CURRENT_IP" != "$LAST_IP" ]; then
              if [ -n "$LAST_IP" ]; then
                echo "Gluetun IP changed from $LAST_IP to $CURRENT_IP. Restarting dependents..."
                systemctl restart podman-nzbget.service podman-vuetorrent.service
              else
                echo "Gluetun IP initialized to $CURRENT_IP."
              fi
              LAST_IP="$CURRENT_IP"
            fi

            VPN_STATUS=$(${pkgs.podman}/bin/podman exec gluetun wget -qO- --header "X-API-Key: $API_KEY" http://127.0.0.1:8000/v1/vpn/status 2>/dev/null | ${pkgs.jq}/bin/jq -r .status 2>/dev/null || true)
            FORWARDED_PORT=$(${pkgs.podman}/bin/podman exec gluetun wget -qO- --header "X-API-Key: $API_KEY" http://127.0.0.1:8000/v1/portforward 2>/dev/null | ${pkgs.jq}/bin/jq -r .port 2>/dev/null || true)

            if [ -n "$FORWARDED_PORT" ] && [ "$FORWARDED_PORT" != "null" ] && [ "$FORWARDED_PORT" != "0" ]; then
              PF_FAILURES=0
              if ${pkgs.podman}/bin/podman exec gluetun wget -qO- http://127.0.0.1:5000/api/v2/app/version >/dev/null 2>&1; then
                CURRENT_VT_PORT=$(${pkgs.podman}/bin/podman exec gluetun wget -qO- http://127.0.0.1:5000/api/v2/app/preferences 2>/dev/null | ${pkgs.jq}/bin/jq -r .listen_port 2>/dev/null || true)

                if [ "$CURRENT_VT_PORT" != "$FORWARDED_PORT" ]; then
                  echo "VueTorrent port mismatch (Current: $CURRENT_VT_PORT, Forwarded: $FORWARDED_PORT). Updating..."
                  ${pkgs.podman}/bin/podman exec gluetun wget -qO- --post-data "json={\"listen_port\":$FORWARDED_PORT,\"random_port\":false,\"upnp\":false}" http://127.0.0.1:5000/api/v2/app/setPreferences >/dev/null 2>&1 || true
                fi
              fi
            elif [ "$VPN_STATUS" = "running" ]; then
              PF_FAILURES=$((PF_FAILURES + 1))
              echo "Gluetun port forwarding is degraded (failure $PF_FAILURES)."
              if [ "$PF_FAILURES" -ge 5 ]; then
                echo "Restarting podman-gluetun after repeated port forwarding failures."
                systemctl restart podman-gluetun.service
                PF_FAILURES=0
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
