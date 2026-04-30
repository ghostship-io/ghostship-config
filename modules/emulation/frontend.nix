{ config
, lib
, pkgs
, ...
}:

let
  cfg = config.ghostship.emulation;
  emu = config.ghostship.emulation.internal.lib;
  packages = config.ghostship.emulation.internal.packages;

  mkSystemXml = system: ''
    <system>
      <name>${emu.xmlEscape system.id}</name>
      <fullname>${emu.xmlEscape system.fullname}</fullname>
      <path>${emu.xmlEscape "${cfg.romRoot}/${system.folder}"}</path>
      <extension>${emu.xmlEscape system.extensions}</extension>
      <command>run-emulator ${emu.xmlEscape system.id} ${emu.xmlEscape system.emulator} %ROM%</command>
      <platform>${emu.xmlEscape system.platform}</platform>
      <theme>${emu.xmlEscape system.theme}</theme>
    </system>'';

  esSystemsXml = pkgs.writeText "emulation-es-systems.xml" ''
    <?xml version="1.0"?>
    <systemList>
    ${lib.concatMapStringsSep "\n" mkSystemXml emu.allSystems}
      <system>
        <name>tools</name>
        <fullname>Tools</fullname>
        <path>${emu.xmlEscape "${cfg.dataRoot}/tools"}</path>
        <extension>.sh .SH</extension>
        <command>${pkgs.bash}/bin/bash %ROM%</command>
        <platform>tools</platform>
        <theme>tools</theme>
      </system>
    </systemList>
  '';

  esFindRulesXml = pkgs.writeText "emulation-es-find-rules.xml" ''
    <?xml version="1.0"?>
    <ruleList>
      <emulator name="EMULATION_WRAPPER">
        <rule type="systempath">
          <entry>run-emulator</entry>
        </rule>
      </emulator>
      <emulator name="RETROARCH">
        <rule type="systempath">
          <entry>${packages.retroarchPackage}/bin/retroarch</entry>
        </rule>
      </emulator>
      <emulator name="GAMESCOPE">
        <rule type="systempath">
          <entry>${pkgs.gamescope}/bin/gamescope</entry>
        </rule>
      </emulator>
    </ruleList>
  '';

  mkToolGamelistEntry = index: tool: ''
    <game>
      <path>./${emu.xmlEscape tool.file}</path>
      <name>${emu.xmlEscape (lib.removeSuffix ".sh" tool.file)}</name>
      <sortname>${lib.fixedWidthNumber 2 (index + 1)}</sortname>
    </game>'';

  toolsGamelistXml = pkgs.writeText "emulation-tools-gamelist.xml" ''
    <?xml version="1.0"?>
    <gameList>
    ${lib.concatStringsSep "\n" (lib.imap0 mkToolGamelistEntry emu.tools)}
    </gameList>
  '';

  esSettingsXml = pkgs.writeText "emulation-es-settings.xml" ''
    <?xml version="1.0"?>
    <settings>
      <string name="Theme" value="art-book-next-es-de" />
      <string name="ThemeSet" value="art-book-next-es-de" />
      <string name="ThemeAspectRatio" value="automatic" />
      <string name="SystemsSorting" value="manufacturer_hwtype_year" />
      <string name="InputControllerType" value="switchpro" />
      <string name="Scraper" value="screenscraper" />
      <string name="ScraperRegion" value="na" />
      <string name="ScraperLanguage" value="en" />
      <string name="MediaDirectory" value="${emu.xmlEscape "${cfg.esde.appDataDir}/downloaded_media"}" />
      <bool name="DisplayClock" value="true" />
      <bool name="InputOnlyFirstController" value="false" />
      <bool name="ScraperUseAccountScreenScraper" value="true" />
      <bool name="ScrapeGameNames" value="true" />
      <bool name="ScrapeRatings" value="true" />
      <bool name="ScrapeMetadata" value="true" />
      <bool name="ScrapeVideos" value="true" />
      <bool name="ScrapeScreenshots" value="true" />
      <bool name="ScrapeCovers" value="true" />
      <bool name="ScrapeMarquees" value="true" />
      <bool name="MiximageGenerate" value="true" />
      <bool name="MiximageIncludeMarquee" value="true" />
      <bool name="MiximageIncludeBox" value="true" />
      <bool name="MiximageIncludePhysicalMedia" value="true" />
      <bool name="ScraperSearchFileHash" value="true" />
      <bool name="ScraperInteractive" value="false" />
      <bool name="ScraperSemiautomatic" value="true" />
      <bool name="ScraperRegionFallback" value="true" />
      <bool name="Debug" value="false" />
      <bool name="CheckForUpdates" value="false" />
    </settings>
  '';

  syncEsdeConfig = pkgs.writeShellScriptBin "sync-esde-config" ''
    set -euo pipefail
    export PATH=${emu.scriptPath}:${
      lib.makeBinPath (
        [
          pkgs.jq
          pkgs.python3
        ]
        ++ lib.optional (
          config.ghostship.emulation.internal.scripts ? renderScraperSettings
        ) config.ghostship.emulation.internal.scripts.renderScraperSettings
      )
    }:$PATH

    install -d -m 0755 -o ${cfg.user} -g ${cfg.group} \
      "${cfg.dataRoot}" \
      "${cfg.romRoot}" \
      "${cfg.biosRoot}" \
      "${cfg.dataRoot}/saves" \
      "${cfg.dataRoot}/states" \
      "${cfg.dataRoot}/screenshots" \
      "${cfg.configRoot}" \
      "${cfg.configRoot}/es-de" \
      "${cfg.configRoot}/smoke" \
      "${cfg.dataRoot}/logs" \
      "${cfg.dataRoot}/logs/esde-session" \
      "${cfg.dataRoot}/logs/launches" \
      "${cfg.dataRoot}/logs/smoke" \
      "${cfg.dataRoot}/smoke-roms" \
      "${cfg.dataRoot}/tmp" \
      "${cfg.dataRoot}/tools" \
      "${cfg.esde.appDataDir}" \
      "${cfg.esde.appDataDir}/custom_systems" \
      "${cfg.esde.appDataDir}/gamelists/tools" \
      "${cfg.esde.appDataDir}/settings" \
      "${cfg.esde.appDataDir}/themes" \
      "${cfg.esde.appDataDir}/scripts"

    install -D -m 0644 -o ${cfg.user} -g ${cfg.group} ${esSystemsXml} "${cfg.esde.appDataDir}/custom_systems/es_systems.xml"
    install -D -m 0644 -o ${cfg.user} -g ${cfg.group} ${esFindRulesXml} "${cfg.esde.appDataDir}/custom_systems/es_find_rules.xml"
    install -D -m 0644 -o ${cfg.user} -g ${cfg.group} ${toolsGamelistXml} "${cfg.esde.appDataDir}/gamelists/tools/gamelist.xml"
    if [ ! -e "${cfg.esde.appDataDir}/settings/es_settings.xml" ]; then
      install -D -m 0640 -o ${cfg.user} -g ${cfg.group} ${esSettingsXml} "${cfg.esde.appDataDir}/settings/es_settings.xml"
    fi

    ln -sfn ${packages.artBookNext}/share/es-de/themes/art-book-next-es-de "${cfg.esde.appDataDir}/themes/art-book-next-es-de"
    python3 - "${cfg.esde.appDataDir}/settings/es_settings.xml" <<'PY'
    import os
    import re
    import sys
    import tempfile
    import xml.etree.ElementTree as ET
    from pathlib import Path

    settings_path = Path(sys.argv[1])
    raw_settings = settings_path.read_text() if settings_path.exists() else ""
    try:
        root = ET.fromstring(raw_settings)
        if root.tag != "settings":
            wrapper = ET.Element("settings")
            wrapper.append(root)
            root = wrapper
    except ET.ParseError:
        body = re.sub(r"^\s*<\?xml[^>]*\?>", "", raw_settings, count=1)
        root = ET.fromstring(f"<settings>{body}</settings>") if body.strip() else ET.Element("settings")

    def set_string(name, value):
        for entry in root.findall("string"):
            if entry.get("name") == name:
                entry.set("value", value)
                return
        ET.SubElement(root, "string", {"name": name, "value": value})

    def set_bool(name, value):
        text_value = "true" if value else "false"
        for entry in root.findall("bool"):
            if entry.get("name") == name:
                entry.set("value", text_value)
                return
        ET.SubElement(root, "bool", {"name": name, "value": text_value})

    set_string("Theme", "art-book-next-es-de")
    set_string("ThemeSet", "art-book-next-es-de")
    set_string("ThemeAspectRatio", "automatic")
    set_string("SystemsSorting", "manufacturer_hwtype_year")
    set_string("InputControllerType", "switchpro")
    set_bool("DisplayClock", True)
    set_bool("InputOnlyFirstController", False)

    fd, tmp = tempfile.mkstemp(prefix="es_settings.", dir=str(settings_path.parent))
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write('<?xml version="1.0"?>\n')
        for entry in root:
            handle.write(ET.tostring(entry, encoding="unicode"))
            handle.write("\n")
    os.chmod(tmp, 0o640)
    Path(tmp).replace(settings_path)
    PY
    chown ${cfg.user}:${cfg.group} "${cfg.esde.appDataDir}/settings/es_settings.xml"
    chmod 0640 "${cfg.esde.appDataDir}/settings/es_settings.xml"

    printf '%s' '${emu.allSystemsJson}' | jq -c '.[]' | while read -r system; do
      folder="$(jq -r '.folder' <<<"$system")"
      source="/mnt/z/Library/ROMs/roms/$folder"
      target="${cfg.romRoot}/$folder"
      if [ -e "$source" ] && [ ! -e "$target" ]; then
        ln -s "$source" "$target"
      elif [ ! -e "$target" ]; then
        install -d -m 0755 -o ${cfg.user} -g ${cfg.group} "$target"
      fi
    done

    pico8_folder="Fantasy - PICO-8 (2015)"
    pico8_source="/mnt/z/Library/ROMs/roms/$pico8_folder"
    pico8_target="${cfg.romRoot}/$pico8_folder"
    if [ -d "$pico8_source" ] && [ -d "$pico8_target" ]; then
      if ! find -L "$pico8_target" -maxdepth 1 -type f \( -name '*.p8' -o -name '*.P8' -o -name '*.p8.png' -o -name '*.P8.PNG' \) -print -quit | grep -q .; then
        for cart in \
          "Celeste Classic.p8.png" \
          "Celeste Classic 2 - Lani's Trek.p8.png" \
          "Just One Boss.p8.png" \
          "PICOHOT.p8.png" \
          "POOM.p8.png" \
          "Pico Tetris.p8.png"; do
          if [ -f "$pico8_source/$cart" ] && [ ! -e "$pico8_target/$cart" ]; then
            ln -s "$pico8_source/$cart" "$pico8_target/$cart"
          fi
        done
      fi
    fi

    ln -sfn "${cfg.dataRoot}" /home/${cfg.user}/Emulation
    chown -h ${cfg.user}:${cfg.group} /home/${cfg.user}/Emulation || true
    if command -v render-esde-scraper-settings >/dev/null 2>&1; then
      render-esde-scraper-settings || true
    fi
  '';

  esdePreflight = pkgs.writeShellScriptBin "esde-preflight" ''
    set -u
    export PATH=${emu.scriptPath}:${
      lib.makeBinPath [
        packages.esdePackage
        pkgs.gamescope
        pkgs.jq
        pkgs.util-linux
        pkgs.vulkan-tools
        config.ghostship.emulation.internal.scripts.displayProfile
      ]
    }:$PATH

    fail=0
    check() {
      label="$1"
      shift
      if "$@" >/dev/null 2>&1; then
        printf 'ok - %s\n' "$label"
      else
        printf 'FAIL - %s\n' "$label"
        fail=1
      fi
    }

    uid="$(id -u ${cfg.user} 2>/dev/null || true)"
    runtime_dir="/run/user/$uid"

    check "no failed systemd units" sh -c '! systemctl --failed --no-legend | grep -q .'
    check "kiosk user exists" test -n "$uid"
    check "kiosk runtime directory exists" test -d "$runtime_dir"
    check "kiosk session D-Bus socket exists" test -S "$runtime_dir/bus"
    check "connected display detected" sh -c 'display-profile | jq -e ".connected == true and (.connector | length > 0)"'
    check "selected DRM card exists" sh -c 'device="$(display-profile | jq -r ".drm_device // empty")"; [ -n "$device" ] && [ -e "$device" ]'
    check "kiosk can read/write selected DRM card" sh -c 'device="$(display-profile | jq -r ".drm_device // empty")"; [ -n "$device" ] && runuser -u ${cfg.user} -- test -w "$device"'
    check "kiosk can access render nodes" sh -c 'runuser -u ${cfg.user} -- sh -c "test -w /dev/dri/renderD128 || test -w /dev/dri/renderD129"'
    check "RX 6650M Vulkan device is visible" sh -c 'vulkaninfo --summary 2>/dev/null | grep -Eq "deviceID[[:space:]]*=[[:space:]]*0x73ef|AMD Radeon RX 6650M"'
    check "gamescope is available" gamescope --version
    check "ES-DE is available" es-de --version
    check "ES-DE custom systems are installed" test -r "${cfg.esde.appDataDir}/custom_systems/es_systems.xml"
    check "ES-DE find rules are installed" test -r "${cfg.esde.appDataDir}/custom_systems/es_find_rules.xml"
    check "Art Book Next theme is installed" test -e "${cfg.esde.appDataDir}/themes/art-book-next-es-de"
    check "ES-DE appdata is writable by kiosk" runuser -u ${cfg.user} -- test -w "${cfg.esde.appDataDir}"
    check "ES-DE session log directory is writable by kiosk" runuser -u ${cfg.user} -- test -w "${cfg.dataRoot}/logs/esde-session"

    exit "$fail"
  '';

  esdeStatus = pkgs.writeShellScriptBin "esde-status" ''
    set -euo pipefail
    export PATH=${emu.scriptPath}:${
      lib.makeBinPath [
        pkgs.procps
        pkgs.systemd
        pkgs.jq
        config.ghostship.emulation.internal.scripts.displayProfile
      ]
    }:$PATH

    printf 'emulation-session: '
    systemctl is-active emulation-session.service || true

    printf '\nprocesses:\n'
    pgrep -a -u ${cfg.user} gamescope || true
    pgrep -a -u ${cfg.user} es-de || true

    printf '\nconnected outputs:\n'
    for status in /sys/class/drm/card*-*/status; do
      [ -e "$status" ] || continue
      if grep -qx connected "$status"; then
        output="''${status%/status}"
        printf '%s\n' "''${output##*/}"
        [ -r "$output/modes" ] && sed -n '1,8p' "$output/modes"
      fi
    done

    printf '\ndisplay profile:\n'
    display-profile | jq . || true

    printf '\nlatest ES-DE session log:\n'
    latest="$(find "${cfg.dataRoot}/logs/esde-session" -type f -name '*.log' -printf '%T@ %p\n' 2>/dev/null | sort -nr | sed -n '1s/^[^ ]* //p')"
    if [ -n "$latest" ]; then
      printf '%s\n' "$latest"
      tail -n 60 "$latest" || true
    else
      printf 'none\n'
    fi

    printf '\nrecent service journal:\n'
    journalctl -u emulation-session.service -n 80 --no-pager || true
  '';

  emulationSession = pkgs.writeShellScriptBin "emulation-session" ''
    set -euo pipefail
    export PATH=${emu.scriptPath}:${
      lib.makeBinPath (
        [
          syncEsdeConfig
          config.ghostship.emulation.internal.scripts.audioRoute
          config.ghostship.emulation.internal.scripts.displayProfile
          packages.esdePackage
          pkgs.gamescope
          pkgs.jq
          pkgs.vulkan-tools
        ]
        ++ config.ghostship.emulation.internal.setupScripts
      )
    }:$PATH
    export ESDE_APPDATA_DIR="${cfg.esde.appDataDir}"
    export XDG_RUNTIME_DIR="''${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
    if [ -S "$XDG_RUNTIME_DIR/bus" ]; then
      export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"
    fi
    export XDG_DATA_HOME="${cfg.dataRoot}/xdg/share"
    export XDG_CONFIG_HOME="${cfg.dataRoot}/xdg/config"
    export XDG_CACHE_HOME="${cfg.dataRoot}/xdg/cache"
    export TMPDIR="${cfg.dataRoot}/tmp"
    export SDL_GAMECONTROLLERCONFIG_FILE="${cfg.configRoot}/controllers/gamecontrollerdb.txt"
    export SDL_GAMECONTROLLER_USE_BUTTON_LABELS=1
    export MESA_VK_DEVICE_SELECT="''${MESA_VK_DEVICE_SELECT:-1002:73ef}"
    export DRI_PRIME="''${DRI_PRIME:-1}"

    log_dir="${cfg.dataRoot}/logs/esde-session"
    mkdir -p "$log_dir"
    log_file="$log_dir/$(date -u +%Y%m%dT%H%M%SZ).log"
    exec > >(tee -a "$log_file") 2>&1
    echo "$(date -u +%FT%TZ) starting ES-DE session"
    echo "XDG_RUNTIME_DIR=$XDG_RUNTIME_DIR"
    echo "MESA_VK_DEVICE_SELECT=$MESA_VK_DEVICE_SELECT"
    grep '^Cap' /proc/$$/status || true
    audio-route || true

    if [ "$(id -u)" = 0 ]; then
      sync-esde-config
      ${lib.concatMapStringsSep "\n" (
        pkg: "${lib.getExe pkg}"
      ) config.ghostship.emulation.internal.setupScripts}
    elif [ ! -d "${cfg.esde.appDataDir}/custom_systems" ]; then
      echo "emulation state is not prepared yet; run sync-esde-config as root."
      exit 1
    fi
    if [ "''${EMULATION_ESDE_NO_GAMESCOPE:-0}" = "1" ]; then
      exec es-de --no-update-check --no-splash
    fi

    profile_json=""
    for attempt in $(seq 1 20); do
      profile_json="$(display-profile || true)"
      if [ -n "$profile_json" ] && jq -e '.connected == true' <<<"$profile_json" >/dev/null 2>&1; then
        break
      fi
      echo "$(date -u +%FT%TZ) waiting for a connected display ($attempt/20)"
      sleep 1
    done
    if [ -z "$profile_json" ]; then
      profile_json="$(display-profile)"
    fi

    drm_device="$(jq -r '.drm_device // empty' <<<"$profile_json")"
    if [ -n "$drm_device" ]; then
      drm_devices="$drm_device"
      for card in /dev/dri/card*; do
        [ -e "$card" ] || continue
        [ "$card" = "$drm_device" ] && continue
        drm_devices="$drm_devices:$card"
      done
      export WLR_DRM_DEVICES="$drm_devices"
    fi
    if ! vulkaninfo --summary 2>/dev/null | grep -Eq "deviceID[[:space:]]*=[[:space:]]*0x73ef|AMD Radeon RX 6650M"; then
      unset MESA_VK_DEVICE_SELECT
    fi
    profile_compact="$(jq -c . <<<"$profile_json" 2>/dev/null || printf '%s' "$profile_json")"
    echo "display-profile=$profile_compact"
    echo "WLR_DRM_DEVICES=''${WLR_DRM_DEVICES:-unset}"
    mapfile -t gamescope_args < <(jq -r '.frontend_gamescope_args[]' <<<"$profile_json")
    exec gamescope "''${gamescope_args[@]}" -- es-de --no-update-check --no-splash
  '';

  startEsde = pkgs.writeShellScriptBin "start-esde" ''
    set -euo pipefail
    if [ "$(id -u)" != 0 ]; then
      exec ${lib.getExe emulationSession}
    fi
    exec ${pkgs.systemd}/bin/systemctl start emulation-session.service
  '';

  stopEsde = pkgs.writeShellScriptBin "stop-esde" ''
    set -euo pipefail
    exec ${pkgs.systemd}/bin/systemctl stop emulation-session.service
  '';
