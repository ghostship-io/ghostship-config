{ config, lib, pkgs, ... }:

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
    export PATH=${emu.scriptPath}:${lib.makeBinPath ([
      pkgs.jq
    ] ++ lib.optional (config.ghostship.emulation.internal.scripts ? boomerRenderScraperSettings) config.ghostship.emulation.internal.scripts.boomerRenderScraperSettings)}:$PATH

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
      "${cfg.dataRoot}/logs/launches" \
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

  boomerEmulationSession = pkgs.writeShellScriptBin "boomer-emulation-session" ''
    set -euo pipefail
    export PATH=${emu.scriptPath}:${lib.makeBinPath ([ boomerSyncEsdeConfig packages.esdePackage pkgs.gamescope ] ++ config.ghostship.emulation.internal.setupScripts)}:$PATH
    export ESDE_APPDATA_DIR="${cfg.esde.appDataDir}"
    export XDG_DATA_HOME="${cfg.dataRoot}/xdg/share"
    export XDG_CONFIG_HOME="${cfg.dataRoot}/xdg/config"
    export XDG_CACHE_HOME="/fast/emulation/xdg/cache"
    export TMPDIR="/fast/emulation/tmp"
    export SDL_GAMECONTROLLERCONFIG_FILE="${cfg.configRoot}/controllers/gamecontrollerdb.txt"
    boomer-sync-esde-config
    ${lib.concatMapStringsSep "\n" (pkg: "${lib.getExe pkg}") config.ghostship.emulation.internal.setupScripts}
    if [ "''${BOOMER_ESDE_NO_GAMESCOPE:-0}" = "1" ]; then
      exec es-de --fullscreen
    fi
    exec gamescope -f -e -- es-de --fullscreen
  '';
in
{
  config = lib.mkIf cfg.enable {
    ghostship.emulation.internal.scripts = {
      inherit boomerEmulationSession boomerSyncEsdeConfig;
    };

    services.greetd = {
      enable = true;
      settings.default_session = {
        command = "${lib.getExe boomerEmulationSession}";
        user = cfg.user;
      };
    };

    systemd.services.boomer-emulation-setup = {
      description = "Prepare Boomer Kuwanger emulation runtime state";
      wantedBy = [ "multi-user.target" ];
      before = [ "greetd.service" ];
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
      };
      path = [ boomerSyncEsdeConfig ] ++ config.ghostship.emulation.internal.setupScripts;
      script = ''
        boomer-sync-esde-config
        ${lib.concatMapStringsSep "\n" (pkg: "${lib.getExe pkg}") config.ghostship.emulation.internal.setupScripts}
      '';
    };
  };
}
