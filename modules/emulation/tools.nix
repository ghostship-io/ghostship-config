{ config, lib, pkgs, ... }:

let
  cfg = config.ghostship.emulation;
  emu = config.ghostship.emulation.internal.lib;

  terminalTool = pkgs.writeShellScriptBin "terminal-tool" ''
    set -euo pipefail
    export PATH=${emu.scriptPath}:${lib.makeBinPath [ pkgs.foot ]}:$PATH
    title="''${1:-Emulation Tool}"
    command="''${2:-true}"
    if [ -n "''${WAYLAND_DISPLAY:-}" ] && command -v foot >/dev/null 2>&1; then
      exec foot -T "$title" sh -lc "$command; status=\$?; printf '\n%s\n' 'Press Enter to close.'; read -r _; exit \$status"
    fi
    exec sh -lc "$command"
  '';

  toolMenu = pkgs.writeShellScriptBin "tool-menu" ''
    set -euo pipefail
    export PATH=${emu.scriptPath}:$PATH
    title="''${1:-Emulation Tool}"
    shift || true
    labels=()
    commands=()
    while [ "$#" -ge 2 ]; do
      labels+=("$1")
      commands+=("$2")
      shift 2
    done
    while true; do
      clear 2>/dev/null || true
      printf '%s\n\n' "$title"
      i=1
      for label in "''${labels[@]}"; do
        printf '%2d. %s\n' "$i" "$label"
        i=$((i + 1))
      done
      printf '\nq. Back\n\n> '
      read -r choice
      case "$choice" in
        q|Q|"") exit 0 ;;
        *[!0-9]*) continue ;;
      esac
      if [ "$choice" -lt 1 ] || [ "$choice" -gt "''${#commands[@]}" ]; then
        continue
      fi
      command="''${commands[$((choice - 1))]}"
      clear 2>/dev/null || true
      sh -lc "$command"
      printf '\n%s\n' 'Press Enter to return to the menu.'
      read -r _
    done
  '';

  mkMenuCommand = title: items:
    "tool-menu ${lib.escapeShellArg title} "
    + lib.concatMapStringsSep " " (item: "${lib.escapeShellArg item.label} ${lib.escapeShellArg item.command}") items;

  mkMenuTool = name: title: items:
    pkgs.writeShellScriptBin name ''
      set -euo pipefail
      export PATH=${emu.scriptPath}:${lib.makeBinPath ([
        terminalTool
        toolMenu
        config.ghostship.emulation.internal.packages.retroarchPackage
      ] ++ lib.optionals (config.ghostship.emulation.internal.scripts ? displayProfile) [ config.ghostship.emulation.internal.scripts.displayProfile ]
      ++ lib.optionals (config.ghostship.emulation.internal.scripts ? renderScraperSettings) [ config.ghostship.emulation.internal.scripts.renderScraperSettings ]
      ++ lib.optionals (config.ghostship.emulation.internal.scripts ? retroarchShaderSmokeTest) [ config.ghostship.emulation.internal.scripts.retroarchShaderSmokeTest ]
      ++ lib.optionals (config.ghostship.emulation.internal.scripts ? romCoverageCheck) [ config.ghostship.emulation.internal.scripts.romCoverageCheck ]
      ++ lib.optionals (config.ghostship.emulation.internal.scripts ? smokeRomSelect) [ config.ghostship.emulation.internal.scripts.smokeRomSelect ]
      ++ lib.optionals (config.ghostship.emulation.internal.scripts ? smokeRomSync) [ config.ghostship.emulation.internal.scripts.smokeRomSync ]
      ++ lib.optionals (config.ghostship.emulation.internal.scripts ? smokeTest) [ config.ghostship.emulation.internal.scripts.smokeTest ]
      ++ lib.optionals (config.ghostship.emulation.internal.scripts ? smokeReport) [ config.ghostship.emulation.internal.scripts.smokeReport ])}:$PATH
      exec terminal-tool ${lib.escapeShellArg title} ${lib.escapeShellArg (mkMenuCommand title items)}
    '';

  profileMenuCommand = ''
    profile_dir="${cfg.configRoot}/retroarch/profiles"
    current="$profile_dir/current.cfg"
    mkdir -p "$profile_dir"
    echo "Current profile:"
    readlink "$current" 2>/dev/null || echo "custom or missing"
    echo
    echo "Available profiles:"
    find "$profile_dir" -maxdepth 1 -type f -name "*.cfg" -printf "%f\n" | sort
    echo
    printf "Profile name to activate, or blank to keep current: "
    read -r profile
    [ -n "$profile" ] || exit 0
    case "$profile" in *.cfg) ;; *) profile="$profile.cfg" ;; esac
    if [ ! -r "$profile_dir/$profile" ]; then
      echo "Unknown profile: $profile"
      exit 1
    fi
    backup="$profile_dir/current.cfg.$(date -u +%Y%m%dT%H%M%SZ).bak"
    [ -e "$current" ] && cp -P "$current" "$backup" || true
    ln -sfn "$profile" "$current"
    echo "Activated $profile"
  '';

  playerAssignmentCommand = ''
    order="${cfg.configRoot}/controllers/player-order.json"
    mkdir -p "$(dirname "$order")"
    case "''${action:-show}" in
      show)
        [ -r "$order" ] && jq . "$order" || echo '{"players":[]}'
        ;;
      rebuild)
        bluetoothctl devices Connected | awk '{mac=$2; $1=$2=""; sub(/^  */, ""); print mac "\t" $0}' \
          | jq -R -s 'split("\n") | map(select(length > 0)) | map(split("\t")) | {players: [to_entries[] | {player:(.key + 1), mac:.value[0], name:.value[1], connected:true}]} ' >"$order.tmp"
        mv "$order.tmp" "$order"
        jq . "$order"
        ;;
      rotate)
        [ -r "$order" ] || echo '{"players":[]}' >"$order"
        jq '.players |= (if length > 1 then .[1:] + .[:1] else . end) | .players |= [to_entries[] | .value + {player:(.key + 1)}]' "$order" >"$order.tmp"
        mv "$order.tmp" "$order"
        jq . "$order"
        ;;
      clear)
        echo '{"players":[]}' >"$order"
        jq . "$order"
        ;;
    esac
  '';

  toolScripts = {
    wifi-status = mkMenuTool "wifi-status" "Wi-Fi Status" [
      { label = "Radio status"; command = "nmcli radio; echo; nmcli device status || true"; }
      { label = "Active connections"; command = "nmcli connection show --active"; }
      { label = "Force 5 GHz profiles"; command = "rfkill unblock wlan || true; nmcli networking on || true; nmcli radio wifi on || true; nmcli -t -f UUID,TYPE connection show | while IFS=: read -r uuid type; do [ \"$type\" = \"802-11-wireless\" ] && nmcli connection modify \"$uuid\" connection.interface-name \"\" 802-11-wireless.band a connection.autoconnect yes connection.autoconnect-priority 100 || true; done; nmcli radio; nmcli connection show --active"; }
    ];
    wifi-connect = mkMenuTool "wifi-connect" "Wi-Fi Connect" [
      { label = "Open NetworkManager TUI"; command = "rfkill unblock wlan || true; nmcli networking on || true; nmcli radio wifi on || true; nmtui; nmcli -t -f UUID,TYPE connection show | while IFS=: read -r uuid type; do [ \"$type\" = \"802-11-wireless\" ] && nmcli connection modify \"$uuid\" connection.interface-name \"\" 802-11-wireless.band a connection.autoconnect yes connection.autoconnect-priority 100 || true; done"; }
      { label = "Show nearby networks"; command = "rfkill unblock wlan || true; nmcli radio wifi on || true; nmcli device wifi list || true"; }
    ];
    bluetooth-status = mkMenuTool "bluetooth-status" "Bluetooth Status" [
      { label = "Adapter status"; command = "bluetoothctl show"; }
      { label = "Paired devices"; command = "bluetoothctl devices Paired"; }
      { label = "Connected devices"; command = "bluetoothctl devices Connected"; }
      { label = "Controller order"; command = "[ -r ${cfg.configRoot}/controllers/player-order.json ] && jq . ${cfg.configRoot}/controllers/player-order.json || true"; }
    ];
    bluetooth-pair-controller = mkMenuTool "bluetooth-pair-controller" "Bluetooth Pair Controller" [
      { label = "Interactive pair/trust/connect"; command = "bluetoothctl power on; bluetoothctl agent on; bluetoothctl default-agent; echo 'Put the controller in pairing mode, then use scan/pair/trust/connect.'; bluetoothctl"; }
      { label = "Start scan for 30 seconds"; command = "bluetoothctl power on; timeout 30s bluetoothctl scan on || true"; }
    ];
    bluetooth-reconnect-controllers = mkMenuTool "bluetooth-reconnect-controllers" "Bluetooth Reconnect Controllers" [
      { label = "Reconnect all paired devices"; command = "bluetoothctl devices Paired | awk '{print $2}' | while read -r mac; do bluetoothctl trust \"$mac\" || true; bluetoothctl connect \"$mac\" || true; done; bluetoothctl devices Connected"; }
      { label = "Power-cycle Bluetooth adapter"; command = "bluetoothctl power off; sleep 2; bluetoothctl power on; bluetoothctl devices Paired"; }
    ];
    player-assignment = mkMenuTool "player-assignment" "Player Assignment" [
      { label = "Show current order"; command = "action=show; ${playerAssignmentCommand}"; }
      { label = "Rebuild from connected controllers"; command = "action=rebuild; ${playerAssignmentCommand}"; }
      { label = "Rotate players"; command = "action=rotate; ${playerAssignmentCommand}"; }
      { label = "Clear saved order"; command = "action=clear; ${playerAssignmentCommand}"; }
    ];
    display-profile-tool = mkMenuTool "display-profile-tool" "Display Profile Test" [
      { label = "Current profile"; command = "display-profile | jq ."; }
      { label = "Resolution matrix"; command = "display-profile --matrix-test | jq ."; }
      { label = "Gamescope args"; command = "display-profile gamescope-args"; }
    ];
    display-profile-override = mkMenuTool "display-profile-override" "Display Profile Override" [
      { label = "Show current override"; command = "[ -r ${cfg.configRoot}/display.env ] && cat ${cfg.configRoot}/display.env || echo 'No override file.'"; }
      { label = "Write disabled template"; command = "cat > ${cfg.configRoot}/display.env <<'EOF'\n# EMULATION_DISPLAY_WIDTH=3840\n# EMULATION_DISPLAY_HEIGHT=2160\n# EMULATION_RENDER_SIZE=2954x1662\n# EMULATION_FORCE_FSR=1\n# EMULATION_DISABLE_FSR=1\nEOF\ncat ${cfg.configRoot}/display.env"; }
    ];
    retroarch-core-status = mkMenuTool "retroarch-core-status" "RetroArch Core Status" [
      { label = "RetroArch version"; command = "retroarch --version | head -n 1"; }
      { label = "Installed cores"; command = "find ${config.ghostship.emulation.internal.packages.retroarchPackage}/lib/retroarch/cores -maxdepth 1 -name '*_libretro.so' -printf '%f\\n' | sort"; }
      { label = "Shader smoke test"; command = "retroarch-shader-smoke-test || true"; }
      { label = "Update workflow"; command = "echo 'RetroArch cores are Nix-managed. Rebuild the host with: nix build .#nixosConfigurations.boomer-kuwanger.config.system.build.toplevel -L'"; }
    ];
    retroarch-graphics-profiles = mkMenuTool "retroarch-graphics-profiles" "RetroArch Graphics Profiles" [
      { label = "Show/switch profile"; command = profileMenuCommand; }
      { label = "System overrides"; command = "find ${cfg.configRoot}/retroarch/system-overrides -maxdepth 1 -type f -printf '%f\\n' | sort"; }
    ];
    retroarch-shader-profiles = mkMenuTool "retroarch-shader-profiles" "RetroArch Shader Profiles" [
      { label = "Show/switch profile"; command = profileMenuCommand; }
      { label = "Shader policy"; command = "jq . ${cfg.configRoot}/retroarch/shader-policy.json"; }
      { label = "Shader smoke test"; command = "retroarch-shader-smoke-test || true"; }
    ];
    esde-scraper-status = mkMenuTool "esde-scraper-status" "ES-DE Scraper Status" [
      { label = "Secret projection"; command = "ls -l /run/ghostship-secrets/emulation-scraper.env 2>/dev/null || echo 'No decrypted scraper projection.'"; }
      { label = "Projected settings"; command = "render-esde-scraper-settings || true; grep -E 'Scraper|Miximage|ScreenScraper' ${cfg.esde.appDataDir}/settings/es_settings.xml || true"; }
      { label = "Rekey reminder"; command = "echo 'After changing emulation-scraper-secrets recipients, run secret-rekey.'"; }
    ];
    esde-scrape-missing-media = mkMenuTool "esde-scrape-missing-media" "ES-DE Scrape Missing Media" [
      { label = "Prepare scraper settings"; command = "render-esde-scraper-settings || true; echo 'Open ES-DE > Main Menu > Scraper. Missing-media scrape uses the projected ScreenScraper settings when available.'"; }
    ];
    launch-log-review = mkMenuTool "launch-log-review" "Launch Log Review" [
      { label = "Latest launch log"; command = "latest=$(find ${cfg.dataRoot}/logs/launches -type f -name '*.jsonl' 2>/dev/null | sort | tail -n 1); [ -n \"$latest\" ] && jq . \"$latest\" || echo 'No launch logs yet.'"; }
      { label = "Launch log files"; command = "find ${cfg.dataRoot}/logs/launches -type f -name '*.jsonl' 2>/dev/null | sort | tail -n 25"; }
    ];
    rom-coverage-check-tool = mkMenuTool "rom-coverage-check-tool" "ROM Coverage Check" [
      { label = "Check /mnt/z source"; command = "rom-coverage-check /mnt/z/Library/ROMs/roms || true"; }
      { label = "Check local ROM root"; command = "rom-coverage-check ${cfg.romRoot} || true"; }
    ];
    smoke-tests = mkMenuTool "smoke-tests" "Smoke Tests" [
      { label = "Select smoke ROMs"; command = "smoke-rom-select"; }
      { label = "Sync smoke ROMs"; command = "smoke-rom-sync"; }
      { label = "Dry-run launches"; command = "smoke-test --dry-run"; }
      { label = "Run smoke test"; command = "smoke-test"; }
      { label = "Latest report"; command = "smoke-report"; }
    ];
    restart-esde = pkgs.writeShellScriptBin "restart-esde" ''
      set -euo pipefail
      systemctl restart emulation-session.service
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
    ghostship.emulation.internal.scripts = toolScripts // {
      inherit terminalTool toolMenu syncEsdeTools;
    };
    ghostship.emulation.internal.setupScripts = [ syncEsdeTools ];
  };
}
