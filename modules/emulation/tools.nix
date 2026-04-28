{ config, lib, pkgs, ... }:

let
  cfg = config.ghostship.emulation;
  emu = config.ghostship.emulation.internal.lib;

  boomerTerminalTool = pkgs.writeShellScriptBin "boomer-terminal-tool" ''
    set -euo pipefail
    export PATH=${emu.scriptPath}:${lib.makeBinPath [ pkgs.foot ]}:$PATH
    title="''${1:-Boomer Tool}"
    command="''${2:-true}"
    if [ -n "''${WAYLAND_DISPLAY:-}" ] && command -v foot >/dev/null 2>&1; then
      exec foot -T "$title" sh -lc "$command; status=\$?; printf '\n%s\n' 'Press Enter to close.'; read -r _; exit \$status"
    fi
    exec sh -lc "$command"
  '';

  boomerToolMenu = pkgs.writeShellScriptBin "boomer-tool-menu" ''
    set -euo pipefail
    export PATH=${emu.scriptPath}:$PATH
    title="''${1:-Boomer Tool}"
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
    "boomer-tool-menu ${lib.escapeShellArg title} "
    + lib.concatMapStringsSep " " (item: "${lib.escapeShellArg item.label} ${lib.escapeShellArg item.command}") items;

  mkMenuTool = name: title: items:
    pkgs.writeShellScriptBin name ''
      set -euo pipefail
      export PATH=${emu.scriptPath}:${lib.makeBinPath ([
        boomerTerminalTool
        boomerToolMenu
        config.ghostship.emulation.internal.packages.retroarchPackage
      ] ++ lib.optionals (config.ghostship.emulation.internal.scripts ? boomerDisplayProfile) [ config.ghostship.emulation.internal.scripts.boomerDisplayProfile ]
      ++ lib.optionals (config.ghostship.emulation.internal.scripts ? boomerRenderScraperSettings) [ config.ghostship.emulation.internal.scripts.boomerRenderScraperSettings ]
      ++ lib.optionals (config.ghostship.emulation.internal.scripts ? boomerRetroarchShaderSmokeTest) [ config.ghostship.emulation.internal.scripts.boomerRetroarchShaderSmokeTest ]
      ++ lib.optionals (config.ghostship.emulation.internal.scripts ? boomerRomCoverageCheck) [ config.ghostship.emulation.internal.scripts.boomerRomCoverageCheck ])}:$PATH
      exec boomer-terminal-tool ${lib.escapeShellArg title} ${lib.escapeShellArg (mkMenuCommand title items)}
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
    boomer-wifi-status = mkMenuTool "boomer-wifi-status" "Wi-Fi Status" [
      { label = "Radio status"; command = "nmcli radio; echo; nmcli device status || true"; }
      { label = "Disable Wi-Fi"; command = "nmcli radio wifi off || true; rfkill block wlan || true; nmcli radio"; }
      { label = "Enable Wi-Fi temporarily"; command = "rfkill unblock wlan || true; nmcli radio wifi on || true; nmcli radio"; }
    ];
    boomer-wifi-connect = mkMenuTool "boomer-wifi-connect" "Wi-Fi Connect" [
      { label = "Open NetworkManager TUI"; command = "rfkill unblock wlan || true; nmcli radio wifi on || true; nmtui"; }
      { label = "Show nearby networks"; command = "rfkill unblock wlan || true; nmcli radio wifi on || true; nmcli device wifi list || true"; }
    ];
    boomer-bluetooth-status = mkMenuTool "boomer-bluetooth-status" "Bluetooth Status" [
      { label = "Adapter status"; command = "bluetoothctl show"; }
      { label = "Paired devices"; command = "bluetoothctl devices Paired"; }
      { label = "Connected devices"; command = "bluetoothctl devices Connected"; }
      { label = "Controller order"; command = "[ -r ${cfg.configRoot}/controllers/player-order.json ] && jq . ${cfg.configRoot}/controllers/player-order.json || true"; }
    ];
    boomer-bluetooth-pair-controller = mkMenuTool "boomer-bluetooth-pair-controller" "Bluetooth Pair Controller" [
      { label = "Interactive pair/trust/connect"; command = "bluetoothctl power on; bluetoothctl agent on; bluetoothctl default-agent; echo 'Put the controller in pairing mode, then use scan/pair/trust/connect.'; bluetoothctl"; }
      { label = "Start scan for 30 seconds"; command = "bluetoothctl power on; timeout 30s bluetoothctl scan on || true"; }
    ];
    boomer-bluetooth-reconnect-controllers = mkMenuTool "boomer-bluetooth-reconnect-controllers" "Bluetooth Reconnect Controllers" [
      { label = "Reconnect all paired devices"; command = "bluetoothctl devices Paired | awk '{print $2}' | while read -r mac; do bluetoothctl trust \"$mac\" || true; bluetoothctl connect \"$mac\" || true; done; bluetoothctl devices Connected"; }
      { label = "Power-cycle Bluetooth adapter"; command = "bluetoothctl power off; sleep 2; bluetoothctl power on; bluetoothctl devices Paired"; }
    ];
    boomer-player-assignment = mkMenuTool "boomer-player-assignment" "Player Assignment" [
      { label = "Show current order"; command = "action=show; ${playerAssignmentCommand}"; }
      { label = "Rebuild from connected controllers"; command = "action=rebuild; ${playerAssignmentCommand}"; }
      { label = "Rotate players"; command = "action=rotate; ${playerAssignmentCommand}"; }
      { label = "Clear saved order"; command = "action=clear; ${playerAssignmentCommand}"; }
    ];
    boomer-display-profile-tool = mkMenuTool "boomer-display-profile-tool" "Display Profile Test" [
      { label = "Current profile"; command = "boomer-display-profile | jq ."; }
      { label = "Resolution matrix"; command = "boomer-display-profile --matrix-test | jq ."; }
      { label = "Gamescope args"; command = "boomer-display-profile gamescope-args"; }
    ];
    boomer-display-profile-override = mkMenuTool "boomer-display-profile-override" "Display Profile Override" [
      { label = "Show current override"; command = "[ -r ${cfg.configRoot}/display.env ] && cat ${cfg.configRoot}/display.env || echo 'No override file.'"; }
      { label = "Write disabled template"; command = "cat > ${cfg.configRoot}/display.env <<'EOF'\n# BOOMER_DISPLAY_WIDTH=3840\n# BOOMER_DISPLAY_HEIGHT=2160\n# BOOMER_RENDER_SIZE=2954x1662\n# BOOMER_FORCE_FSR=1\n# BOOMER_DISABLE_FSR=1\nEOF\ncat ${cfg.configRoot}/display.env"; }
    ];
    boomer-retroarch-core-status = mkMenuTool "boomer-retroarch-core-status" "RetroArch Core Status" [
      { label = "RetroArch version"; command = "retroarch --version | head -n 1"; }
      { label = "Installed cores"; command = "find ${config.ghostship.emulation.internal.packages.retroarchPackage}/lib/retroarch/cores -maxdepth 1 -name '*_libretro.so' -printf '%f\\n' | sort"; }
      { label = "Shader smoke test"; command = "boomer-retroarch-shader-smoke-test || true"; }
      { label = "Update workflow"; command = "echo 'RetroArch cores are Nix-managed. Rebuild the host with: nix build .#nixosConfigurations.boomer-kuwanger.config.system.build.toplevel -L'"; }
    ];
    boomer-retroarch-graphics-profiles = mkMenuTool "boomer-retroarch-graphics-profiles" "RetroArch Graphics Profiles" [
      { label = "Show/switch profile"; command = profileMenuCommand; }
      { label = "System overrides"; command = "find ${cfg.configRoot}/retroarch/system-overrides -maxdepth 1 -type f -printf '%f\\n' | sort"; }
    ];
    boomer-retroarch-shader-profiles = mkMenuTool "boomer-retroarch-shader-profiles" "RetroArch Shader Profiles" [
      { label = "Show/switch profile"; command = profileMenuCommand; }
      { label = "Shader policy"; command = "jq . ${cfg.configRoot}/retroarch/shader-policy.json"; }
      { label = "Shader smoke test"; command = "boomer-retroarch-shader-smoke-test || true"; }
    ];
    boomer-esde-scraper-status = mkMenuTool "boomer-esde-scraper-status" "ES-DE Scraper Status" [
      { label = "Secret projection"; command = "ls -l /run/ghostship-secrets/emulation-scraper.env 2>/dev/null || echo 'No decrypted scraper projection.'"; }
      { label = "Projected settings"; command = "boomer-render-esde-scraper-settings || true; grep -E 'Scraper|Miximage|TheGamesDB' ${cfg.esde.appDataDir}/settings/es_settings.xml || true"; }
      { label = "Rekey reminder"; command = "echo 'Add boomer-kuwanger host SSH key to emulation-runtime, then run secret-rekey.'"; }
    ];
    boomer-esde-scrape-missing-media = mkMenuTool "boomer-esde-scrape-missing-media" "ES-DE Scrape Missing Media" [
      { label = "Prepare scraper settings"; command = "boomer-render-esde-scraper-settings || true; echo 'Open ES-DE > Main Menu > Scraper. Missing-media scrape uses the projected ScreenScraper/TheGamesDB settings when available.'"; }
    ];
    boomer-launch-log-review = mkMenuTool "boomer-launch-log-review" "Launch Log Review" [
      { label = "Latest launch log"; command = "latest=$(find ${cfg.dataRoot}/logs/launches -type f -name '*.jsonl' 2>/dev/null | sort | tail -n 1); [ -n \"$latest\" ] && jq . \"$latest\" || echo 'No launch logs yet.'"; }
      { label = "Launch log files"; command = "find ${cfg.dataRoot}/logs/launches -type f -name '*.jsonl' 2>/dev/null | sort | tail -n 25"; }
    ];
    boomer-rom-coverage-check-tool = mkMenuTool "boomer-rom-coverage-check-tool" "ROM Coverage Check" [
      { label = "Check /mnt/z source"; command = "boomer-rom-coverage-check /mnt/z/Library/ROMs/roms || true"; }
      { label = "Check local ROM root"; command = "boomer-rom-coverage-check ${cfg.romRoot} || true"; }
    ];
    boomer-restart-esde = pkgs.writeShellScriptBin "boomer-restart-esde" ''
      set -euo pipefail
      systemctl --user restart graphical-session.target 2>/dev/null || loginctl terminate-user ${cfg.user}
    '';
    boomer-shutdown = pkgs.writeShellScriptBin "boomer-shutdown" ''
      set -euo pipefail
      systemctl poweroff
    '';
    boomer-reboot = pkgs.writeShellScriptBin "boomer-reboot" ''
      set -euo pipefail
      systemctl reboot
    '';
  };

  boomerSyncEsdeTools = pkgs.writeShellScriptBin "boomer-sync-esde-tools" ''
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
      inherit boomerTerminalTool boomerToolMenu boomerSyncEsdeTools;
    };
    ghostship.emulation.internal.setupScripts = [ boomerSyncEsdeTools ];
  };
}
