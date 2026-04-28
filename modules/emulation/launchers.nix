{ config, lib, pkgs, ... }:

let
  cfg = config.ghostship.emulation;
  emu = config.ghostship.emulation.internal.lib;
  packages = config.ghostship.emulation.internal.packages;

  launcherPath = lib.makeBinPath ([
    packages.retroarchPackage
    pkgs.gamescope
    pkgs.gamemode
    pkgs.jq
    pkgs.mangohud
    packages.pico8Package
    packages.winePackage
  ] ++ emu.optionalPackages [
    "dolphin-emu"
    "cemu"
    "xemu"
    "ryubing"
    "lime3ds"
    "gzdoom"
  ] ++ lib.optional (packages.supermodelPackage != null) packages.supermodelPackage);

  displayPolicy = pkgs.writeText "boomer-display-policy.json" (builtins.toJSON {
    upscaler = "gamescope-fsr-auto";
    ultrawide = "center-fixed-aspect";
    renderTargets = {
      "3840x2160" = { quality = "2954x1662"; balanced = "2560x1440"; };
      "3440x1440" = { quality = "2646x1108"; balanced = "2293x960"; };
      "3840x1600" = { quality = "2954x1231"; balanced = "2560x1067"; };
      "5120x1440" = { quality = "3840x1080"; balanced = "3440x968"; };
      "5120x2160" = { quality = "3840x1620"; balanced = "3440x1451"; };
      "7680x4320" = { quality = "3840x2160"; balanced = "2954x1662"; };
    };
    heavyEmulators = [
      "cemu"
      "dolphin"
      "lime3ds"
      "retroarch-beetle-psx-hw"
      "retroarch-beetle-saturn"
      "retroarch-flycast"
      "retroarch-mupen64plus"
      "retroarch-parallel-n64"
      "retroarch-pcsx2"
      "retroarch-ppsspp"
      "ryubing"
      "supermodel"
      "teknoparrot"
      "xemu"
    ];
  });

  boomerDisplayProfile = pkgs.writeShellScriptBin "boomer-display-profile" ''
    set -euo pipefail
    export PATH=${emu.scriptPath}:$PATH

    if [ "''${1:-}" = "--matrix-test" ]; then
      tmp="$(mktemp)"
      for spec in 1280x720 1920x1080 1920x1200 2560x1080 2560x1440 2560x1600 3440x1440 3840x1600 3840x2160 5120x1440 5120x2160 7680x4320; do
        BOOMER_DISPLAY_WIDTH="''${spec%x*}" BOOMER_DISPLAY_HEIGHT="''${spec#*x}" BOOMER_EMULATOR_HEAVY=0 "$0" >>"$tmp"
        BOOMER_DISPLAY_WIDTH="''${spec%x*}" BOOMER_DISPLAY_HEIGHT="''${spec#*x}" BOOMER_EMULATOR_HEAVY=1 "$0" >>"$tmp"
      done
      jq -s . "$tmp"
      rm -f "$tmp"
      exit 0
    fi

    width="''${BOOMER_DISPLAY_WIDTH:-}"
    height="''${BOOMER_DISPLAY_HEIGHT:-}"
    refresh="''${BOOMER_DISPLAY_REFRESH:-60}"
    system_id="''${BOOMER_SYSTEM_ID:-unknown}"
    emulator_id="''${BOOMER_EMULATOR_ID:-unknown}"

    if [ -z "$width" ] || [ -z "$height" ]; then
      if command -v wlr-randr >/dev/null 2>&1; then
        mode="$(wlr-randr 2>/dev/null | awk '/^[^ ]/{out=$1} /current/{print $1; exit}' || true)"
        if [ -n "$mode" ]; then
          width="''${mode%x*}"
          rest="''${mode#*x}"
          height="''${rest%@*}"
          if printf '%s' "$rest" | grep -q '@'; then
            refresh="''${rest#*@}"
          fi
        fi
      fi
    fi

    if [ -z "$width" ] || [ -z "$height" ]; then
      if command -v xrandr >/dev/null 2>&1; then
        mode="$(xrandr --current 2>/dev/null | awk '/ connected/{out=$1} /\*/{print $1; exit}' || true)"
        if [ -n "$mode" ]; then
          width="''${mode%x*}"
          height="''${mode#*x}"
        fi
      fi
    fi

    width="''${width:-1920}"
    height="''${height:-1080}"
    aspect="$(awk -v w="$width" -v h="$height" 'BEGIN { if (h == 0) h = 1; printf "%.3f", w / h }')"
    class="$(awk -v a="$aspect" 'BEGIN { if (a > 2.9) print "super-ultrawide"; else if (a > 1.9) print "ultrawide"; else if (a > 1.65) print "widescreen"; else print "standard"; }')"
    heavy="''${BOOMER_EMULATOR_HEAVY:-0}"
    render_width="$width"
    render_height="$height"
    fsr=false
    fsr_sharpness="5"
    scale_mode="fit"
    fixed_aspect="center"

    case "''${width}x''${height}" in
      3840x2160) if [ "$heavy" = "1" ]; then render_width=2954; render_height=1662; fsr=true; fi ;;
      5120x2160) if [ "$heavy" = "1" ]; then render_width=3840; render_height=1620; fsr=true; fi ;;
      3440x1440) if [ "$heavy" = "1" ]; then render_width=2646; render_height=1108; fsr=true; fi ;;
      3840x1600) if [ "$heavy" = "1" ]; then render_width=2954; render_height=1231; fsr=true; fi ;;
      5120x1440) if [ "$heavy" = "1" ]; then render_width=3840; render_height=1080; fsr=true; fi ;;
      7680x4320) render_width=3840; render_height=2160; fsr=true ;;
      2560x1440|2560x1600) if [ "$heavy" = "1" ]; then render_width=1920; render_height=1080; fsr=true; fi ;;
      1920x1080|1920x1200|1280x720|2560x1080) fsr=false ;;
      *)
        if [ "$heavy" = "1" ] && [ "$width" -gt 1920 ]; then
          render_width="$(awk -v w="$width" 'BEGIN { printf "%d", w * 0.77 }')"
          render_height="$(awk -v h="$height" 'BEGIN { printf "%d", h * 0.77 }')"
          fsr=true
        fi
        ;;
    esac

    if [ "''${BOOMER_FORCE_FSR:-0}" = "1" ]; then fsr=true; fi
    if [ "''${BOOMER_DISABLE_FSR:-0}" = "1" ]; then fsr=false; render_width="$width"; render_height="$height"; fi
    if [ -n "''${BOOMER_RENDER_SIZE:-}" ] && printf '%s' "$BOOMER_RENDER_SIZE" | grep -Eq '^[0-9]+x[0-9]+$'; then
      render_width="''${BOOMER_RENDER_SIZE%x*}"
      render_height="''${BOOMER_RENDER_SIZE#*x}"
      if [ "$render_width" != "$width" ] || [ "$render_height" != "$height" ]; then fsr=true; fi
    fi
    if [ "$render_width" = "$width" ] && [ "$render_height" = "$height" ]; then fsr=false; fi

    if [ "''${1:-}" = "gamescope-args" ]; then
      args=(-f -e -W "$width" -H "$height" -w "$render_width" -h "$render_height" -S "$scale_mode")
      if [ "$fsr" = true ]; then args+=(-F fsr --fsr-sharpness "$fsr_sharpness"); fi
      printf '%q ' "''${args[@]}"
      printf '\n'
      exit 0
    fi

    jq -n \
      --arg system_id "$system_id" \
      --arg emulator_id "$emulator_id" \
      --argjson output_width "$width" \
      --argjson output_height "$height" \
      --arg refresh "$refresh" \
      --arg aspect "$aspect" \
      --arg class "$class" \
      --argjson render_width "$render_width" \
      --argjson render_height "$render_height" \
      --argjson fsr "$fsr" \
      --arg fsr_sharpness "$fsr_sharpness" \
      --arg scale_mode "$scale_mode" \
      --arg fixed_aspect "$fixed_aspect" \
      '{system_id:$system_id, emulator_id:$emulator_id, output_width:$output_width, output_height:$output_height, refresh:$refresh, aspect:($aspect|tonumber), class:$class, render_width:$render_width, render_height:$render_height, fsr:$fsr, fsr_sharpness:($fsr_sharpness|tonumber), scale_mode:$scale_mode, fixed_aspect:$fixed_aspect}'
  '';

  boomerTeknoparrotFree = pkgs.writeShellScriptBin "boomer-teknoparrot-free" ''
        set -euo pipefail
        export PATH=${emu.scriptPath}:${lib.makeBinPath [ packages.winePackage pkgs.curl pkgs.unzip ]}:$PATH
        prefix="${cfg.configRoot}/teknoparrot"
        install_dir="$prefix/TeknoParrot"
        rom="''${1:-}"
        mkdir -p "$prefix" "${cfg.dataRoot}/logs/teknoparrot"
        export WINEPREFIX="$prefix/prefix"
        export WINEARCH=win64
        if [ ! -e "$install_dir/TeknoParrotUi.exe" ]; then
          cat >&2 <<EOF
    TeknoParrot free is scaffolded but not installed yet.

    Place the official free TeknoParrot files under:
      ${cfg.configRoot}/teknoparrot/TeknoParrot

    No premium unlocks, bypasses, commercial game files, or third-party patch packs
    are managed by this module.
    EOF
          exit 69
        fi
        exec wine "$install_dir/TeknoParrotUi.exe" "$rom"
  '';

  boomerRunEmulator = pkgs.writeShellScriptBin "boomer-run-emulator" ''
    set -euo pipefail
    export PATH=${emu.scriptPath}:${launcherPath}:$PATH

    if [ "$#" -lt 3 ]; then
      echo "Usage: boomer-run-emulator <system-id> <emulator-id> <rom-path>" >&2
      exit 64
    fi

    [ -r "${cfg.configRoot}/display.env" ] && . "${cfg.configRoot}/display.env"

    system_id="$1"
    emulator_id="$2"
    rom_path="$3"
    export BOOMER_SYSTEM_ID="$system_id"
    export BOOMER_EMULATOR_ID="$emulator_id"
    log_dir="${cfg.dataRoot}/logs/launches"
    mkdir -p "$log_dir"
    log_file="$log_dir/$(date -u +%Y%m%dT%H%M%SZ)-$system_id.jsonl"

    log_event() {
      jq -nc --arg time "$(date -u +%FT%TZ)" --arg event "$1" --arg system "$system_id" --arg emulator "$emulator_id" --arg rom "$rom_path" --arg message "''${2:-}" \
        '{time:$time,event:$event,system:$system,emulator:$emulator,rom:$rom,message:$message}' >>"$log_file"
    }

    core_file_for() {
      case "$1" in
        retroarch-fbneo) echo fbneo_libretro.so ;;
        retroarch-mame) echo mame_libretro.so ;;
        retroarch-mesen) echo mesen_libretro.so ;;
        retroarch-snes9x) echo snes9x_libretro.so ;;
        retroarch-bsnes) echo bsnes_libretro.so ;;
        retroarch-bsnes-hd) echo bsnes_hd_beta_libretro.so ;;
        retroarch-genesis-plus-gx) echo genesis_plus_gx_libretro.so ;;
        retroarch-picodrive) echo picodrive_libretro.so ;;
        retroarch-beetle-pce-fast) echo mednafen_pce_fast_libretro.so ;;
        retroarch-gambatte) echo gambatte_libretro.so ;;
        retroarch-sameboy) echo sameboy_libretro.so ;;
        retroarch-mgba) echo mgba_libretro.so ;;
        retroarch-beetle-ngp) echo mednafen_ngp_libretro.so ;;
        retroarch-neocd) echo neocd_libretro.so ;;
        retroarch-beetle-vb) echo mednafen_vb_libretro.so ;;
        retroarch-beetle-psx-hw) echo mednafen_psx_hw_libretro.so ;;
        retroarch-beetle-saturn) echo mednafen_saturn_libretro.so ;;
        retroarch-flycast) echo flycast_libretro.so ;;
        retroarch-mupen64plus) echo mupen64plus_next_libretro.so ;;
        retroarch-parallel-n64) echo parallel_n64_libretro.so ;;
        retroarch-melonds) echo melonds_libretro.so ;;
        retroarch-ppsspp) echo ppsspp_libretro.so ;;
        retroarch-pcsx2) echo pcsx2_libretro.so ;;
        retroarch-citra) echo citra_libretro.so ;;
        *) return 1 ;;
      esac
    }

    core_pattern_for() {
      case "$1" in
        retroarch-melonds) echo '*melon*ds*_libretro.so' ;;
        retroarch-bsnes-hd) echo '*bsnes*hd*_libretro.so' ;;
        retroarch-mupen64plus) echo '*mupen64plus*_libretro.so' ;;
        retroarch-parallel-n64) echo '*parallel*n64*_libretro.so' ;;
        retroarch-beetle-*) echo '*mednafen*_libretro.so' ;;
        *) echo "*''${1#retroarch-}*_libretro.so" ;;
      esac
    }

    heavy=0
    case "$emulator_id" in
      dolphin|cemu|xemu|ryubing|lime3ds|supermodel|teknoparrot|retroarch-pcsx2|retroarch-beetle-psx-hw|retroarch-beetle-saturn|retroarch-mupen64plus|retroarch-parallel-n64|retroarch-ppsspp|retroarch-flycast) heavy=1 ;;
    esac
    export BOOMER_EMULATOR_HEAVY="$heavy"
    profile_json="$(boomer-display-profile)"
    output_width="$(jq -r '.output_width' <<<"$profile_json")"
    output_height="$(jq -r '.output_height' <<<"$profile_json")"
    render_width="$(jq -r '.render_width' <<<"$profile_json")"
    render_height="$(jq -r '.render_height' <<<"$profile_json")"
    fsr="$(jq -r '.fsr' <<<"$profile_json")"
    fsr_sharpness="$(jq -r '.fsr_sharpness' <<<"$profile_json")"
    scale_mode="$(jq -r '.scale_mode' <<<"$profile_json")"

    cmd=()
    case "$emulator_id" in
      retroarch-*)
        core_file="$(core_file_for "$emulator_id")"
        core_path="${packages.retroarchPackage}/lib/retroarch/cores/$core_file"
        if [ ! -e "$core_path" ]; then
          core_path="$(find "${packages.retroarchPackage}/lib/retroarch/cores" -maxdepth 1 -name "$(core_pattern_for "$emulator_id")" -print -quit || true)"
        fi
        if [ -z "''${core_path:-}" ] || [ ! -e "$core_path" ]; then
          log_event "error" "missing RetroArch core for $emulator_id"
          echo "Missing RetroArch core for $emulator_id" >&2
          exit 66
        fi
        profile="${cfg.configRoot}/retroarch/profiles/current.cfg"
        if [ ! -r "$profile" ]; then
          profile="${cfg.configRoot}/retroarch/profiles/${cfg.visuals.defaultProfile}.cfg"
        fi
        shader_status="${cfg.configRoot}/retroarch/shader-status.json"
        if [ -r "$shader_status" ] && jq -e '.megabezel == false' "$shader_status" >/dev/null 2>&1; then
          case "$(readlink "$profile" 2>/dev/null || basename "$profile")" in
            megabezel*) profile="${cfg.configRoot}/retroarch/profiles/sharp-clean.cfg" ;;
          esac
        fi
        system_override="${cfg.configRoot}/retroarch/system-overrides/$system_id.cfg"
        append_config="$profile"
        if [ -r "$system_override" ]; then
          append_config="$append_config|$system_override"
        fi
        cmd=(retroarch --config "${cfg.configRoot}/retroarch/retroarch.cfg" --appendconfig "$append_config" -L "$core_path" "$rom_path")
        ;;
      dolphin) cmd=(dolphin-emu -b -e "$rom_path") ;;
      cemu) cmd=(cemu -f -g "$rom_path") ;;
      xemu) cmd=(xemu -full-screen -dvd_path "$rom_path") ;;
      ryubing) cmd=(ryujinx "$rom_path") ;;
      lime3ds) cmd=(lime3ds "$rom_path") ;;
      supermodel) cmd=(supermodel "$rom_path" -fullscreen) ;;
      gzdoom) cmd=(gzdoom -iwad "$rom_path") ;;
      pico8) cmd=(pico8 -run "$rom_path") ;;
      teknoparrot) cmd=(boomer-teknoparrot-free "$rom_path") ;;
      *)
        log_event "error" "unknown emulator"
        echo "Unknown emulator: $emulator_id" >&2
        exit 64
        ;;
    esac

    log_event "launch" "$profile_json"
    run_cmd=("''${cmd[@]}")
    if [ "''${BOOMER_MANGOHUD:-0}" = "1" ]; then
      run_cmd=(mangohud "''${run_cmd[@]}")
    fi
    if [ "''${BOOMER_DISABLE_GAMESCOPE:-0}" != "1" ]; then
      gamescope_args=(-f -e -W "$output_width" -H "$output_height" -w "$render_width" -h "$render_height" -S "$scale_mode")
      if [ "$fsr" = "true" ]; then
        gamescope_args+=(-F fsr --fsr-sharpness "$fsr_sharpness")
      fi
      run_cmd=(gamescope "''${gamescope_args[@]}" -- "''${run_cmd[@]}")
    fi
    if command -v gamemoderun >/dev/null 2>&1; then
      run_cmd=(gamemoderun "''${run_cmd[@]}")
    fi
    exec "''${run_cmd[@]}"
  '';

  boomerRomCoverageCheck = pkgs.writeShellScriptBin "boomer-rom-coverage-check" ''
    set -euo pipefail
    export PATH=${emu.scriptPath}:$PATH
    source_root="''${1:-/mnt/z/Library/ROMs/roms}"
    [ -d "$source_root" ] || source_root="${cfg.romRoot}"
    missing=0
    printf '%s\n' "Checking ROM folder coverage under $source_root"
    while read -r folder; do
      if [ -e "$source_root/$folder" ]; then
        printf 'ok %s\n' "$folder"
      else
        printf 'missing %s\n' "$folder"
        missing=1
      fi
    done < <(printf '%s' '${emu.allSystemsJson}' | jq -r '.[].folder')
    exit "$missing"
  '';

  boomerSyncEmulatorConfigs = pkgs.writeShellScriptBin "boomer-sync-emulator-configs" ''
    set -euo pipefail
    export PATH=${emu.scriptPath}:$PATH
    install -d -m 0755 -o ${cfg.user} -g ${cfg.group} \
      "${cfg.configRoot}/display" \
      "${cfg.configRoot}/emulators" \
      "${cfg.configRoot}/emulators/dolphin" \
      "${cfg.configRoot}/emulators/cemu" \
      "${cfg.configRoot}/emulators/xemu" \
      "${cfg.configRoot}/emulators/ryubing" \
      "${cfg.configRoot}/emulators/supermodel" \
      "${cfg.configRoot}/emulators/gzdoom" \
      "${cfg.configRoot}/teknoparrot"
    install -D -m 0644 -o ${cfg.user} -g ${cfg.group} ${displayPolicy} "${cfg.configRoot}/display/policy.json"
    for dir in dolphin cemu xemu ryubing supermodel gzdoom; do
      readme="${cfg.configRoot}/emulators/$dir/README.txt"
      if [ ! -e "$readme" ]; then
        printf '%s\n' "Runtime config scaffold for $dir. Durable defaults are managed by Nix; hardware tuning can start here." >"$readme"
        chown ${cfg.user}:${cfg.group} "$readme"
        chmod 0644 "$readme"
      fi
    done
  '';
in
{
  config = lib.mkIf cfg.enable {
    ghostship.emulation.internal.scripts = {
      inherit
        boomerDisplayProfile
        boomerRomCoverageCheck
        boomerRunEmulator
        boomerSyncEmulatorConfigs
        boomerTeknoparrotFree
        ;
    };
    ghostship.emulation.internal.setupScripts = [ boomerSyncEmulatorConfigs ];
  };
}
