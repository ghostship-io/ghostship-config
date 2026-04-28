{ config, lib, pkgs, ... }:

let
  cfg = config.ghostship.emulation;
  emu = config.ghostship.emulation.internal.lib;

  boomerControllerLeds = pkgs.writeShellScriptBin "boomer-controller-leds" ''
    set -euo pipefail
    export PATH=${emu.scriptPath}:$PATH
    state_dir="${cfg.configRoot}/controllers"
    order_file="$state_dir/player-order.json"
    log_file="${cfg.dataRoot}/logs/controller-leds.log"
    mkdir -p "$state_dir" "$(dirname "$log_file")"
    touch "$log_file"
    chown ${cfg.user}:${cfg.group} "$state_dir" "$log_file" || true

    ensure_order_file() {
      if ! jq -e '.players | type == "array"' "$order_file" >/dev/null 2>&1; then
        printf '{"players":[]}\n' >"$order_file"
        chown ${cfg.user}:${cfg.group} "$order_file" || true
      fi
    }

    record_connected_devices() {
      ensure_order_file
      tmp="$(mktemp)"
      jq '.players |= map(. + {connected:false})' "$order_file" >"$tmp"
      mv "$tmp" "$order_file"

      bluetoothctl devices Connected 2>/dev/null | while read -r _ mac rest; do
        [ -n "''${mac:-}" ] || continue
        name="''${rest:-unknown-controller}"
        tmp="$(mktemp)"
        if jq -e --arg mac "$mac" '.players[]? | select(.mac == $mac)' "$order_file" >/dev/null; then
          jq --arg mac "$mac" --arg name "$name" \
            '.players |= map(if .mac == $mac then . + {name:$name, connected:true} else . end)' \
            "$order_file" >"$tmp"
        else
          jq --arg mac "$mac" --arg name "$name" \
            '.players += [{player:(.players | length) + 1, mac:$mac, name:$name, connected:true}]' \
            "$order_file" >"$tmp"
        fi
        mv "$tmp" "$order_file"
      done

      tmp="$(mktemp)"
      jq '.players |= [to_entries[] | .value + {player:(.key + 1)}]' "$order_file" >"$tmp"
      mv "$tmp" "$order_file"
      chown ${cfg.user}:${cfg.group} "$order_file" || true
      chmod 0644 "$order_file" || true
    }

    apply_leds() {
      found=0
      player=1
      for led in /sys/class/leds/*; do
        [ -e "$led/brightness" ] || continue
        name="$(basename "$led")"
        case "$name" in
          *player*|*pro_controller*|*8BitDo*|*nintendo*)
            found=1
            if [ "$player" -le 4 ]; then
              echo 1 >"$led/brightness" 2>/dev/null || true
              echo "$(date -u +%FT%TZ) set $name for player $player" >>"$log_file"
              player=$((player + 1))
            fi
            ;;
        esac
      done
      if [ "$found" = 0 ]; then
        echo "$(date -u +%FT%TZ) no supported controller LED sysfs entries found" >>"$log_file"
      fi
    }

    while true; do
      record_connected_devices || true
      apply_leds || true
      sleep 2
    done
  '';
in
{
  config = lib.mkIf cfg.enable {
    ghostship.emulation.internal.scripts.boomerControllerLeds = boomerControllerLeds;

    boot.kernelModules = [ "hid-nintendo" ];
    boot.extraModprobeConfig = ''
      options btusb enable_autosuspend=n
    '';

    hardware.bluetooth = {
      enable = true;
      powerOnBoot = true;
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

    systemd.services.boomer-wifi-5ghz-only = {
      description = "Keep Wi-Fi profiles constrained to 5 GHz for Bluetooth-focused emulation";
      wantedBy = [ "multi-user.target" ];
      after = [ "NetworkManager.service" ];
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
      };
      path = [ pkgs.networkmanager pkgs.util-linux ];
      script = ''
        rfkill unblock wlan || true
        nmcli radio wifi on || true
        nmcli -t -f UUID,TYPE connection show | while IFS=: read -r uuid type; do
          [ "$type" = "802-11-wireless" ] || continue
          nmcli connection modify "$uuid" 802-11-wireless.band a connection.autoconnect yes connection.autoconnect-priority 100 || true
        done
      '';
    };

    systemd.services.boomer-controller-leds = {
      description = "Maintain Boomer Kuwanger controller player order and LED state";
      wantedBy = [ "multi-user.target" ];
      after = [ "bluetooth.service" "boomer-emulation-setup.service" ];
      serviceConfig = {
        ExecStart = "${lib.getExe boomerControllerLeds}";
        Restart = "always";
        RestartSec = "2s";
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
      serviceConfig = {
        ExecStart = "${pkgs.joycond-cemuhook}/bin/joycond-cemuhook";
        Restart = "on-failure";
      };
    };
  };
}
