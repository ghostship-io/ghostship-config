{ config, lib, pkgs, ... }:

let
  cfg = config.ghostship.emulation;
  emu = config.ghostship.emulation.internal.lib;
  settingsTuiSource = ./settings-tui.py;

  settingsTui = pkgs.writeShellScriptBin "emulation-settings-tui" ''
    set -euo pipefail
    export PATH=${lib.makeBinPath [
      config.ghostship.emulation.internal.scripts.audioRoute
      config.ghostship.emulation.internal.scripts.controllerAutoconnect
      config.ghostship.emulation.internal.scripts.controllerLeds
      config.ghostship.emulation.internal.scripts.controllerResolve
      pkgs.bluez
      pkgs.coreutils
      pkgs.findutils
      pkgs.gnugrep
      pkgs.iproute2
      pkgs.jq
      pkgs.networkmanager
      pkgs.procps
      pkgs.pulseaudio
      pkgs.systemd
      pkgs.util-linux
      pkgs.wireplumber
    ]}:$PATH
    export EMULATION_CONFIG_ROOT=${lib.escapeShellArg cfg.configRoot}
    export EMULATION_DATA_ROOT=${lib.escapeShellArg cfg.dataRoot}
    exec ${pkgs.python3}/bin/python3 ${settingsTuiSource} "$@"
  '';

  mkSettingsTool = name: title: mode:
    let
      fontSize = if mode == "maps" then "22" else "28";
      geometry = if mode == "maps" then "110x30" else "92x26";
    in
    pkgs.writeShellScriptBin name ''
      set -euo pipefail
      export PATH=${lib.makeBinPath [ settingsTui pkgs.foot pkgs.xterm ]}:$PATH
      log_dir=${lib.escapeShellArg cfg.dataRoot}/logs/tools
      mkdir -p "$log_dir"
      log_file="$log_dir/${name}.log"
      {
        printf '%s launching ${name}: DISPLAY=%s WAYLAND_DISPLAY=%s TERM=%s\n' "$(date -Is)" "''${DISPLAY:-}" "''${WAYLAND_DISPLAY:-}" "''${TERM:-}"
        if [ -n "''${DISPLAY:-}" ] && command -v xterm >/dev/null 2>&1; then
          exec xterm -T ${lib.escapeShellArg title} -fa Monospace -fs ${fontSize} -geometry ${geometry} -e emulation-settings-tui ${mode}
        fi
        if [ -n "''${WAYLAND_DISPLAY:-}" ] && command -v foot >/dev/null 2>&1; then
          exec foot -T ${lib.escapeShellArg title} -f monospace:size=${fontSize} -- emulation-settings-tui ${mode}
        fi
        exec emulation-settings-tui ${mode}
      } >>"$log_file" 2>&1
    '';

  restartEsdeDelayed = pkgs.writeShellScript "restart-esde-delayed" (
    if cfg.startup.mode == "kiosk" then ''
      set -euo pipefail
      sleep 1
      ${pkgs.systemd}/bin/systemctl stop emulation-session.service || true
      ${pkgs.systemd}/bin/systemctl reset-failed greetd.service emulation-session.service || true
      exec ${pkgs.systemd}/bin/systemctl restart greetd.service
    '' else ''
      set -euo pipefail
      sleep 1
      ${pkgs.systemd}/bin/systemctl stop emulation-session.service || true
      for _ in $(${pkgs.coreutils}/bin/seq 1 10); do
        if ! ${pkgs.systemd}/bin/systemctl is-active --quiet emulation-session.service; then
          break
        fi
        sleep 0.5
      done
      ${pkgs.systemd}/bin/systemctl stop getty@tty1.service || true
      ${pkgs.systemd}/bin/systemctl reset-failed emulation-session.service getty@tty1.service || true
      exec ${pkgs.systemd}/bin/systemctl start emulation-session.service
    ''
  );

  toolScripts = {
    bluetooth-settings = mkSettingsTool "bluetooth-settings" "Bluetooth Settings" "bluetooth";
    wifi-settings = mkSettingsTool "wifi-settings" "Wi-Fi Settings" "wifi";
    controller-maps = mkSettingsTool "controller-maps" "Controller Maps" "maps";
    restart-esde = pkgs.writeShellScriptBin "restart-esde" ''
      set -euo pipefail
      ${pkgs.systemd}/bin/systemctl start --no-block restart-esde.service
    '';
    system-shutdown = pkgs.writeShellScriptBin "system-shutdown" ''
      set -euo pipefail
      systemctl poweroff
    '';
    system-reboot = pkgs.writeShellScriptBin "system-reboot" ''
      set -euo pipefail
      systemctl reboot
    '';
  };

  syncEsdeTools = pkgs.writeShellScriptBin "sync-esde-tools" ''
    set -euo pipefail
    install -d -m 0755 -o ${cfg.user} -g ${cfg.group} "${cfg.dataRoot}/tools"
    ${lib.concatMapStringsSep "\n" (tool: ''
      ln -sfn ${lib.getExe (builtins.getAttr tool.target toolScripts)} "${cfg.dataRoot}/tools/${tool.file}"
      chown -h ${cfg.user}:${cfg.group} "${cfg.dataRoot}/tools/${tool.file}" || true
    '') emu.tools}
  '';
in
{
  config = lib.mkIf cfg.enable {
    security.polkit.enable = true;
    security.polkit.extraConfig = ''
      polkit.addRule(function(action, subject) {
        if (subject.user != "${cfg.user}") {
          return;
        }
        if (action.id != "org.freedesktop.systemd1.manage-units") {
          return;
        }
        var unit = action.lookup("unit");
        var verb = action.lookup("verb");
        if ((unit == "bluetooth.service" ||
             unit == "NetworkManager.service" ||
             unit == "wifi-5ghz-only.service" ||
             unit == "controller-leds.service" ||
             unit == "controller-leds-apply.service" ||
             unit == "controller-autoconnect.service" ||
             unit == "restart-esde.service") &&
            (verb == "start" || verb == "stop" || verb == "restart")) {
          return polkit.Result.YES;
        }
      });
    '';
    systemd.services.restart-esde = {
      description = "Restart ES-DE from outside the active emulation session";
      serviceConfig = {
        Type = "oneshot";
        ExecStart = restartEsdeDelayed;
      };
    };
    ghostship.emulation.internal.scripts = toolScripts // {
      inherit settingsTui syncEsdeTools;
    };
    ghostship.emulation.internal.setupScripts = [ syncEsdeTools ];
  };
}
