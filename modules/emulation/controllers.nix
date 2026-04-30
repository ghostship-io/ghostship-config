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
    mkdir -p "$state_dir" "$(dirname "$log_file")"
    touch "$log_file"
    chown ${cfg.user}:${cfg.group} "$state_dir" "$log_file" || true

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
      busctl --system --json=short call org.bluez / org.freedesktop.DBus.ObjectManager GetManagedObjects 2>/dev/null \
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

    supported_player_device() {
      mac="$1"
      name="''${2:-}"
      modalias="''${3:-}"
      icon="''${4:-}"
      text="$(printf '%s\n%s\n%s\n' "$name" "$modalias" "$icon" | tr '[:upper:]' '[:lower:]')"
      if printf '%s\n' "$text" | grep -Eiq 'audio|headphone|headset|speaker|keyboard|mouse|phone|television| tv|shield'; then
        return 1
      fi
      printf '%s\n' "$text" | grep -Eiq '^pro controller$|usb:v057ep2009|name: pro controller|alias: pro controller|nintendo switch pro|joy-con|joycon'
    }

    prune_non_player_devices() {
      ensure_order_file
      before="$(jq -c '.players // []' "$order_file" 2>/dev/null || echo '[]')"
      tmp="$(mktemp)"
      jq '
        .players |= map(select(
          (.mac == "KEYBOARD") or
          (
            ((.mac // "") | test("^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")) and
            ((.name // "") | test("(?i)(^pro controller$|nintendo switch pro|joy-con|joycon|switch pro)"))
          )
        ))
      ' "$order_file" >"$tmp"
      mv "$tmp" "$order_file"
      after="$(jq -c '.players // []' "$order_file" 2>/dev/null || echo '[]')"
      if [ "$before" != "$after" ]; then
        echo "$(date -u +%FT%TZ) pruned non-switch controller player entries" >>"$log_file"
      fi
    }

    record_connected_devices() {
      ensure_order_file
      prune_non_player_devices
      tmp="$(mktemp)"
      jq '.players |= map(if ((.mac // "") | test("^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")) then . + {connected:false} else . end)' "$order_file" >"$tmp"
      mv "$tmp" "$order_file"

      connected_tmp="$(mktemp)"
      bluez_device_rows >"$connected_tmp" || true

      while IFS=$'\t' read -r mac name connected _paired _trusted _wake modalias icon; do
        [ -n "''${mac:-}" ] || continue
        [ "''${connected:-false}" = true ] || continue
        if ! printf '%s\n' "$mac" | grep -Eiq '^([0-9a-f]{2}:){5}[0-9a-f]{2}$'; then
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
             | if $next == null then . else .players += [{player:$next, mac:$mac, name:$name, connected:true}] end' \
            "$order_file" >"$tmp"
        fi
        mv "$tmp" "$order_file"
      done <"$connected_tmp"
      rm -f "$connected_tmp"

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

    apply_leds() {
      force="''${1:-false}"
      found=0
      changed=0
      while IFS=$'\t' read -r player mac; do
        [ -n "''${player:-}" ] || continue
        device_root=""
        for event in /sys/class/input/event*; do
          [ -r "$event/device/uniq" ] || continue
          uniq="$(tr '[:lower:]' '[:upper:]' <"$event/device/uniq" 2>/dev/null || true)"
          [ "$uniq" = "$(printf '%s' "$mac" | tr '[:lower:]' '[:upper:]')" ] || continue
          input_path="$(readlink -f "$event/device")"
          device_root="$(dirname "$(dirname "$input_path")")"
          break
        done
        [ -n "''${device_root:-}" ] || continue
        trigger_led=""
        trigger_value=""
        controller_changed=0
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
              if [ -z "$trigger_led" ]; then
                trigger_led="$led/brightness"
                trigger_value="$desired"
              fi
              if [ "$current" != "$desired" ]; then
                echo "$desired" >"$led/brightness" 2>/dev/null || true
                changed=1
                controller_changed=1
                sleep 0.08
              fi
              ;;
          esac
        done
        if [ "$force" = true ] && [ "$controller_changed" = 0 ] && [ -n "$trigger_led" ]; then
          echo "$trigger_value" >"$trigger_led" 2>/dev/null || true
          changed=1
          sleep 0.08
        fi
        sleep 0.12
      done < <(desired_led_rows)

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
      sanitize_known_bad_order
      record_connected_devices || true
      apply_leds true || true
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
      sanitize_known_bad_order
      record_connected_devices || true
      state="$(desired_led_state || true)"
      previous="$(cat "$last_state_file" 2>/dev/null || true)"
      if [ "$state" != "$previous" ]; then
        apply_leds false || true
        printf '%s\n' "$state" >"$last_state_file"
        chown ${cfg.user}:${cfg.group} "$last_state_file" || true
      fi
      sleep 15
    done
  '';

  controllerAutoconnect = pkgs.writeShellScriptBin "controller-autoconnect" ''
    set -euo pipefail
    export PATH=${emu.scriptPath}:$PATH
    log_file="${cfg.dataRoot}/logs/controller-autoconnect.log"
    mkdir -p "$(dirname "$log_file")"
    touch "$log_file"

    log() {
      echo "$(date -u +%FT%TZ) $*" >>"$log_file"
    }

    bluez_switch_pro_rows() {
      busctl --system --json=short call org.bluez / org.freedesktop.DBus.ObjectManager GetManagedObjects 2>/dev/null \
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
            | select((.[3] == "true") and (((.[4] | test("v057ep2009")) or (.[1] | ascii_downcase | test("(^pro controller$|nintendo switch pro)")))))
            | @tsv
          '
    }

    connected_device() {
      [ "''${1:-false}" = true ]
    }

    connect_once() {
      bluetoothctl power on >/dev/null 2>&1 || true
      did_connect=0
      while IFS=$'\t' read -r mac name connected _paired _modalias _icon; do
        [ -n "''${mac:-}" ] || continue
        if connected_device "$connected"; then
          continue
        fi
        log "connecting ''${name:-Switch Pro Controller} ($mac)"
        bluetoothctl trust "$mac" >/dev/null 2>&1 || true
        bluetoothctl wake "$mac" on >/dev/null 2>&1 || true
        if timeout 15s bluetoothctl connect "$mac" >>"$log_file" 2>&1; then
          log "connected ''${name:-Switch Pro Controller} ($mac)"
          did_connect=1
        else
          log "connect failed ''${name:-Switch Pro Controller} ($mac)"
        fi
        sleep 2
      done < <(bluez_switch_pro_rows)
      if [ "$did_connect" = 1 ]; then
        ${lib.getExe controllerLeds} apply || true
      fi
    }

    case "''${1:-loop}" in
      once|--once)
        connect_once
        ;;
      loop)
        while true; do
          connect_once
          sleep 30
        done
        ;;
      *)
        echo "Usage: controller-autoconnect [loop|once]" >&2
        exit 64
        ;;
    esac
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
      disabledPlugins = [ "bap" ];
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
      SUBSYSTEM=="usb", ATTR{idVendor}=="057e", ATTR{idProduct}=="2009", TEST=="power/control", ATTR{power/control}="on"
      KERNEL=="hidraw*", ATTRS{idVendor}=="2dc8", ATTRS{idProduct}=="310b", MODE="0660", GROUP="input", TAG+="uaccess"
      KERNEL=="hidraw*", ATTRS{idVendor}=="057e", ATTRS{idProduct}=="2009", MODE="0660", GROUP="input", TAG+="uaccess"
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
      };
    };

    systemd.services.controller-leds-apply = {
      description = "Apply controller player LED state once";
      after = [
        "bluetooth.service"
        "emulation-setup.service"
        "controller-bluetooth-tuning.service"
      ];
      serviceConfig = {
        Type = "oneshot";
        ExecStart = "${lib.getExe controllerLeds} apply";
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
      };
    };

    systemd.services.bluetooth.serviceConfig.ExecStart = lib.mkForce [
      ""
      "${config.hardware.bluetooth.package}/libexec/bluetooth/bluetoothd -f /etc/bluetooth/main.conf --noplugin=bap -E --debug=*"
    ];
    systemd.services.bluetooth.restartIfChanged = lib.mkForce true;

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
        TimeoutStartSec = "60s";
      };
      script = ''
        btmgmt_set() {
          timeout 5s btmgmt "$@" || true
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
      '';
    };

    systemd.services.controller-bluetooth-debug = {
      description = "Enable focused Bluetooth and hid-nintendo debug logging";
      wantedBy = [ "multi-user.target" ];
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
      wantedBy = [ "multi-user.target" ];
      after = [
        "bluetooth.service"
        "controller-leds.service"
      ];
      serviceConfig = {
        ExecStart = "${lib.getExe controllerBluetoothHealth}";
        Restart = "always";
        RestartSec = "5s";
      };
      bindsTo = [ "bluetooth.service" ];
      partOf = [ "bluetooth.service" ];
    };
  };
}
