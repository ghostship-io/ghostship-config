{ config
, lib
, pkgs
, ...
}:

let
  cfg = config.ghostship.emulation;
  emu = config.ghostship.emulation.internal.lib;

  controllerLeds = pkgs.writeShellScriptBin "controller-leds" ''
    set -euo pipefail
    export PATH=${emu.scriptPath}:$PATH
    state_dir="${cfg.configRoot}/controllers"
    order_file="$state_dir/player-order.json"
    last_state_file="$state_dir/led-state.tsv"
    log_file="${cfg.dataRoot}/logs/controller-leds.log"
    last_led_status=""
    mode="''${1:-loop}"
    led_write_delay="0.5"
    mkdir -p "$state_dir" "$(dirname "$log_file")"
    touch "$log_file"
    chown ${cfg.user}:${cfg.group} "$state_dir" "$log_file" || true
    exec 9>"$state_dir/controller-leds.lock"

    ensure_order_file() {
      if ! jq -e '.players | type == "array"' "$order_file" >/dev/null 2>&1; then
        printf '{"players":[]}\n' >"$order_file"
        chown ${cfg.user}:${cfg.group} "$order_file" || true
      fi
    }

    sanitize_known_bad_order() {
      ensure_order_file
      if jq -e '
          ([.players[]? | select(.mac | test("^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$"))] | length) == 0
          and ([.players[]? | select(.mac == "Controller")] | length) > 0
        ' "$order_file" >/dev/null 2>&1; then
        printf '{"players":[]}\n' >"$order_file"
        chown ${cfg.user}:${cfg.group} "$order_file" || true
        chmod 0644 "$order_file" || true
        echo "$(date -u +%FT%TZ) reset bogus controller order file" >>"$log_file"
      fi
    }

    bluez_device_rows() {
      timeout 3s busctl --system --json=short call org.bluez / org.freedesktop.DBus.ObjectManager GetManagedObjects 2>/dev/null \
        | jq -r '
            .data[0]
            | to_entries[]
            | select(.value["org.bluez.Device1"]?)
            | .value["org.bluez.Device1"]
            | [
                (.Address.data // ""),
                ((.Alias.data // .Name.data // "unknown-controller") | gsub("[\t\r\n]"; " ")),
                ((.Connected.data // false) | tostring),
                ((.Paired.data // .Bonded.data // false) | tostring),
                ((.Trusted.data // false) | tostring),
                ((.WakeAllowed.data // false) | tostring),
                ((.Modalias.data // "") | ascii_downcase),
                ((.Icon.data // "") | ascii_downcase)
              ]
            | @tsv
          '
    }

    player_identifier() {
      printf '%s\n' "''${1:-}" | grep -Eiq '^(([0-9a-f]{2}:){5}[0-9a-f]{2}|USB:[0-9a-f]{4}:[0-9a-f]{4}:.+)$'
    }

    led_identifier() {
      printf '%s\n' "''${1:-}" | grep -Eiq '^([0-9a-f]{2}:){5}[0-9a-f]{2}$'
    }

    usb_identifier_from_modalias() {
      modalias="''${1:-}"
      uniq="''${2:-unknown}"
      vendor="$(printf '%s\n' "$modalias" | sed -n 's/.*v\([0-9a-fA-F]\{4\}\)p\([0-9a-fA-F]\{4\}\).*/\1/p')"
      product="$(printf '%s\n' "$modalias" | sed -n 's/.*v\([0-9a-fA-F]\{4\}\)p\([0-9a-fA-F]\{4\}\).*/\2/p')"
      [ -n "$vendor" ] && [ -n "$product" ] || return 1
      stable="$(printf '%s' "$uniq" | tr -c '[:alnum:]_.:-' '_')"
      printf 'USB:%s:%s:%s\n' \
        "$(printf '%s' "$vendor" | tr '[:lower:]' '[:upper:]')" \
        "$(printf '%s' "$product" | tr '[:lower:]' '[:upper:]')" \
        "$stable"
    }

    controller_identifier() {
      uniq="''${1:-}"
      modalias="''${2:-}"
      if led_identifier "$uniq"; then
        printf '%s\n' "$(printf '%s' "$uniq" | tr '[:lower:]' '[:upper:]')"
        return 0
      fi
      usb_identifier_from_modalias "$modalias" "$uniq"
    }

    supported_player_device() {
      id="$1"
      name="''${2:-}"
      modalias="''${3:-}"
      icon="''${4:-}"
      text="$(printf '%s\n%s\n%s\n' "$name" "$modalias" "$icon" | tr '[:upper:]' '[:lower:]')"
      if printf '%s\n' "$text" | grep -Eiq 'audio|headphone|headset|speaker|keyboard|mouse|phone|television| tv|shield'; then
        return 1
      fi
      printf '%s\n' "$text" | grep -Eiq '(^|[^a-z])pro controller([^a-z]|$)|usb:v057ep2009|input:b0003v057ep2009|usb:v2dc8p301a|input:b0003v2dc8p301a|name: pro controller|alias: pro controller|nintendo switch pro|joy-con|joycon|8bitdo ultimate c 2'
    }

    local_switch_rows() {
      for event in /sys/class/input/event*; do
        [ -r "$event/device/name" ] || continue
        name="$(cat "$event/device/name" 2>/dev/null || true)"
        case "$name" in
          ""|*"IMU"*|*"imu"*) continue ;;
        esac
        uniq="$(cat "$event/device/uniq" 2>/dev/null || true)"
        modalias="$(cat "$event/device/modalias" 2>/dev/null | tr '[:upper:]' '[:lower:]' || true)"
        case "$modalias" in
          input:b0003*) ;;
          *) continue ;;
        esac
        id="$(controller_identifier "$uniq" "$modalias" || true)"
        [ -n "''${id:-}" ] || continue
        player_identifier "$id" || continue
        supported_player_device "$id" "$name" "$modalias" "input-gaming" || continue
        printf '%s\t%s\ttrue\tfalse\tfalse\tfalse\t%s\tinput-gaming\n' \
          "$id" \
          "$(printf '%s' "$name" | tr '\t\r\n' '   ')" \
          "$modalias"
      done | sort -u
    }

    prune_non_player_devices() {
      ensure_order_file
      before="$(jq -c '.players // []' "$order_file" 2>/dev/null || echo '[]')"
      tmp="$(mktemp)"
      jq '
        def player_id:
          (((.mac // "") | test("^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")) or
           ((.mac // "") | test("^USB:[0-9A-Fa-f]{4}:[0-9A-Fa-f]{4}:.+")));
        .players |= map(select(
          (.mac == "KEYBOARD") or
          (
            player_id and
            ((.name // "") | test("(?i)(pro controller|nintendo switch pro|joy-con|joycon|switch pro|8bitdo ultimate c 2)"))
          )
        ))
      ' "$order_file" >"$tmp"
      mv "$tmp" "$order_file"
      after="$(jq -c '.players // []' "$order_file" 2>/dev/null || echo '[]')"
      if [ "$before" != "$after" ]; then
        echo "$(date -u +%FT%TZ) pruned non-switch controller player entries" >>"$log_file"
      fi
    }

    compact_player_slots() {
      ensure_order_file
      before="$(jq -c '.players // []' "$order_file" 2>/dev/null || echo '[]')"
      tmp="$(mktemp)"
      if ! jq '
        def player_id:
          (((.mac // "") | test("^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")) or
           ((.mac // "") | test("^USB:[0-9A-Fa-f]{4}:[0-9A-Fa-f]{4}:.+")));
        def slot: (.player | tonumber? // 99);
        def pack($rows; $used):
          reduce ($rows[]) as $row
            ({players: [], used: $used};
              (.used) as $used_slots
              | ([1, 2, 3, 4] | map(select(. as $candidate | ($used_slots | index($candidate) | not))) | .[0]) as $next
              | if $next == null then
                  .players += [$row + {player: ((.used | length) + 1)}]
                else
                  .players += [$row + {player: $next}]
                  | .used += [$next]
                end
            );

        (.players // []) as $players
        | ($players | map(select((.mac // "") == "KEYBOARD"))) as $keyboard
        | ($keyboard | map(slot | select(. >= 1 and . <= 4))) as $reserved
        | ($players | map(select(((.mac // "") != "KEYBOARD") and player_id and (.connected == true))) | sort_by(slot)) as $connected
        | ($players | map(select(((.mac // "") != "KEYBOARD") and player_id and (.connected != true))) | sort_by(slot)) as $disconnected
        | (pack($connected; $reserved)) as $active
        | (pack($disconnected; $active.used)) as $inactive
        | .players = (($keyboard | sort_by(slot)) + $active.players + $inactive.players | sort_by(slot))
      ' "$order_file" >"$tmp"; then
        rm -f "$tmp"
        echo "$(date -u +%FT%TZ) failed to compact controller player slots" >>"$log_file"
        return 1
      fi
      mv "$tmp" "$order_file"
      after="$(jq -c '.players // []' "$order_file" 2>/dev/null || echo '[]')"
      if [ "$before" != "$after" ]; then
        echo "$(date -u +%FT%TZ) compacted connected controller player slots" >>"$log_file"
      fi
    }

    record_connected_devices() {
      ensure_order_file
      prune_non_player_devices
      connected_tmp="$(mktemp)"
      : >"$connected_tmp"
      if ! bluez_device_rows >>"$connected_tmp"; then
        echo "$(date -u +%FT%TZ) skipped controller order reconcile because BlueZ device query timed out" >>"$log_file"
      fi
      local_switch_rows >>"$connected_tmp" || true

      tmp="$(mktemp)"
      jq '.players |= map(if (((.mac // "") | test("^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")) or ((.mac // "") | test("^USB:[0-9A-Fa-f]{4}:[0-9A-Fa-f]{4}:.+"))) then . + {connected:false} else . end)' "$order_file" >"$tmp"
      mv "$tmp" "$order_file"

      while IFS=$'\t' read -r mac name connected _paired _trusted _wake modalias icon; do
        [ -n "''${mac:-}" ] || continue
        [ "''${connected:-false}" = true ] || continue
        if ! player_identifier "$mac"; then
          continue
        fi
        name="''${name:-unknown-controller}"
        supported_player_device "$mac" "$name" "$modalias" "$icon" || continue
        mac_upper="$(printf '%s' "$mac" | tr '[:lower:]' '[:upper:]')"
        tmp="$(mktemp)"
        if jq -e --arg mac "$mac_upper" '.players[]? | select(((.mac // "") | ascii_upcase) == $mac)' "$order_file" >/dev/null; then
          jq --arg mac "$mac_upper" --arg name "$name" \
            '.players |= map(if ((.mac // "") | ascii_upcase) == $mac then . + {mac:$mac, name:$name, connected:true} else . end)' \
            "$order_file" >"$tmp"
        else
          jq --arg mac "$mac_upper" --arg name "$name" \
            '([.players[]?.player] as $used
              | ([1, 2, 3, 4] | map(select(. as $slot | ($used | index($slot) | not))) | .[0])) as $next
             | if $next == null then .players += [{player:((.players | length) + 1), mac:$mac, name:$name, connected:true}] else .players += [{player:$next, mac:$mac, name:$name, connected:true}] end' \
            "$order_file" >"$tmp"
        fi
        mv "$tmp" "$order_file"
      done <"$connected_tmp"
      rm -f "$connected_tmp"

      tmp="$(mktemp)"
      jq '.players |= map(select((((.mac // "") | test("^USB:[0-9A-Fa-f]{4}:[0-9A-Fa-f]{4}:.+")) | not) or (.connected == true)))' "$order_file" >"$tmp"
      mv "$tmp" "$order_file"

      compact_player_slots

      tmp="$(mktemp)"
      jq '.players |= sort_by(.player)' "$order_file" >"$tmp"
      mv "$tmp" "$order_file"
      chown ${cfg.user}:${cfg.group} "$order_file" || true
      chmod 0644 "$order_file" || true
    }

    desired_led_rows() {
      jq -r '
        .players[]?
        | select(.connected == true)
        | select(((.player | tonumber? // 0) >= 1) and ((.player | tonumber? // 0) <= 4))
        | select((.mac // "") | test("^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$"))
        | [.player, ((.mac // "") | ascii_upcase)]
        | @tsv
      ' "$order_file" 2>/dev/null || true
    }

    desired_led_state() {
      desired_led_rows | sort
    }

    find_device_root() {
      mac="$1"
      max_attempts="''${2:-1}"
      delay="''${3:-0}"
      mac_upper="$(printf '%s' "$mac" | tr '[:lower:]' '[:upper:]')"
      attempt=1
      while [ "$attempt" -le "$max_attempts" ]; do
        for event in /sys/class/input/event*; do
          [ -r "$event/device/uniq" ] || continue
          uniq="$(tr '[:lower:]' '[:upper:]' <"$event/device/uniq" 2>/dev/null || true)"
          [ "$uniq" = "$mac_upper" ] || continue
          input_path="$(readlink -f "$event/device" 2>/dev/null || true)"
          [ -n "$input_path" ] || continue
          dirname "$(dirname "$input_path")"
          return 0
        done
        attempt=$((attempt + 1))
        if [ "$attempt" -le "$max_attempts" ]; then
          sleep "$delay"
        fi
      done
      return 1
    }

    apply_leds() {
      force="''${1:-false}"
      found=0
      changed=0
      pending_leds="$(mktemp)"
      while IFS=$'\t' read -r player mac; do
        [ -n "''${player:-}" ] || continue
        root_attempts=1
        root_delay=0
        if [ "$force" = true ]; then
          root_attempts=20
          root_delay=0.1
        fi
        device_root="$(find_device_root "$mac" "$root_attempts" "$root_delay" || true)"
        [ -n "''${device_root:-}" ] || continue
        for led in "$device_root"/leds/*:green:player-[1-4]; do
          [ -e "$led/brightness" ] || continue
          led_name="$(basename "$led")"
          led_index="''${led_name##*:green:player-}"
          case "$led_index" in
            [1-4])
              found=1
              if [ "$led_index" -le "$player" ]; then
                desired=1
              else
                desired=0
              fi
              current="$(cat "$led/brightness" 2>/dev/null || echo unknown)"
              if [ "$current" != "$desired" ]; then
                printf '%s\t%s\n' "$desired" "$led/brightness" >>"$pending_leds"
                changed=1
              fi
              ;;
          esac
        done
      done < <(desired_led_rows)

      while IFS=$'\t' read -r value path; do
        [ -n "''${path:-}" ] || continue
        [ -e "$path" ] || continue
        if ! timeout -k 1s 0.7s sh -c 'printf "%s\n" "$1" > "$2"' sh "$value" "$path" 2>/dev/null; then
          echo "$(date -u +%FT%TZ) skipped slow controller LED write: $path" >>"$log_file"
        fi
        sleep "$led_write_delay"
      done <"$pending_leds"
      rm -f "$pending_leds"

      if [ "$found" = 0 ]; then
        status="no supported controller LED sysfs entries found"
      elif [ "$changed" = 0 ]; then
        status="controller LED entries already match player order"
      else
        status="updated controller LED entries"
      fi
      if [ "$status" != "$last_led_status" ]; then
        echo "$(date -u +%FT%TZ) $status" >>"$log_file"
        last_led_status="$status"
      fi
    }

    run_once() {
      if ! flock -w 10 9; then
        echo "$(date -u +%FT%TZ) skipped controller LED apply because another reconciliation is active" >>"$log_file"
        return 0
      fi
      sanitize_known_bad_order
      if record_connected_devices; then
        apply_leds true || true
        state="$(desired_led_state || true)"
        printf '%s\n' "$state" >"$last_state_file"
        chown ${cfg.user}:${cfg.group} "$last_state_file" || true
      fi
      flock -u 9
    }

    case "$mode" in
      apply|once|--once)
        run_once
        exit 0
        ;;
      loop)
        ;;
      *)
        echo "Usage: controller-leds [loop|apply]" >&2
        exit 64
        ;;
    esac

    while true; do
      if flock -w 10 9; then
        sanitize_known_bad_order
        if record_connected_devices; then
          state="$(desired_led_state || true)"
          previous="$(cat "$last_state_file" 2>/dev/null || true)"
          if [ "$state" != "$previous" ]; then
            apply_leds false || true
            printf '%s\n' "$state" >"$last_state_file"
            chown ${cfg.user}:${cfg.group} "$last_state_file" || true
          fi
        fi
        flock -u 9
      else
        echo "$(date -u +%FT%TZ) skipped controller LED loop because another reconciliation is active" >>"$log_file"
      fi
      sleep 5
    done
  '';

  controllerBluetoothLowLatency = pkgs.writeShellScriptBin "controller-bluetooth-low-latency" ''
    set -euo pipefail
    export PATH=${emu.scriptPath}:${lib.makeBinPath [ pkgs.bluez pkgs.coreutils pkgs.gnugrep pkgs.gnused pkgs.jq pkgs.systemd ]}:$PATH
    log_file="${cfg.dataRoot}/logs/controller-bluetooth-latency.log"
    mkdir -p "$(dirname "$log_file")"
    touch "$log_file"

    log() {
      echo "$(date -u +%FT%TZ) $*" >>"$log_file"
    }

    switch_pro_macs() {
      timeout 3s busctl --system --json=short call org.bluez / org.freedesktop.DBus.ObjectManager GetManagedObjects 2>/dev/null \
        | jq -r '
            .data[0]
            | to_entries[]
            | select(.value["org.bluez.Device1"]?)
            | .value["org.bluez.Device1"]
            | [
                (.Address.data // ""),
                ((.Alias.data // .Name.data // "Switch Pro Controller") | gsub("[\t\r\n]"; " ")),
                ((.Connected.data // false) | tostring),
                ((.Modalias.data // "") | ascii_downcase),
                ((.Icon.data // "") | ascii_downcase)
              ]
            | select((.[2] == "true") and (((.[3] | test("v057ep2009|v2dc8p(310b|301a)")) or (.[1] | ascii_downcase | test("(^pro controller$|nintendo switch pro|8bitdo|ultimate 2c)")))))
            | .[0]
          '
    }

    if hciconfig hci0 >/dev/null 2>&1; then
      adapter_policy="$(hciconfig -a hci0 2>/dev/null | sed -n 's/^[[:space:]]*Link policy: //p' | head -1 || true)"
      if printf '%s\n' "$adapter_policy" | grep -q SNIFF; then
        if hciconfig hci0 lp rswitch >/dev/null 2>&1; then
          log "set hci0 link policy to RSWITCH"
        else
          log "failed to set hci0 link policy"
        fi
      fi
    fi

    macs_tmp="$(mktemp)"
    if ! switch_pro_macs >"$macs_tmp"; then
      log "skipped controller link-policy tuning because BlueZ device query timed out"
      rm -f "$macs_tmp"
      exit 0
    fi

    while IFS= read -r mac; do
      [ -n "''${mac:-}" ] || continue
      current="$(hcitool lp "$mac" 2>/dev/null || true)"
      if printf '%s\n' "$current" | grep -q SNIFF; then
        if hcitool lp "$mac" rswitch >/dev/null 2>&1; then
          log "disabled SNIFF link policy for $mac"
        else
          log "failed to disable SNIFF link policy for $mac"
        fi
      fi
    done <"$macs_tmp"
    rm -f "$macs_tmp"
  '';

  controllerAutoconnect = pkgs.writeShellScriptBin "controller-autoconnect" ''
    set -euo pipefail
    export PATH=${emu.scriptPath}:$PATH
    log_file="${cfg.dataRoot}/logs/controller-autoconnect.log"
    cursor_file="${cfg.dataRoot}/config/controllers/autoconnect-cursor"
    mkdir -p "$(dirname "$log_file")"
    mkdir -p "$(dirname "$cursor_file")"
    touch "$log_file"

    log() {
      echo "$(date -u +%FT%TZ) $*" >>"$log_file"
    }

    bluez_switch_pro_rows() {
      timeout 3s busctl --system --json=short call org.bluez / org.freedesktop.DBus.ObjectManager GetManagedObjects 2>/dev/null \
        | jq -r '
            .data[0]
            | to_entries[]
            | select(.value["org.bluez.Device1"]?)
            | .value["org.bluez.Device1"]
            | [
                (.Address.data // ""),
                ((.Alias.data // .Name.data // "Switch Pro Controller") | gsub("[\t\r\n]"; " ")),
                ((.Connected.data // false) | tostring),
                ((.Paired.data // .Bonded.data // false) | tostring),
                ((.Modalias.data // "") | ascii_downcase),
                ((.Icon.data // "") | ascii_downcase)
              ]
            | select((.[3] == "true") and (((.[4] | test("v057ep2009|v2dc8p(310b|301a)")) or (.[1] | ascii_downcase | test("(^pro controller$|nintendo switch pro|8bitdo|ultimate 2c)")))))
            | @tsv
          '
    }

    connected_device() {
      [ "''${1:-false}" = true ]
    }

    connect_once() {
      manage_pairing="''${1:-false}"
      attempt_limit="''${2:-0}"
      duration="''${3:-0}"
      did_connect=0
      deadline=0
      if [ "$duration" -gt 0 ]; then
        deadline=$(( $(date +%s) + duration ))
      fi
      while true; do
      rows_tmp="$(mktemp)"
      if ! bluez_switch_pro_rows >"$rows_tmp"; then
        log "skipped autoconnect because BlueZ device query timed out"
        rm -f "$rows_tmp"
        return 0
      fi
      mapfile -t rows <"$rows_tmp"
      rm -f "$rows_tmp"
      total="''${#rows[@]}"
      if [ "$total" -eq 0 ]; then
        [ "$duration" -gt 0 ] || return 0
        [ "$(date +%s)" -lt "$deadline" ] || break
        timeout 2s bluetoothctl scan on >/dev/null 2>&1 || true
        sleep 1
        continue
      fi

      start=0
      if [ "$attempt_limit" -gt 0 ]; then
        start="$(cat "$cursor_file" 2>/dev/null || echo 0)"
        case "$start" in
          *[!0-9]*|"") start=0 ;;
        esac
        start=$((start % total))
      fi

      for offset in $(seq 0 $((total - 1))); do
        idx=$(((start + offset) % total))
        IFS=$'\t' read -r mac name connected _paired _modalias _icon <<<"''${rows[$idx]}"
        [ -n "''${mac:-}" ] || continue
        if connected_device "$connected"; then
          continue
        fi
        if timeout 3s bluetoothctl info "$mac" 2>/dev/null | grep -q 'Connected: yes'; then
          continue
        fi
        log "connecting ''${name:-Switch Pro Controller} ($mac)"
        if [ "$manage_pairing" = true ]; then
          timeout 5s bluetoothctl trust "$mac" >/dev/null 2>&1 || true
          timeout 5s bluetoothctl wake "$mac" on >/dev/null 2>&1 || true
        fi
        if timeout 6s bluetoothctl connect "$mac" >>"$log_file" 2>&1; then
          log "connected ''${name:-Switch Pro Controller} ($mac)"
          did_connect=1
        else
          log "connect failed ''${name:-Switch Pro Controller} ($mac)"
        fi
        if [ "$attempt_limit" -gt 0 ]; then
          echo $(((idx + 1) % total)) >"$cursor_file"
          break
        fi
        sleep 1
      done
      [ "$duration" -gt 0 ] || break
      [ "$(date +%s)" -lt "$deadline" ] || break
      sleep 1
      done
      if [ "$did_connect" = 1 ]; then
        ${lib.getExe controllerBluetoothLowLatency} || true
        ${lib.getExe controllerLeds} apply || true
      fi
    }

    case "''${1:-loop}" in
      once|--once)
        connect_once true 0 "''${2:-0}"
        ;;
      loop)
        while true; do
          connect_once false 1
          sleep 60
        done
        ;;
      *)
        echo "Usage: controller-autoconnect [loop|once]" >&2
        exit 64
        ;;
    esac
  '';

  controllerUsbPair = pkgs.writeShellScriptBin "controller-usb-pair" ''
    set -euo pipefail
    export PATH=${emu.scriptPath}:$PATH
    log_file="${cfg.dataRoot}/logs/controller-usb-pair.log"
    mkdir -p "$(dirname "$log_file")"
    {
      echo "$(date -u +%FT%TZ) USB-assisted Switch Pro pairing/connect refresh"
      timeout 5s bluetoothctl power on || true
      timeout 5s bluetoothctl agent KeyboardDisplay || true
      timeout 5s bluetoothctl default-agent || true
      timeout 5s bluetoothctl pairable on || true
      ${lib.getExe controllerAutoconnect} once 10 || true
      ${lib.getExe controllerLeds} apply || true
    } >>"$log_file" 2>&1
  '';

  controllerReconcileEvents = pkgs.writeShellScriptBin "controller-reconcile-events" ''
    set -euo pipefail
    export PATH=${emu.scriptPath}:${lib.makeBinPath [ pkgs.dbus pkgs.systemd ]}:$PATH
    state_dir="${cfg.configRoot}/controllers"
    trigger_file="$state_dir/reconcile-event"
    worker_lock="$state_dir/reconcile-event.lock"
    log_file="${cfg.dataRoot}/logs/controller-reconcile-events.log"
    mkdir -p "$state_dir" "$(dirname "$log_file")"
    touch "$log_file"

    trigger_reconcile() {
      reason="$1"
      echo "$(date -u +%FT%TZ) bluez connected change: $reason" >>"$log_file"
      date +%s%N >"$trigger_file"
      (
        exec 8>"$worker_lock"
        flock -n 8 || exit 0
        while true; do
          token="$(cat "$trigger_file" 2>/dev/null || true)"
          sleep 1
          latest="$(cat "$trigger_file" 2>/dev/null || true)"
          [ "$token" = "$latest" ] && break
        done
        systemctl start --no-block controller-bluetooth-low-latency.service >/dev/null 2>&1 || true
        systemctl start --no-block controller-leds-apply.service >/dev/null 2>&1 || true
      ) &
    }

    in_device=0
    saw_connected=0
    dbus-monitor --system "type='signal',sender='org.bluez',interface='org.freedesktop.DBus.Properties',member='PropertiesChanged',arg0='org.bluez.Device1'" 2>>"$log_file" \
      | while IFS= read -r line; do
          case "$line" in
            *"member=PropertiesChanged"*)
              in_device=0
              saw_connected=0
              ;;
            *'string "org.bluez.Device1"'*)
              in_device=1
              ;;
            *'string "Connected"'*)
              if [ "$in_device" = 1 ]; then
                saw_connected=1
              fi
              ;;
            *"boolean true"*)
              if [ "$in_device" = 1 ] && [ "$saw_connected" = 1 ]; then
                trigger_reconcile connected
                saw_connected=0
              fi
              ;;
            *"boolean false"*)
              if [ "$in_device" = 1 ] && [ "$saw_connected" = 1 ]; then
                trigger_reconcile disconnected
                saw_connected=0
              fi
              ;;
          esac
        done
  '';

  controllerBluetoothHealth = pkgs.writeShellScriptBin "controller-bluetooth-health" ''
    set -euo pipefail
    export PATH=${emu.scriptPath}:$PATH
    log_file="${cfg.dataRoot}/logs/controller-bluetooth-health.log"
    mkdir -p "$(dirname "$log_file")"
    touch "$log_file"

    map_hid_roots() {
      for event in /sys/class/input/event*; do
        [ -r "$event/device/name" ] || continue
        name="$(cat "$event/device/name" 2>/dev/null || true)"
        case "$name" in
          *"IMU"*|*"imu"*)
            continue
            ;;
          *"Pro Controller"*)
            uniq="$(cat "$event/device/uniq" 2>/dev/null | tr '[:lower:]' '[:upper:]' || true)"
            input_path="$(readlink -f "$event/device" 2>/dev/null || true)"
            [ -n "$input_path" ] || continue
            root="$(basename "$(dirname "$(dirname "$input_path")")")"
            printf '%s=%s %s\n' "$root" "$uniq" "$name"
            ;;
        esac
      done | sort -u
    }

    while true; do
      warnings="$(journalctl -k --since '60 seconds ago' --no-pager 2>/dev/null | grep -Ec 'nintendo .*timeout waiting|joycon_enforce_subcmd_rate|compensating for .* dropped IMU reports' || true)"
      if [ "''${warnings:-0}" -gt 0 ]; then
        {
          printf '%s recent_hid_warnings=%s\n' "$(date -u +%FT%TZ)" "$warnings"
          map_hid_roots | sed 's/^/  /'
        } >>"$log_file"
      fi
      sleep 60
    done
  '';

  controllerBluetoothDiagnostics = pkgs.writeShellScriptBin "controller-bluetooth-diagnostics" ''
    set -euo pipefail
    export PATH=${emu.scriptPath}:$PATH
    seconds="''${1:-20}"
    case "$seconds" in
      *[!0-9]*|"") seconds=20 ;;
    esac
    out_dir="${cfg.dataRoot}/logs/bluetooth-diagnostics/$(date -u +%Y%m%dT%H%M%SZ)"
    mkdir -p "$out_dir"
    {
      date -u +%FT%TZ
      echo "== btmgmt info =="
      timeout 5s btmgmt info || true
      echo
      echo "== btmgmt expinfo =="
      timeout 5s btmgmt expinfo || true
      echo
      echo "== btmgmt connections =="
      timeout 5s btmgmt con || true
      echo
      echo "== paired devices =="
      timeout 5s bluetoothctl devices Paired || true
      echo
      echo "== connected devices =="
      timeout 5s bluetoothctl devices Connected || true
      echo
      echo "== controller link policy =="
      timeout 5s hciconfig -a hci0 2>/dev/null | grep -E 'Link policy|Link mode' || true
      timeout 5s bluetoothctl devices Connected 2>/dev/null \
        | awk '/Pro Controller/ {print $2}' \
        | while read -r mac; do
            [ -n "$mac" ] || continue
            printf '%s ' "$mac"
            timeout 3s hcitool lp "$mac" 2>/dev/null || true
          done
      echo
      echo "== controller player order =="
      cat "${cfg.configRoot}/controllers/player-order.json" 2>/dev/null || true
      echo
      echo "== recent kernel bluetooth/hid log =="
      journalctl -k --since '10 minutes ago' --no-pager | grep -Ei 'Bluetooth|btusb|btmtk|nintendo|hid' || true
    } >"$out_dir/summary.txt"
    timeout "$seconds" btmon -T -w "$out_dir/hci.btsnoop" >/dev/null 2>&1 || true
    printf '%s\n' "$out_dir"
  '';
in
{
  config = lib.mkIf cfg.enable {
    ghostship.emulation.internal.scripts.controllerLeds = controllerLeds;
    ghostship.emulation.internal.scripts.controllerAutoconnect = controllerAutoconnect;
    ghostship.emulation.internal.scripts.controllerUsbPair = controllerUsbPair;
    ghostship.emulation.internal.scripts.controllerBluetoothLowLatency = controllerBluetoothLowLatency;
    ghostship.emulation.internal.scripts.controllerBluetoothHealth = controllerBluetoothHealth;
    ghostship.emulation.internal.scripts.controllerBluetoothDiagnostics = controllerBluetoothDiagnostics;

    boot.kernelModules = [ "hid-nintendo" ];
    boot.extraModprobeConfig = ''
      options btusb enable_autosuspend=n
      options mt7921e disable_aspm=Y
    '';

    hardware.bluetooth = {
      enable = true;
      powerOnBoot = true;
      disabledPlugins = [
        "bap"
        "csip"
      ];
      settings = {
        General = {
          Experimental = true;
          FastConnectable = true;
          ControllerMode = "bredr";
          JustWorksRepairing = "always";
          Privacy = "off";
        };
        Policy = {
          AutoEnable = true;
        };
      };
      input = {
        General = {
          IdleTimeout = 0;
          UserspaceHID = true;
          ClassicBondedOnly = true;
        };
      };
    };

    networking.networkmanager.wifi.powersave = false;

    services.udev.extraRules = ''
      # 8BitDo Ultimate 2C Bluetooth and Nintendo Switch Pro mode controller identities.
      SUBSYSTEM=="usb", ATTR{idVendor}=="2dc8", ATTR{idProduct}=="310b", TEST=="power/control", ATTR{power/control}="on"
      SUBSYSTEM=="usb", ATTR{idVendor}=="2dc8", ATTR{idProduct}=="301a", TEST=="power/control", ATTR{power/control}="on"
      SUBSYSTEM=="usb", ATTR{idVendor}=="057e", ATTR{idProduct}=="2009", TEST=="power/control", ATTR{power/control}="on"
      ACTION=="add", SUBSYSTEM=="usb", ATTR{idVendor}=="2dc8", ATTR{idProduct}=="310b", TAG+="systemd", ENV{SYSTEMD_WANTS}+="controller-usb-pair.service"
      ACTION=="add", SUBSYSTEM=="usb", ATTR{idVendor}=="2dc8", ATTR{idProduct}=="301a", TAG+="systemd", ENV{SYSTEMD_WANTS}+="controller-usb-pair.service"
      ACTION=="add", SUBSYSTEM=="usb", ATTR{idVendor}=="057e", ATTR{idProduct}=="2009", TAG+="systemd", ENV{SYSTEMD_WANTS}+="controller-usb-pair.service"
      KERNEL=="hidraw*", ATTRS{idVendor}=="2dc8", ATTRS{idProduct}=="310b", MODE="0660", GROUP="input", TAG+="uaccess"
      KERNEL=="hidraw*", ATTRS{idVendor}=="2dc8", ATTRS{idProduct}=="301a", MODE="0660", GROUP="input", TAG+="uaccess"
      KERNEL=="hidraw*", ATTRS{idVendor}=="057e", ATTRS{idProduct}=="2009", MODE="0660", GROUP="input", TAG+="uaccess"
      ACTION=="add", SUBSYSTEM=="input", KERNEL=="event*", ATTRS{name}=="Pro Controller", TAG+="systemd", ENV{SYSTEMD_WANTS}+="controller-bluetooth-low-latency.service"
      ACTION=="add", SUBSYSTEM=="input", KERNEL=="event*", ATTRS{name}=="Pro Controller", TAG+="systemd", ENV{SYSTEMD_WANTS}+="controller-leds-apply.service"
      ACTION=="add", SUBSYSTEM=="input", KERNEL=="event*", ATTRS{name}=="Nintendo.Co.Ltd. Pro Controller", TAG+="systemd", ENV{SYSTEMD_WANTS}+="controller-leds-apply.service"
    '';

    systemd.services.wifi-5ghz-only = {
      description = "Keep Wi-Fi profiles constrained to 5 GHz for Bluetooth-focused emulation";
      wantedBy = [ "multi-user.target" ];
      after = [ "NetworkManager.service" ];
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
      };
      path = [
        pkgs.networkmanager
        pkgs.util-linux
        pkgs.gawk
        pkgs.jq
      ];
      script = ''
        log() {
          echo "wifi-5ghz-only: $*"
        }

        policy_file="${cfg.configRoot}/network/wifi-policy.json"
        allow_24ghz=false
        if [ -r "$policy_file" ]; then
          allow_24ghz="$(jq -r '.allow_24ghz // false' "$policy_file" 2>/dev/null || echo false)"
        fi

        rfkill unblock wlan || true
        for attempt in $(seq 1 30); do
          if nmcli -t -f RUNNING general 2>/dev/null | grep -qx running; then
            break
          fi
          log "waiting for NetworkManager ($attempt/30)"
          sleep 1
        done

        nmcli networking on || true
        nmcli radio wifi on || true

        for attempt in $(seq 1 30); do
          if nmcli -t -f DEVICE,TYPE device status 2>/dev/null | awk -F: '$2 == "wifi" { found=1 } END { exit found ? 0 : 1 }'; then
            break
          fi
          log "waiting for Wi-Fi device ($attempt/30)"
          sleep 1
        done

        if [ "$allow_24ghz" = true ]; then
          wifi_band=""
          log "2.4 GHz Wi-Fi is allowed by runtime policy"
        else
          wifi_band="a"
          log "constraining Wi-Fi profiles to 5 GHz"
        fi

        nmcli -t -f UUID,TYPE connection show | while IFS=: read -r uuid type; do
          [ "$type" = "802-11-wireless" ] || continue
          nmcli connection modify "$uuid" \
            connection.interface-name "" \
            802-11-wireless.band "$wifi_band" \
            connection.autoconnect yes \
            connection.autoconnect-priority 100 || true
        done

        wifi_active() {
          nmcli -t -f TYPE connection show --active 2>/dev/null | grep -qx "802-11-wireless"
        }

        wait_for_wifi_active() {
          max="''${1:-30}"
          for attempt in $(seq 1 "$max"); do
            if wifi_active; then
              return 0
            fi
            sleep 1
          done
          return 1
        }

        if ! wifi_active; then
          log "no active Wi-Fi connection; trying saved 5 GHz profiles"
          while IFS=: read -r uuid type; do
            [ "$type" = "802-11-wireless" ] || continue
            tmp="$(mktemp)"
            nmcli --wait 5 connection up uuid "$uuid" >"$tmp" 2>&1 || true
            if wait_for_wifi_active 25; then
              rm -f "$tmp"
              break
            fi
            sed 's/^/wifi-5ghz-only: nmcli: /' "$tmp" || true
            rm -f "$tmp"
          done < <(nmcli -t -f UUID,TYPE connection show)
        fi

        if ! wifi_active; then
          log "no active Wi-Fi connection after saved profile attempts"
        fi

        nmcli -t -f NAME,TYPE,DEVICE connection show --active || true
      '';
    };

    systemd.services.controller-leds = {
      description = "Maintain controller player order and LED state";
      wantedBy = [ "multi-user.target" ];
      after = [
        "bluetooth.service"
        "emulation-setup.service"
        "controller-bluetooth-tuning.service"
      ];
      serviceConfig = {
        ExecStart = "${lib.getExe controllerLeds}";
        Restart = "always";
        RestartSec = "5s";
        TimeoutStopSec = "5s";
      };
    };

    systemd.services.controller-leds-apply = {
      description = "Apply controller player LED state once";
      after = [
        "bluetooth.service"
        "emulation-setup.service"
        "controller-bluetooth-tuning.service"
      ];
      unitConfig.StartLimitIntervalSec = 0;
      serviceConfig = {
        Type = "oneshot";
        ExecStart = "${lib.getExe controllerLeds} apply";
        TimeoutStartSec = "30s";
      };
    };

    systemd.services.controller-autoconnect = {
      description = "Automatically reconnect paired Switch Pro controllers";
      wantedBy = [ "multi-user.target" ];
      after = [
        "bluetooth.service"
        "emulation-setup.service"
      ];
      serviceConfig = {
        ExecStart = "${lib.getExe controllerAutoconnect}";
        Restart = "always";
        RestartSec = "5s";
        TimeoutStopSec = "5s";
      };
    };

    systemd.services.controller-usb-pair = {
      description = "Attempt USB-assisted Switch Pro Bluetooth pairing refresh";
      after = [
        "bluetooth.service"
        "emulation-setup.service"
      ];
      unitConfig.StartLimitIntervalSec = 0;
      serviceConfig = {
        Type = "oneshot";
        ExecStart = "${lib.getExe controllerUsbPair}";
        TimeoutStartSec = "20s";
      };
    };

    systemd.services.controller-reconcile-events = {
      description = "Trigger controller player reconciliation from BlueZ events";
      wantedBy = [ "multi-user.target" ];
      after = [
        "bluetooth.service"
        "controller-leds.service"
      ];
      serviceConfig = {
        ExecStart = "${lib.getExe controllerReconcileEvents}";
        Restart = "always";
        RestartSec = "2s";
      };
      bindsTo = [ "bluetooth.service" ];
      partOf = [ "bluetooth.service" ];
    };

    systemd.services.bluetooth.serviceConfig.ExecStart = lib.mkForce [
      ""
      "${config.hardware.bluetooth.package}/libexec/bluetooth/bluetoothd -f /etc/bluetooth/main.conf --noplugin=bap,csip -E"
    ];
    systemd.services.bluetooth.serviceConfig.Nice = -5;
    systemd.services.bluetooth.serviceConfig.CPUWeight = 500;
    systemd.services.bluetooth.restartIfChanged = lib.mkForce true;

    systemd.services.dbus.serviceConfig.CPUWeight = 300;
    systemd.services.dbus.serviceConfig.Nice = -2;

    systemd.services.controller-bluetooth-tuning = {
      description = "Apply Bluetooth controller tuning for Boomer Switch Pro controllers";
      wantedBy = [ "multi-user.target" ];
      after = [ "bluetooth.service" ];
      before = [
        "controller-autoconnect.service"
        "controller-leds.service"
      ];
      path = [
        pkgs.bluez
        pkgs.coreutils
      ];
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
        TimeoutStartSec = "20s";
      };
      script = ''
        log_file="${cfg.dataRoot}/logs/controller-bluetooth-tuning.log"
        mkdir -p "$(dirname "$log_file")"
        touch "$log_file"

        log() {
          echo "$(date -u +%FT%TZ) $*" >>"$log_file"
        }

        dynamic_debug=/sys/kernel/debug/dynamic_debug/control
        if [ -w "$dynamic_debug" ]; then
          for query in \
            'func __joycon_hid_send -p' \
            'func joycon_hid_send_sync -p' \
            'func joycon_send_subcmd -p' \
            'func joycon_set_player_leds -p' \
            'func joycon_send_rumble_data -p' \
            'file drivers/bluetooth/btusb.c -p' \
            'file drivers/bluetooth/btmtk.c -p'
          do
            printf '%s\n' "$query" >"$dynamic_debug" 2>/dev/null || true
          done
        fi

        btmgmt_set() {
          if ! timeout -k 1s 2s btmgmt "$@" >>"$log_file" 2>&1; then
            log "skipped slow btmgmt $*"
          fi
        }

        echo N > /sys/module/btusb/parameters/enable_autosuspend 2>/dev/null || true
        echo Y > /sys/module/mt7921e/parameters/disable_aspm 2>/dev/null || true
        btmgmt_set bredr on
        btmgmt_set le off
        btmgmt_set advertising off
        btmgmt_set connectable on
        btmgmt_set bondable on
        btmgmt_set fast-conn on
        btmgmt_set ssp on
        btmgmt_set sc on
        ${lib.getExe controllerBluetoothLowLatency} || true
      '';
    };

    systemd.services.controller-bluetooth-low-latency = {
      description = "Disable Bluetooth low-power sniff policy for Switch Pro controller links";
      wantedBy = [ "multi-user.target" ];
      after = [
        "bluetooth.service"
        "controller-bluetooth-tuning.service"
      ];
      before = [
        "controller-autoconnect.service"
        "controller-leds.service"
      ];
      unitConfig.StartLimitIntervalSec = 0;
      serviceConfig = {
        Type = "oneshot";
        ExecStart = "${lib.getExe controllerBluetoothLowLatency}";
        TimeoutStartSec = "8s";
      };
      bindsTo = [ "bluetooth.service" ];
      partOf = [ "bluetooth.service" ];
    };

    systemd.services.controller-bluetooth-debug = {
      description = "Enable focused Bluetooth and hid-nintendo debug logging";
      after = [ "systemd-modules-load.service" ];
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
      };
      script = ''
        control=/sys/kernel/debug/dynamic_debug/control
        [ -w "$control" ] || exit 0
        for query in \
          'func __joycon_hid_send +p' \
          'func joycon_hid_send_sync +p' \
          'func joycon_send_subcmd +p' \
          'func joycon_set_player_leds +p' \
          'func joycon_send_rumble_data +p' \
          'file drivers/bluetooth/btusb.c +p' \
          'file drivers/bluetooth/btmtk.c +p'
        do
          printf '%s\n' "$query" >"$control" 2>/dev/null || true
        done
      '';
    };

    systemd.services.controller-bluetooth-health = {
      description = "Log Switch Pro Bluetooth HID health warnings";
      after = [
        "bluetooth.service"
        "controller-leds.service"
      ];
      serviceConfig = {
        ExecStart = "${lib.getExe controllerBluetoothHealth}";
      };
      bindsTo = [ "bluetooth.service" ];
      partOf = [ "bluetooth.service" ];
    };
  };
}
