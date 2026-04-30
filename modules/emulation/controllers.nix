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

    connected_bluez_devices() {
      busctl --system --json=short call org.bluez / org.freedesktop.DBus.ObjectManager GetManagedObjects 2>/dev/null \
        | jq -r '
            .data[0]
            | to_entries[]
            | select(.value["org.bluez.Device1"]?)
            | .value["org.bluez.Device1"]
            | select(.Connected.data == true)
            | [
                .Address.data,
                ((.Alias.data // .Name.data // "unknown-controller") | gsub("[\t\r\n]"; " "))
              ]
            | @tsv
          '
    }

    supported_player_device() {
      mac="$1"
      name="''${2:-}"
      info="$(bluetoothctl info "$mac" 2>/dev/null || true)"
      text="$(printf '%s\n%s\n' "$name" "$info" | tr '[:upper:]' '[:lower:]')"
      if printf '%s\n' "$text" | grep -Eiq 'audio|headphone|headset|speaker|keyboard|mouse|phone|television| tv|shield'; then
        return 1
      fi
      printf '%s\n' "$text" | grep -Eiq '^pro controller$|modalias: usb:v057ep2009|name: pro controller|alias: pro controller|nintendo switch pro|joy-con|joycon'
    }

    prune_non_player_devices() {
      ensure_order_file
      jq -r '.players[]? | [.mac, (.name // "")] | @tsv' "$order_file" 2>/dev/null \
        | while IFS=$'\t' read -r mac name; do
            [ -n "''${mac:-}" ] || continue
            if ! printf '%s\n' "$mac" | grep -Eiq '^([0-9a-f]{2}:){5}[0-9a-f]{2}$'; then
              continue
            fi
            if supported_player_device "$mac" "$name"; then
              continue
            fi
            tmp="$(mktemp)"
            jq --arg mac "$(printf '%s' "$mac" | tr '[:lower:]' '[:upper:]')" \
              '.players |= map(select(((.mac // "") | ascii_upcase) != $mac))' \
              "$order_file" >"$tmp"
            mv "$tmp" "$order_file"
            echo "$(date -u +%FT%TZ) pruned non-controller player entry $mac" >>"$log_file"
          done
    }

    record_connected_devices() {
      ensure_order_file
      prune_non_player_devices
      tmp="$(mktemp)"
      jq '.players |= map(if ((.mac // "") | test("^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")) then . + {connected:false} else . end)' "$order_file" >"$tmp"
      mv "$tmp" "$order_file"

      connected_tmp="$(mktemp)"
      connected_bluez_devices >"$connected_tmp" || true

      while IFS=$'\t' read -r mac name; do
        [ -n "''${mac:-}" ] || continue
        if ! printf '%s\n' "$mac" | grep -Eiq '^([0-9a-f]{2}:){5}[0-9a-f]{2}$'; then
          continue
        fi
        name="''${name:-unknown-controller}"
        supported_player_device "$mac" "$name" || continue
        tmp="$(mktemp)"
        if jq -e --arg mac "$mac" '.players[]? | select(.mac == $mac)' "$order_file" >/dev/null; then
          jq --arg mac "$mac" --arg name "$name" \
            '.players |= map(if .mac == $mac then . + {name:$name, connected:true} else . end)' \
            "$order_file" >"$tmp"
        else
          jq --arg mac "$mac" --arg name "$name" \
            'def next_player:
              ([.players[]?.player] as $used
               | ([1, 2, 3, 4] | map(select(. as $slot | ($used | index($slot) | not))) | .[0])
               // ((.players | length) + 1));
             .players += [{player:next_player, mac:$mac, name:$name, connected:true}]' \
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

    apply_leds() {
      found=0
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
        for led in "$device_root"/leds/*:green:player-[1-4]; do
          [ -e "$led/brightness" ] || continue
          led_name="$(basename "$led")"
          led_index="''${led_name##*:green:player-}"
          case "$led_index" in
            [1-4])
              found=1
              if [ "$led_index" -le "$player" ]; then
                echo 1 >"$led/brightness" 2>/dev/null || true
              else
                echo 0 >"$led/brightness" 2>/dev/null || true
              fi
              ;;
          esac
        done
      done < <(jq -r '.players[]? | select(.connected == true) | [.player, .mac] | @tsv' "$order_file" 2>/dev/null || true)

      if [ "$found" = 0 ]; then
        status="no supported controller LED sysfs entries found"
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
      apply_leds || true
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
      run_once
      sleep 2
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

    switch_pro_device() {
      info="$1"
      printf '%s\n' "$info" | grep -Eiq 'Modalias:.*v057E[pP]2009|Name: Pro Controller|Alias: Pro Controller|Name: Nintendo Switch Pro|Alias: Nintendo Switch Pro'
    }

    connected_device() {
      printf '%s\n' "$1" | grep -Eq 'Connected: yes|BREDR\.Connected: yes'
    }

    connect_once() {
      bluetoothctl power on >/dev/null 2>&1 || true
      bluetoothctl devices Paired | awk '/^Device / {print $2}' | while read -r mac; do
        [ -n "''${mac:-}" ] || continue
        info="$(bluetoothctl info "$mac" 2>/dev/null || true)"
        [ -n "$info" ] || continue
        switch_pro_device "$info" || continue
        name="$(printf '%s\n' "$info" | awk -F': ' '/^\s*Name:/ {print $2; exit}')"
        bluetoothctl trust "$mac" >/dev/null 2>&1 || true
        bluetoothctl wake "$mac" on >/dev/null 2>&1 || true
        if connected_device "$info"; then
          continue
        fi
        log "connecting ''${name:-Switch Pro Controller} ($mac)"
        if timeout 15s bluetoothctl connect "$mac" >>"$log_file" 2>&1; then
          log "connected ''${name:-Switch Pro Controller} ($mac)"
          ${lib.getExe controllerLeds} apply || true
        else
          log "connect failed ''${name:-Switch Pro Controller} ($mac)"
        fi
        sleep 1
      done
    }

    case "''${1:-loop}" in
      once|--once)
        connect_once
        ;;
      loop)
        while true; do
          connect_once
          sleep 6
        done
        ;;
      *)
        echo "Usage: controller-autoconnect [loop|once]" >&2
        exit 64
        ;;
    esac
  '';
in
{
  config = lib.mkIf cfg.enable {
    ghostship.emulation.internal.scripts.controllerLeds = controllerLeds;
    ghostship.emulation.internal.scripts.controllerAutoconnect = controllerAutoconnect;

    boot.kernelModules = [ "hid-nintendo" ];
    boot.extraModprobeConfig = ''
      options btusb enable_autosuspend=n
    '';

    hardware.bluetooth = {
      enable = true;
      powerOnBoot = true;
      disabledPlugins = [ "bap" ];
      settings = {
        General = {
          Experimental = true;
          FastConnectable = true;
          ControllerMode = "dual";
          JustWorksRepairing = "always";
          Privacy = "off";
        };
        Policy = {
          AutoEnable = true;
        };
      };
    };

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

    systemd.services.joycond = lib.mkIf (pkgs ? joycond) {
      description = "Joy-Con and Switch Pro controller userspace daemon";
      wantedBy = [ "multi-user.target" ];
      after = [ "bluetooth.service" ];
      serviceConfig = {
        ExecStart = "${pkgs.joycond}/bin/joycond";
        Restart = "on-failure";
      };
    };

    systemd.services.joycond-cemuhook = lib.mkIf (pkgs ? joycond-cemuhook) {
      description = "Joycond Cemuhook motion server";
      wantedBy = [ "multi-user.target" ];
      after = [ "joycond.service" ];
      path = [ pkgs.kmod ];
      serviceConfig = {
        ExecStart = "${pkgs.joycond-cemuhook}/bin/joycond-cemuhook";
        Restart = "on-failure";
      };
    };
  };
}