in
{
  config = lib.mkIf cfg.enable (
    lib.mkMerge [
      {
        ghostship.emulation.internal.scripts = {
          inherit
            emulationSession
            esdePreflight
            esdeStatus
            startEsde
            stopEsde
            syncEsdeConfig
            ;
        };

        systemd.services.emulation-session = {
          description = "Launch ES-DE emulation session";
          after = [
            "emulation-setup.service"
            "systemd-user-sessions.service"
          ];
          wants = [ "emulation-setup.service" ];
          conflicts = lib.optionals (cfg.startup.mode == "console") [ "getty@tty1.service" ];
          serviceConfig = {
            User = cfg.user;
            Group = cfg.group;
            WorkingDirectory = "/home/${cfg.user}";
            PAMName = "login";
            TTYPath = "/dev/tty1";
            TTYReset = true;
            TTYVHangup = true;
            TTYVTDisallocate = true;
            StandardInput = "tty";
            StandardOutput = "journal+console";
            StandardError = "journal+console";
            Restart = "no";
            CapabilityBoundingSet = "";
            AmbientCapabilities = "";
            NoNewPrivileges = true;
          }
          // lib.optionalAttrs (cfg.startup.mode == "console") {
            ExecStopPost = "+${pkgs.systemd}/bin/systemctl start getty@tty1.service";
          };
          script = ''
            exec ${lib.getExe emulationSession}
          '';
        };

        systemd.services.emulation-setup = {
          description = "Prepare emulation runtime state";
          wantedBy = [ "multi-user.target" ];
          before = lib.optionals (cfg.startup.mode == "kiosk") [ "greetd.service" ];
          serviceConfig = {
            Type = "oneshot";
            RemainAfterExit = true;
          };
          path = [ syncEsdeConfig ] ++ config.ghostship.emulation.internal.setupScripts;
          script = ''
            sync-esde-config
            ${lib.concatMapStringsSep "\n" (
              pkg: "${lib.getExe pkg}"
            ) config.ghostship.emulation.internal.setupScripts}
          '';
        };
      }

      (lib.mkIf (cfg.startup.mode == "kiosk") {
        services.greetd = {
          enable = true;
          settings.default_session = {
            command = "${lib.getExe emulationSession}";
            user = cfg.user;
          };
        };
      })

      (lib.mkIf (cfg.startup.mode == "console") {
        services.greetd.enable = lib.mkForce false;
        services.getty.autologinUser = cfg.user;
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
            if (unit == "emulation-session.service" &&
                (verb == "start" || verb == "stop" || verb == "restart")) {
              return polkit.Result.YES;
            }
          });
        '';
      })
    ]
  );
}
