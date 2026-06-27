{
  config,
  lib,
  pkgs,
  ...
}:

let
  gluetun-secrets = config.ghostship.selfHostedSecrets.projections.gluetun.path;
  gluetun-runtime-env = "/run/secrets/gluetun-runtime.env";
  gluetun-state-dir = "/srv/apps/gluetun";
  gluetun-selection-cache = "${gluetun-state-dir}/pia-wireguard-selection.json";
  pia-ca-cert = ./gluetun/ca.rsa.4096.crt;
  gluetun-web-benchmark-script = ./gluetun/web-benchmark.py;
  gluetun-web-benchmark-url = "https://speed.cloudflare.com/__down?bytes=8388608";
  gluetun-web-benchmark-total-bytes = 67108864;
  gluetun-web-benchmark-time-limit = 15;
  gluetun-preferred-region-name = "Vancouver";
  gluetun-top-server-count = 10;
  gluetun-switch-improvement-threshold = 0.20;
  gluetun-selection-script = pkgs.writeShellApplication {
    name = "gluetun-pia-selector";
    runtimeInputs = with pkgs; [
      bash
      coreutils
      curl
      gawk
      jq
      podman
      python3
      util-linux
      wireguard-tools
    ];
    text = ''
            set -euo pipefail

            if [ "$#" -ne 6 ]; then
              echo "Usage: gluetun-pia-selector <provisional|benchmark> <gluetun-secrets> <state-dir> <cache-file> <ca-cert> <benchmark-script>" >&2
              exit 1
            fi

            mode="$1"
            secrets_file="$2"
            state_dir="$3"
            cache_file="$4"
            ca_cert="$5"
            benchmark_script="$6"

            preferred_region_name='${gluetun-preferred-region-name}'
            top_server_count='${toString gluetun-top-server-count}'
            material_threshold='${toString gluetun-switch-improvement-threshold}'
            benchmark_url='${gluetun-web-benchmark-url}'
            benchmark_total_bytes='${toString gluetun-web-benchmark-total-bytes}'
            benchmark_time_limit='${toString gluetun-web-benchmark-time-limit}'
            gluetun_image='docker.io/qmcgaw/gluetun:latest'

            timestamp_utc() {
              date -u +%Y-%m-%dT%H:%M:%SZ
            }

            have_cache() {
              [ -s "$cache_file" ]
            }

            fail_or_keep_cache() {
              echo "$1" >&2
              if have_cache; then
                exit 0
              fi
              exit 1
            }

            load_env_file() {
              set -a
              # shellcheck disable=SC1090
              . "$1"
              set +a
            }

            tsv_to_json() {
              jq -Rnc '[inputs | select(length > 0) | split("	") | {
                latency_seconds: (.[0] | tonumber),
                region_id: .[1],
                region_name: .[2],
                country: .[3],
                meta_ip: .[4],
                wg_ip: .[5],
                wg_host: .[6]
              }]'
            }

            benchmark_candidate() {
              local latency_seconds="$1"
              local region_id="$2"
              local region_name="$3"
              local country="$4"
              local meta_ip="$5"
              local wg_ip="$6"
              local wg_host="$7"
              local private_key
              local public_key
              local addkey_json
              local peer_ip
              local server_key
              local server_port
              local env_file
              local container_name
              local status
              local pid
              local measurement_json

              private_key="$(${pkgs.wireguard-tools}/bin/wg genkey)"
              public_key="$(printf '%s' "$private_key" | ${pkgs.wireguard-tools}/bin/wg pubkey)"

              addkey_json="$(
                curl -4 -fsS             --connect-to "$wg_host::$wg_ip:"             --cacert "$ca_cert"             --get             --data-urlencode "pt=$token"             --data-urlencode "pubkey=$public_key"             --max-time 10             "https://$wg_host:1337/addKey" 2>/dev/null
              )" || return 1

              if [ "$(printf '%s' "$addkey_json" | jq -r '.status // empty')" != "OK" ]; then
                return 1
              fi

              peer_ip="$(printf '%s' "$addkey_json" | jq -r '.peer_ip // empty')"
              server_key="$(printf '%s' "$addkey_json" | jq -r '.server_key // empty')"
              server_port="$(printf '%s' "$addkey_json" | jq -r '.server_port // empty')"
              if [ -z "$peer_ip" ] || [ -z "$server_key" ] || [ -z "$server_port" ]; then
                return 1
              fi

              env_file="$tmp_dir/''${region_id}-candidate.env"
              printf '%s\n'                       "VPN_SERVICE_PROVIDER=custom"                       "VPN_TYPE=wireguard"                       "WIREGUARD_ENDPOINT_IP=$wg_ip"                       "WIREGUARD_ENDPOINT_PORT=$server_port"                       "WIREGUARD_PUBLIC_KEY=$server_key"                       "WIREGUARD_PRIVATE_KEY=$private_key"                       "WIREGUARD_ADDRESSES=$peer_ip"                       "SERVER_NAMES=$wg_host"                       "VPN_PORT_FORWARDING=off"                       "HTTPPROXY=off"                       "DOT=off"                       "TZ=UTC"                       > "$env_file"

              container_name="gluetun-bench-''${region_id//_/-}-$$-''${RANDOM}"
              ${pkgs.podman}/bin/podman rm -f "$container_name" >/dev/null 2>&1 || true
              if ! ${pkgs.podman}/bin/podman run -d           --pull=never           --name "$container_name"           --cap-add=NET_ADMIN           --device=/dev/net/tun:/dev/net/tun           --network=ghostship_net           --health-cmd '/gluetun-entrypoint healthcheck'           --health-interval=10s           --health-timeout=5s           --health-retries=12           --health-start-period=20s           --env-file "$env_file"           "$gluetun_image" >/dev/null; then
                ${pkgs.podman}/bin/podman rm -f "$container_name" >/dev/null 2>&1 || true
                return 1
              fi

              status=""
              for _ in $(seq 1 45); do
                status="$(${pkgs.podman}/bin/podman inspect --format '{{if .State.Healthcheck}}{{.State.Healthcheck.Status}}{{else}}{{.State.Status}}{{end}}' "$container_name" 2>/dev/null || true)"
                if [ "$status" = "healthy" ]; then
                  break
                fi
                if [ "$status" = "unhealthy" ] || [ "$status" = "exited" ]; then
                  break
                fi
                sleep 2
              done

              if [ "$status" != "healthy" ]; then
                ${pkgs.podman}/bin/podman rm -f "$container_name" >/dev/null 2>&1 || true
                return 1
              fi

              pid="$(${pkgs.podman}/bin/podman inspect --format '{{.State.Pid}}' "$container_name")"
              measurement_json="$(
                ${pkgs.util-linux}/bin/nsenter -t "$pid" -n             ${pkgs.python3}/bin/python3 "$benchmark_script"               --url "$benchmark_url"               --bytes-target "$benchmark_total_bytes"               --time-limit "$benchmark_time_limit" 2>/dev/null
              )" || {
                ${pkgs.podman}/bin/podman rm -f "$container_name" >/dev/null 2>&1 || true
                return 1
              }

              ${pkgs.podman}/bin/podman rm -f "$container_name" >/dev/null 2>&1 || true

              jq -cn           --argjson latency_seconds "$latency_seconds"           --arg region_id "$region_id"           --arg region_name "$region_name"           --arg country "$country"           --arg meta_ip "$meta_ip"           --arg wg_ip "$wg_ip"           --arg wg_host "$wg_host"           --argjson measurement "$measurement_json"           '{
                  source: "benchmark",
                  latency_seconds: $latency_seconds,
                  region_id: $region_id,
                  region_name: $region_name,
                  country: $country,
                  meta_ip: $meta_ip,
                  wg_ip: $wg_ip,
                  wg_host: $wg_host,
                  download_bytes_per_second: $measurement.bytes_per_second,
                  bytes_transferred: $measurement.bytes_transferred,
                  elapsed_seconds: $measurement.elapsed_seconds,
                  requests_attempted: $measurement.requests_attempted,
                  requests_completed: $measurement.requests_completed,
                  benchmark_url: $measurement.benchmark_url
                }'
            }

            if [ "$mode" != "provisional" ] && [ "$mode" != "benchmark" ]; then
              echo "Unknown selector mode: $mode" >&2
              exit 1
            fi

            if [ ! -f "$secrets_file" ]; then
              echo "Missing Gluetun secrets file at $secrets_file" >&2
              exit 1
            fi

            load_env_file "$secrets_file"
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
            if ! curl -fsSL https://serverlist.piaservers.net/vpninfo/servers/v6 | head -n 1 > "$serverlist"; then
              fail_or_keep_cache "Failed to fetch the current PIA server inventory"
            fi

            token="$(
              curl -fsSL --request POST           https://www.privateinternetaccess.com/api/client/v2/token           --form "username=$pia_user"           --form "password=$pia_pass"           | jq -r '.token // empty'
            )"
            if [ -z "$token" ]; then
              fail_or_keep_cache "Failed to obtain a PIA token for server selection"
            fi

            jq -r --arg preferred_region_name "$preferred_region_name" '
              .regions[]
              | select(.port_forward == true and (.name | contains($preferred_region_name)))
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
              fail_or_keep_cache "No port-forward-capable PIA WireGuard servers were available for $preferred_region_name"
            fi

            : > "$tmp_dir/latency.tsv"
            while IFS=$'	' read -r region_id region_name country meta_ip wg_ip wg_host; do
              [ -n "$region_id" ] || continue
              connect_time="$(
                curl -4 -o /dev/null -sS             --connect-timeout 1.5             --max-time 2             --write-out '%{time_connect}'             "http://$meta_ip:443" 2>/dev/null || true
              )"
              if [ -n "$connect_time" ]; then
                printf '%s	%s	%s	%s	%s	%s	%s
      '             "$connect_time" "$region_id" "$region_name" "$country" "$meta_ip" "$wg_ip" "$wg_host"             >> "$tmp_dir/latency.tsv"
              fi
            done < "$tmp_dir/candidates.tsv"
            if [ ! -s "$tmp_dir/latency.tsv" ]; then
              fail_or_keep_cache "No PF-capable PIA WireGuard endpoints responded to the latency screen"
            fi

            sort -n "$tmp_dir/latency.tsv" > "$tmp_dir/latency-sorted.tsv"
            head -n "$top_server_count" "$tmp_dir/latency-sorted.tsv" > "$tmp_dir/top-servers.tsv"
            if [ ! -s "$tmp_dir/top-servers.tsv" ]; then
              fail_or_keep_cache "Unable to retain any top Vancouver PIA WireGuard servers after latency screening"
            fi

            top_servers_json="$(tsv_to_json < "$tmp_dir/top-servers.tsv")"

            if [ "$mode" = "provisional" ]; then
              winner_json="$(printf '%s' "$top_servers_json" | jq -c '.[0] + {
                source: "latency",
                download_bytes_per_second: null,
                bytes_transferred: null,
                elapsed_seconds: null,
                requests_attempted: null,
                requests_completed: null,
                benchmark_url: null
              }')"
              fallbacks_json="$(printf '%s' "$top_servers_json" | jq -c --argjson limit "$top_server_count" '.[1:$limit] | map(. + {
                source: "latency",
                download_bytes_per_second: null,
                bytes_transferred: null,
                elapsed_seconds: null,
                requests_attempted: null,
                requests_completed: null,
                benchmark_url: null
              })')"
              jq -n           --arg selected_at "$(timestamp_utc)"           --arg selection_mode "provisional"           --arg selection_scope "vancouver"           --arg preferred_region_name "$preferred_region_name"           --argjson winner "$winner_json"           --argjson fallbacks "$fallbacks_json"           --argjson top_servers "$top_servers_json"           '{
                  selected_at: $selected_at,
                  last_benchmark_at: null,
                  selection_mode: $selection_mode,
                  selection_scope: $selection_scope,
                  preferred_region_name: $preferred_region_name,
                  winner: $winner,
                  fallbacks: $fallbacks,
                  top_servers: $top_servers,
                  benchmark: null
                }' > "$cache_file.tmp"
              mv "$cache_file.tmp" "$cache_file"
              chmod 600 "$cache_file"
              exit 0
            fi

            : > "$tmp_dir/bench.jsonl"
            while IFS=$'	' read -r latency_seconds region_id region_name country meta_ip wg_ip wg_host; do
              result_json="$(benchmark_candidate "$latency_seconds" "$region_id" "$region_name" "$country" "$meta_ip" "$wg_ip" "$wg_host" 2>/dev/null || true)"
              if [ -n "$result_json" ]; then
                printf '%s
      ' "$result_json" >> "$tmp_dir/bench.jsonl"
              fi
            done < "$tmp_dir/top-servers.tsv"
            if [ ! -s "$tmp_dir/bench.jsonl" ]; then
              fail_or_keep_cache "All top Vancouver generic web throughput probes failed"
            fi

            results_json="$(jq -sc 'sort_by(-.download_bytes_per_second, .latency_seconds)' "$tmp_dir/bench.jsonl")"
            challenger_json="$(printf '%s' "$results_json" | jq -c '.[0]')"
            challenger_host="$(printf '%s' "$challenger_json" | jq -r '.wg_host')"
            challenger_speed="$(printf '%s' "$challenger_json" | jq -r '.download_bytes_per_second')"
            now="$(timestamp_utc)"

            current_host=""
            current_speed="0"
            current_mode=""
            current_selected_at=""
            current_region_name=""
            current_winner_json='null'
            if have_cache; then
              current_host="$(jq -r '.winner.wg_host // empty' "$cache_file" 2>/dev/null || true)"
              current_speed="$(jq -r '.winner.download_bytes_per_second // .winner.usenet_bytes_per_second // 0' "$cache_file" 2>/dev/null || printf '0')"
              current_mode="$(jq -r '.selection_mode // empty' "$cache_file" 2>/dev/null || true)"
              current_selected_at="$(jq -r '.selected_at // empty' "$cache_file" 2>/dev/null || true)"
              current_region_name="$(jq -r '.winner.region_name // empty' "$cache_file" 2>/dev/null || true)"
              current_winner_json="$(jq -c '.winner // null' "$cache_file" 2>/dev/null || printf 'null')"
            fi

            switch_required=0
            if [ -z "$current_host" ]; then
              switch_required=1
            elif [ "$current_region_name" != "$preferred_region_name" ]; then
              switch_required=1
            elif [ "$challenger_host" = "$current_host" ]; then
              switch_required=0
            elif [ "$current_mode" = "provisional" ]; then
              switch_required=1
            elif awk "BEGIN { exit !($challenger_speed >= ($current_speed * (1 + $material_threshold))) }"; then
              switch_required=1
            fi

            if [ "$switch_required" -eq 1 ] || [ "$challenger_host" = "$current_host" ] || [ -z "$current_host" ]; then
              active_winner_json="$challenger_json"
              selected_at="$now"
              selection_mode="benchmark"
            else
              active_winner_json="$current_winner_json"
              selected_at="''${current_selected_at:-$now}"
              selection_mode="''${current_mode:-benchmark}"
            fi

            active_host="$(printf '%s' "$active_winner_json" | jq -r '.wg_host // empty')"
            fallbacks_json="$(jq -cn --arg active_host "$active_host" --argjson limit "$top_server_count" --argjson results "$results_json" '[$results[] | select(.wg_host != $active_host)][0:($limit - 1)]')"
            if [ "$switch_required" -eq 1 ]; then
              switched_json=true
            else
              switched_json=false
            fi
            benchmark_json="$(jq -cn         --arg last_run_at "$now"         --arg preferred_region_name "$preferred_region_name"         --arg benchmark_url "$benchmark_url"         --argjson benchmark_server_count "$top_server_count"         --argjson benchmark_total_bytes "$benchmark_total_bytes"         --argjson benchmark_time_limit "$benchmark_time_limit"         --argjson results "$results_json"         --argjson challenger "$challenger_json"         --argjson switched "$switched_json"         --argjson material_threshold "$material_threshold"         '{
                last_run_at: $last_run_at,
                preferred_region_name: $preferred_region_name,
                benchmark_url: $benchmark_url,
                benchmark_server_count: $benchmark_server_count,
                benchmark_total_bytes: $benchmark_total_bytes,
                benchmark_time_limit_seconds: $benchmark_time_limit,
                results: $results,
                challenger: $challenger,
                switched: $switched,
                material_improvement_threshold: $material_threshold
              }')"

            jq -n         --arg selected_at "$selected_at"         --arg last_benchmark_at "$now"         --arg selection_mode "$selection_mode"         --arg selection_scope "vancouver"         --arg preferred_region_name "$preferred_region_name"         --argjson winner "$active_winner_json"         --argjson fallbacks "$fallbacks_json"         --argjson top_servers "$top_servers_json"         --argjson benchmark "$benchmark_json"         '{
                selected_at: $selected_at,
                last_benchmark_at: $last_benchmark_at,
                selection_mode: $selection_mode,
                selection_scope: $selection_scope,
                preferred_region_name: $preferred_region_name,
                winner: $winner,
                fallbacks: $fallbacks,
                top_servers: $top_servers,
                benchmark: $benchmark
              }' > "$cache_file.tmp"
            mv "$cache_file.tmp" "$cache_file"
            chmod 600 "$cache_file"

            if [ "$switch_required" -eq 1 ] && systemctl is-active --quiet podman-gluetun.service; then
              systemctl restart podman-gluetun.service
            fi
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
            # shellcheck disable=SC1090
            . "$secrets_file"
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

            candidates_file="$(mktemp)"
            trap 'rm -f "$candidates_file"' EXIT
            jq -c '
              [.winner] + (.fallbacks // []) + (.top_servers // [])
              | map(select(.wg_ip != null and .wg_host != null))
              | unique_by(.wg_host)
              | .[]
            ' "$cache_file" > "$candidates_file"
            if [ ! -s "$candidates_file" ]; then
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

            selected_json=""
            wireguard_json=""
            while IFS= read -r candidate_json; do
              wg_ip="$(printf '%s' "$candidate_json" | jq -r '.wg_ip')"
              wg_host="$(printf '%s' "$candidate_json" | jq -r '.wg_host')"
              if [ -z "$wg_ip" ] || [ "$wg_ip" = "null" ] || [ -z "$wg_host" ] || [ "$wg_host" = "null" ]; then
                continue
              fi
              wireguard_json="$(
                curl -4 -fsSL \
                  --connect-timeout 10 \
                  --max-time 20 \
                  --connect-to "$wg_host::$wg_ip:" \
                  --cacert "$ca_cert" \
                  --get \
                  --data-urlencode "pt=$token" \
                  --data-urlencode "pubkey=$public_key" \
                  "https://$wg_host:1337/addKey" 2>/dev/null
              )" || {
                echo "PIA WireGuard bootstrap failed for $wg_host ($wg_ip); trying next cached endpoint." >&2
                continue
              }
              if [ "$(printf '%s' "$wireguard_json" | jq -r '.status // empty')" = "OK" ]; then
                selected_json="$candidate_json"
                break
              fi
              echo "PIA WireGuard bootstrap returned a non-OK status for $wg_host ($wg_ip); trying next cached endpoint." >&2
            done < "$candidates_file"

            if [ -z "$selected_json" ]; then
              echo "PIA WireGuard bootstrap failed for all cached Gluetun endpoints" >&2
              exit 1
            fi
            wg_ip="$(printf '%s' "$selected_json" | jq -r '.wg_ip')"
            wg_host="$(printf '%s' "$selected_json" | jq -r '.wg_host')"

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

            current_host="$(jq -r '.winner.wg_host // empty' "$cache_file" 2>/dev/null || true)"
            if [ "$current_host" != "$wg_host" ]; then
              echo "Updating cached Gluetun PIA winner from ''${current_host:-unknown} to $wg_host after bootstrap fallback."
              now="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
              jq \
                --arg selected_at "$now" \
                --argjson winner "$selected_json" \
                '.selected_at = $selected_at
                  | .selection_mode = "bootstrap-fallback"
                  | .winner = ($winner + {
                      source: "bootstrap-fallback",
                      download_bytes_per_second: null,
                      bytes_transferred: null,
                      elapsed_seconds: null,
                      requests_attempted: null,
                      requests_completed: null,
                      benchmark_url: null
                    })
                  | .fallbacks = (((.fallbacks // []) + (.top_servers // []))
                      | map(select(.wg_host != $winner.wg_host))
                      | unique_by(.wg_host))' \
                "$cache_file" > "$cache_file.tmp"
              mv "$cache_file.tmp" "$cache_file"
              chmod 600 "$cache_file"
            fi
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
    description = "Benchmark and refresh the preferred PIA WireGuard server for Gluetun";
    after = [
      "network-online.target"
    ];
    wants = [ "network-online.target" ];
    serviceConfig = {
      Type = "oneshot";
      ExecStart = "${gluetun-selection-script}/bin/gluetun-pia-selector benchmark ${gluetun-secrets} ${gluetun-state-dir} ${gluetun-selection-cache} ${pia-ca-cert} ${gluetun-web-benchmark-script}";
    };
  };

  systemd.timers.gluetun-pia-selector = {
    description = "Run the Gluetun PIA selector shortly after boot and every 8 hours";
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnBootSec = "5m";
      OnUnitActiveSec = "8h";
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

    if [ ! -s "${gluetun-selection-cache}" ] || ! ${pkgs.jq}/bin/jq -e --arg preferred_region_name "${gluetun-preferred-region-name}" '(.winner.region_name // "") | contains($preferred_region_name)' "${gluetun-selection-cache}" >/dev/null 2>&1; then
      ${gluetun-selection-script}/bin/gluetun-pia-selector provisional "${gluetun-secrets}" "${gluetun-state-dir}" "${gluetun-selection-cache}" "${pia-ca-cert}" "${gluetun-web-benchmark-script}"
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
        TUN_INTERFACE="tun0"

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
                systemctl restart podman-qbittorrent.service
              else
                echo "Gluetun IP initialized to $CURRENT_IP."
              fi
              LAST_IP="$CURRENT_IP"
            fi

            VPN_STATUS=$(${pkgs.podman}/bin/podman exec gluetun wget -qO- --header "X-API-Key: $API_KEY" http://127.0.0.1:8000/v1/vpn/status 2>/dev/null | ${pkgs.jq}/bin/jq -r .status 2>/dev/null || true)
            FORWARDED_PORT=$(${pkgs.podman}/bin/podman exec gluetun wget -qO- --header "X-API-Key: $API_KEY" http://127.0.0.1:8000/v1/portforward 2>/dev/null | ${pkgs.jq}/bin/jq -r .port 2>/dev/null || true)
            TUN_IP=$(${pkgs.podman}/bin/podman exec gluetun sh -c "ip -4 -o addr show dev $TUN_INTERFACE 2>/dev/null | tr -s ' ' | cut -d' ' -f4 | cut -d/ -f1 | head -n1" 2>/dev/null || true)

            if ${pkgs.podman}/bin/podman exec gluetun wget -qO- http://127.0.0.1:5000/api/v2/app/version >/dev/null 2>&1; then
              CURRENT_QBT_PREFS=$(${pkgs.podman}/bin/podman exec gluetun wget -qO- http://127.0.0.1:5000/api/v2/app/preferences 2>/dev/null || true)
              CURRENT_QBT_PORT=$(printf '%s' "$CURRENT_QBT_PREFS" | ${pkgs.jq}/bin/jq -r '.listen_port // empty' 2>/dev/null || true)
              CURRENT_QBT_INTERFACE=$(printf '%s' "$CURRENT_QBT_PREFS" | ${pkgs.jq}/bin/jq -r '.current_network_interface // empty' 2>/dev/null || true)
              CURRENT_QBT_ADDR=$(printf '%s' "$CURRENT_QBT_PREFS" | ${pkgs.jq}/bin/jq -r '.current_interface_address // empty' 2>/dev/null || true)
              CURRENT_QBT_EXTERNAL_IP=$(printf '%s' "$CURRENT_QBT_PREFS" | ${pkgs.jq}/bin/jq -r '.status_bar_external_ip // false' 2>/dev/null || true)

              if [ -n "$TUN_IP" ] && { [ "$CURRENT_QBT_INTERFACE" != "$TUN_INTERFACE" ] || [ "$CURRENT_QBT_ADDR" != "$TUN_IP" ] || [ "$CURRENT_QBT_EXTERNAL_IP" != "true" ]; }; then
                echo "qBittorrent interface binding drift detected (Interface: $CURRENT_QBT_INTERFACE, Address: $CURRENT_QBT_ADDR, External IP enabled: $CURRENT_QBT_EXTERNAL_IP). Reconciling to $TUN_INTERFACE/$TUN_IP."
                QBT_BIND_JSON=$(${pkgs.jq}/bin/jq -cn \
                  --arg interface "$TUN_INTERFACE" \
                  --arg address "$TUN_IP" \
                  '{"current_network_interface": $interface, "current_interface_address": $address, "status_bar_external_ip": true}')
                ${pkgs.podman}/bin/podman exec gluetun wget -qO- --post-data "json=$QBT_BIND_JSON" http://127.0.0.1:5000/api/v2/app/setPreferences >/dev/null 2>&1 || true
              fi

              if [ -n "$FORWARDED_PORT" ] && [ "$FORWARDED_PORT" != "null" ] && [ "$FORWARDED_PORT" != "0" ]; then
                PF_FAILURES=0
                if [ "$CURRENT_QBT_PORT" != "$FORWARDED_PORT" ] || [ "$CURRENT_QBT_INTERFACE" != "$TUN_INTERFACE" ] || [ "$CURRENT_QBT_ADDR" != "$TUN_IP" ]; then
                  echo "qBittorrent port or tunnel binding mismatch (Port: $CURRENT_QBT_PORT, Interface: $CURRENT_QBT_INTERFACE, Address: $CURRENT_QBT_ADDR). Updating to $FORWARDED_PORT on $TUN_INTERFACE/$TUN_IP."
                  QBT_PORT_JSON=$(${pkgs.jq}/bin/jq -cn \
                    --arg interface "$TUN_INTERFACE" \
                    --arg address "$TUN_IP" \
                    --arg port "$FORWARDED_PORT" \
                    '{"listen_port": ($port | tonumber), "current_network_interface": $interface, "current_interface_address": $address, "random_port": false, "upnp": false, "status_bar_external_ip": true}')
                  ${pkgs.podman}/bin/podman exec gluetun wget -qO- --post-data "json=$QBT_PORT_JSON" http://127.0.0.1:5000/api/v2/app/setPreferences >/dev/null 2>&1 || true
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
