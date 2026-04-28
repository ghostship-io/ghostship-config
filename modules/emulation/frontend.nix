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
      <command>boomer-run-emulator ${emu.xmlEscape system.id} ${emu.xmlEscape system.emulator} %ROM%</command>
      <platform>${emu.xmlEscape system.platform}</platform>
      <theme>${emu.xmlEscape system.theme}</theme>
    </system>'';

  esSystemsXml = pkgs.writeText "boomer-es-systems.xml" ''
    <?xml version="1.0"?>
    <systemList>
    ${lib.concatMapStringsSep "\n" mkSystemXml emu.allSystems}
      <system>
        <name>tools</name>
        <fullname>Tools</fullname>
        <path>${emu.xmlEscape "${cfg.dataRoot}/tools"}</path>
        <extension>.sh .SH</extension>
        <command>%ROM%</command>
        <platform>tools</platform>
        <theme>tools</theme>
      </system>
    </systemList>
  '';

  esFindRulesXml = pkgs.writeText "boomer-es-find-rules.xml" ''
    <?xml version="1.0"?>
    <ruleList>
      <emulator name="BOOMER_WRAPPER">
        <rule type="systempath">
          <entry>boomer-run-emulator</entry>
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

  esSettingsXml = pkgs.writeText "boomer-es-settings.xml" ''
    <?xml version="1.0"?>
    <settings>
      <string name="ThemeSet" value="art-book-next-es-de" />
      <string name="Scraper" value="screenscraper" />
      <string name="ScraperRegion" value="na" />
      <string name="ScraperLanguage" value="en" />
      <string name="MediaDirectory" value="${emu.xmlEscape "${cfg.esde.appDataDir}/downloaded_media"}" />
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

  boomerSyncEsdeConfig = pkgs.writeShellScriptBin "boomer-sync-esde-config" ''
    set -euo pipefail
    export PATH=${emu.scriptPath}:${
      lib.makeBinPath (
        [
          pkgs.jq
        ]
        ++ lib.optional (
          config.ghostship.emulation.internal.scripts ? boomerRenderScraperSettings
        ) config.ghostship.emulation.internal.scripts.boomerRenderScraperSettings
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
      "${cfg.dataRoot}/logs" \
      "${cfg.dataRoot}/logs/esde-session" \
      "${cfg.dataRoot}/logs/launches" \
      "${cfg.dataRoot}/tmp" \
      "${cfg.dataRoot}/tools" \
      "${cfg.esde.appDataDir}" \
      "${cfg.esde.appDataDir}/custom_systems" \
      "${cfg.esde.appDataDir}/settings" \
      "${cfg.esde.appDataDir}/themes" \
      "${cfg.esde.appDataDir}/scripts"

    install -D -m 0644 -o ${cfg.user} -g ${cfg.group} ${esSystemsXml} "${cfg.esde.appDataDir}/custom_systems/es_systems.xml"
    install -D -m 0644 -o ${cfg.user} -g ${cfg.group} ${esFindRulesXml} "${cfg.esde.appDataDir}/custom_systems/es_find_rules.xml"
    if [ ! -e "${cfg.esde.appDataDir}/settings/es_settings.xml" ]; then
      install -D -m 0640 -o ${cfg.user} -g ${cfg.group} ${esSettingsXml} "${cfg.esde.appDataDir}/settings/es_settings.xml"
    fi

    ln -sfn ${packages.artBookNext}/share/es-de/themes/art-book-next-es-de "${cfg.esde.appDataDir}/themes/art-book-next-es-de"

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

    ln -sfn "${cfg.dataRoot}" /home/${cfg.user}/Emulation
    chown -h ${cfg.user}:${cfg.group} /home/${cfg.user}/Emulation || true
    if command -v boomer-render-esde-scraper-settings >/dev/null 2>&1; then
      boomer-render-esde-scraper-settings || true
    fi
  '';

  boomerEsdePreflight = pkgs.writeShellScriptBin "boomer-esde-preflight" ''
    set -u
    export PATH=${emu.scriptPath}:${
      lib.makeBinPath [
        packages.esdePackage
        pkgs.gamescope
        pkgs.util-linux
        pkgs.vulkan-tools
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
    check "DRM card1 exists" test -e /dev/dri/card1
    check "kiosk can read/write DRM card1" runuser -u ${cfg.user} -- test -w /dev/dri/card1
    check "kiosk can access render nodes" sh -c 'runuser -u ${cfg.user} -- sh -c "test -w /dev/dri/renderD128 || test -w /dev/dri/renderD129"'
    check "HDMI-A-2 is connected" sh -c 'grep -qx connected /sys/class/drm/card1-HDMI-A-2/status'
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

  boomerEsdeStatus = pkgs.writeShellScriptBin "boomer-esde-status" ''
    set -euo pipefail
    export PATH=${emu.scriptPath}:${
      lib.makeBinPath [
        pkgs.procps
        pkgs.systemd
      ]
    }:$PATH

    printf 'boomer-emulation-session: '
    systemctl is-active boomer-emulation-session.service || true

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

    printf '\nlatest ES-DE session log:\n'
    latest="$(find "${cfg.dataRoot}/logs/esde-session" -type f -name '*.log' -printf '%T@ %p\n' 2>/dev/null | sort -nr | sed -n '1s/^[^ ]* //p')"
    if [ -n "$latest" ]; then
      printf '%s\n' "$latest"
      tail -n 60 "$latest" || true
    else
      printf 'none\n'
    fi

    printf '\nrecent service journal:\n'
    journalctl -u boomer-emulation-session.service -n 80 --no-pager || true
  '';

  boomerEmulationSession = pkgs.writeShellScriptBin "boomer-emulation-session" ''
    set -euo pipefail
    export PATH=${emu.scriptPath}:${
      lib.makeBinPath (
        [
          boomerSyncEsdeConfig
          packages.esdePackage
          pkgs.gamescope
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
    export MESA_VK_DEVICE_SELECT="''${MESA_VK_DEVICE_SELECT:-1002:73ef}"
    export DRI_PRIME="''${DRI_PRIME:-1}"
    if [ -e /dev/dri/card1 ]; then
      drm_devices="/dev/dri/card1"
      [ -e /dev/dri/card0 ] && drm_devices="$drm_devices:/dev/dri/card0"
      export WLR_DRM_DEVICES="$drm_devices"
    fi

    log_dir="${cfg.dataRoot}/logs/esde-session"
    mkdir -p "$log_dir"
    log_file="$log_dir/$(date -u +%Y%m%dT%H%M%SZ).log"
    exec > >(tee -a "$log_file") 2>&1
    echo "$(date -u +%FT%TZ) starting Boomer ES-DE session"
    echo "XDG_RUNTIME_DIR=$XDG_RUNTIME_DIR"
    echo "MESA_VK_DEVICE_SELECT=$MESA_VK_DEVICE_SELECT"
    echo "WLR_DRM_DEVICES=''${WLR_DRM_DEVICES:-unset}"
    grep '^Cap' /proc/$$/status || true

    if [ "$(id -u)" = 0 ]; then
      boomer-sync-esde-config
      ${lib.concatMapStringsSep "\n" (
        pkg: "${lib.getExe pkg}"
      ) config.ghostship.emulation.internal.setupScripts}
    elif [ ! -d "${cfg.esde.appDataDir}/custom_systems" ]; then
      echo "Boomer emulation state is not prepared yet; run boomer-sync-esde-config as root."
      exit 1
    fi
    if [ "''${BOOMER_ESDE_NO_GAMESCOPE:-0}" = "1" ]; then
      exec es-de --no-update-check --no-splash
    fi
    exec gamescope --backend drm -f --prefer-vk-device 1002:73ef --prefer-output HDMI-A-2 --force-windows-fullscreen -- es-de --no-update-check --no-splash
  '';

  boomerStartEsde = pkgs.writeShellScriptBin "boomer-start-esde" ''
    set -euo pipefail
    if [ "$(id -u)" != 0 ]; then
      exec ${lib.getExe boomerEmulationSession}
    fi
    exec ${pkgs.systemd}/bin/systemctl start boomer-emulation-session.service
  '';

  boomerStopEsde = pkgs.writeShellScriptBin "boomer-stop-esde" ''
    set -euo pipefail
    exec ${pkgs.systemd}/bin/systemctl stop boomer-emulation-session.service
  '';
in
{
  config = lib.mkIf cfg.enable (
    lib.mkMerge [
      {
        ghostship.emulation.internal.scripts = {
          inherit
            boomerEmulationSession
            boomerEsdePreflight
            boomerEsdeStatus
            boomerStartEsde
            boomerStopEsde
            boomerSyncEsdeConfig
            ;
        };

        systemd.services.boomer-emulation-session = {
          description = "Launch Boomer Kuwanger ES-DE session";
          after = [
            "boomer-emulation-setup.service"
            "systemd-user-sessions.service"
          ];
          wants = [ "boomer-emulation-setup.service" ];
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
            exec ${lib.getExe boomerEmulationSession}
          '';
        };

        systemd.services.boomer-emulation-setup = {
          description = "Prepare Boomer Kuwanger emulation runtime state";
          wantedBy = [ "multi-user.target" ];
          before = lib.optionals (cfg.startup.mode == "kiosk") [ "greetd.service" ];
          serviceConfig = {
            Type = "oneshot";
            RemainAfterExit = true;
          };
          path = [ boomerSyncEsdeConfig ] ++ config.ghostship.emulation.internal.setupScripts;
          script = ''
            boomer-sync-esde-config
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
            command = "${lib.getExe boomerEmulationSession}";
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
            if (unit == "boomer-emulation-session.service" &&
                (verb == "start" || verb == "stop" || verb == "restart")) {
              return polkit.Result.YES;
            }
          });
        '';
      })
    ]
  );
}
