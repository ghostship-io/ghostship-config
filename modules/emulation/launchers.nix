{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.ghostship.emulation;
  emu = config.ghostship.emulation.internal.lib;
  packages = config.ghostship.emulation.internal.packages;

  launcherPath = lib.makeBinPath (
    [
      packages.retroarchPackage
      pkgs.gamescope
      pkgs.gamemode
      pkgs.jq
      pkgs.mangohud
      pkgs.util-linux
      pkgs.xdg-utils
      packages.pico8Package
      packages.ryubingCanaryPackage
      packages.winePackage
      config.ghostship.emulation.internal.scripts.audioRoute
    ]
    ++ emu.optionalPackages [
      "azahar"
      "dolphin-emu"
      "cemu"
      "xemu"
      "lime3ds"
      "pcsx2"
      "ppsspp-sdl"
    ]
    ++ lib.optional (packages.gzdoomPackage != null) packages.gzdoomPackage
    ++ lib.optional (packages.supermodelPackage != null) packages.supermodelPackage
  );

  displayPolicy = pkgs.writeText "emulation-display-policy.json" (
    builtins.toJSON {
      upscaler = "none";
      ultrawide = "center-fixed-aspect";
      gamescope = {
        fsr = false;
        scaleMode = "fit";
        stretchFixedAspect = false;
      };
      nativeScaling = {
        xemu = "internal-resolution-scale";
        ryubing = "resolution-scale-and-native-filter";
        dolphin = "internal-resolution";
        pcsx2 = "hardware-renderer-internal-resolution";
        ppsspp = "rendering-resolution";
        cemu = "graphics-packs";
        azahar = "internal-resolution";
        supermodel = "-res output_width,output_height";
      };
    }
  );

  controllerHotkeysPy = pkgs.writeText "controller-hotkeys.py" ''
    #!/usr/bin/env python3
    import argparse
    import subprocess
    import glob
    import json
    import os
    import select
    import signal
    import struct
    import sys
    import time
    from pathlib import Path

    EVENT = struct.Struct("@llHHi")
    EV_KEY = 0x01
    BTN_CAPTURE = 309
    BTN_SELECT = 314
    BTN_START = 315
    BTN_MODE = 316
    DOUBLE_PRESS_SECONDS = 0.9
    FORCE_KILL_SECONDS = 5.0

    def log(path, message, event="controller-hotkeys", system="", emulator=""):
        if not path:
            return
        try:
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            "event": event,
                            "system": system,
                            "emulator": emulator,
                            "rom": "",
                            "message": message,
                        },
                        separators=(",", ":"),
                    )
                    + "\n"
                )
        except OSError:
            pass

    def input_name(event_path):
        try:
            return (Path("/sys/class/input") / Path(event_path).name / "device/name").read_text(
                encoding="utf-8", errors="replace"
            ).strip()
        except OSError:
            return ""

    def supported_event(event_path):
        name = input_name(event_path).lower()
        return "pro controller" in name and "imu" not in name

    def open_events():
        fds = {}
        for event_path in sorted(glob.glob("/dev/input/event*")):
            if not supported_event(event_path):
                continue
            try:
                fds[event_path] = os.open(event_path, os.O_RDONLY | os.O_NONBLOCK)
            except OSError:
                continue
        return fds

    def signal_group(pid, sig, pgid=None):
        try:
            if pgid is None:
                pgid = os.getpgid(pid)
            os.killpg(pgid, sig)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return False

    def alive(pid):
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def group_alive(pgid):
        try:
            os.killpg(pgid, 0)
            return True
        except OSError:
            return False

    def terminate_group(pid, log_path, timeout=FORCE_KILL_SECONDS, system="", emulator=""):
        try:
            pgid = os.getpgid(pid)
        except ProcessLookupError:
            log(log_path, "Select + Start exit skipped; emulator process is already gone", "exit-request", system, emulator)
            return ["gone"]
        except PermissionError:
            log(log_path, "Select + Start exit failed; could not inspect emulator process group", "exit-request", system, emulator)
            return ["permission-denied"]

        actions = []
        if signal_group(pid, signal.SIGTERM, pgid=pgid):
            actions.append("sigterm")
            log(log_path, "Select + Start double-press sent SIGTERM to emulator process group", "exit-request", system, emulator)
        else:
            actions.append("sigterm-failed")
            log(log_path, "Select + Start SIGTERM failed; emulator process group is already gone or inaccessible", "exit-request", system, emulator)
            return actions

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not group_alive(pgid):
                log(log_path, "emulator process group exited after SIGTERM", "exit-request", system, emulator)
                return actions
            time.sleep(0.1)

        if signal_group(pid, signal.SIGKILL, pgid=pgid):
            actions.append("sigkill")
            log(log_path, "emulator still alive after 5 seconds; sent SIGKILL to emulator process group", "force-kill", system, emulator)
        else:
            actions.append("sigkill-skipped")
            log(log_path, "emulator exited before SIGKILL escalation", "exit-request", system, emulator)
        return actions

    def self_test():
        proc = subprocess.Popen(
            [sys.executable, "-c", "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)"],
            preexec_fn=os.setsid,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            actions = terminate_group(proc.pid, "", timeout=0.2)
            if actions[:2] != ["sigterm", "sigkill"]:
                raise AssertionError(f"unexpected termination actions: {actions}")
            for _ in range(30):
                if proc.poll() is not None:
                    break
                time.sleep(0.1)
            if proc.poll() is None:
                raise AssertionError("self-test child survived SIGKILL")
        finally:
            if proc.poll() is None:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except OSError:
                    pass
                proc.wait(timeout=3)
        print("controller-hotkeys self-test passed")

    def main():
        parser = argparse.ArgumentParser()
        parser.add_argument("--pid", type=int)
        parser.add_argument("--log", default="")
        parser.add_argument("--system", default="")
        parser.add_argument("--emulator", default="")
        parser.add_argument("--self-test", action="store_true")
        args = parser.parse_args()
        if args.self_test:
            self_test()
            return 0
        if args.pid is None:
            parser.error("--pid is required unless --self-test is used")

        fds = open_events()
        if not fds:
            log(args.log, "no Switch Pro controller input devices found", system=args.system, emulator=args.emulator)
            return 0

        pressed = {path: set() for path in fds}
        last_select_start = {path: 0.0 for path in fds}
        log(args.log, f"watching {len(fds)} Switch Pro controller(s) for {args.system}/{args.emulator}", system=args.system, emulator=args.emulator)

        while alive(args.pid):
            try:
                readable, _, _ = select.select(list(fds.values()), [], [], 0.2)
            except OSError:
                break
            reverse = {fd: path for path, fd in fds.items()}
            for fd in readable:
                path = reverse.get(fd)
                if not path:
                    continue
                try:
                    data = os.read(fd, EVENT.size * 16)
                except OSError:
                    continue
                for offset in range(0, len(data) - EVENT.size + 1, EVENT.size):
                    _sec, _usec, ev_type, code, value = EVENT.unpack(data[offset : offset + EVENT.size])
                    if ev_type != EV_KEY:
                        continue
                    if value:
                        pressed[path].add(code)
                    else:
                        pressed[path].discard(code)
                        continue
                    if code == BTN_MODE:
                        log(args.log, "Star/Home pressed; treated as controller-local turbo when exposed", system=args.system, emulator=args.emulator)
                    if code == BTN_CAPTURE:
                        log(args.log, "Square/Capture pressed; emulator-native menu binding should handle this", system=args.system, emulator=args.emulator)
                    if code != BTN_START:
                        continue
                    now = time.monotonic()
                    if BTN_SELECT in pressed[path]:
                        if now - last_select_start[path] <= DOUBLE_PRESS_SECONDS:
                            terminate_group(args.pid, args.log, system=args.system, emulator=args.emulator)
                            release_deadline = time.monotonic() + 3.0
                            while time.monotonic() < release_deadline:
                                try:
                                    r, _, _ = select.select(list(fds.values()), [], [], 0.2)
                                except OSError:
                                    break
                                rev = {fd: p for p, fd in fds.items()}
                                for fd in r:
                                    p = rev.get(fd)
                                    if not p:
                                        continue
                                    try:
                                        d = os.read(fd, EVENT.size * 16)
                                    except OSError:
                                        continue
                                    for off in range(0, len(d) - EVENT.size + 1, EVENT.size):
                                        _, _, t, c, v = EVENT.unpack(d[off:off + EVENT.size])
                                        if t != EV_KEY:
                                            continue
                                        if v:
                                            pressed[p].add(c)
                                        else:
                                            pressed[p].discard(c)
                                if not any(BTN_SELECT in s for s in pressed.values()):
                                    log(args.log, "Select released after exit; safe for ES-DE to resume")
                                    break
                            return 0
                        last_select_start[path] = now
                        continue
        return 0

    if __name__ == "__main__":
        sys.exit(main())
  '';

  controllerHotkeys = pkgs.writeShellScriptBin "controller-hotkeys" ''
    set -euo pipefail
    exec ${pkgs.python3}/bin/python3 ${controllerHotkeysPy} "$@"
  '';

  controllerHotkeysSmokeTest = pkgs.writeShellScriptBin "controller-hotkeys-smoke-test" ''
    set -euo pipefail
    exec ${lib.getExe controllerHotkeys} --self-test
  '';

  switchProButtonProbePy = pkgs.writeText "switch-pro-button-probe.py" ''
    #!/usr/bin/env python3
    import glob
    import os
    import select
    import struct
    import time
    from pathlib import Path

    EVENT = struct.Struct("@llHHi")
    EV_KEY = 0x01
    EV_ABS = 0x03
    NAMES = {
        304: "B/South",
        305: "A/East",
        307: "X/North",
        308: "Y/West",
        309: "Square/Capture",
        310: "L1",
        311: "R1",
        312: "ZL",
        313: "ZR",
        314: "Select/-",
        315: "Start/+",
        316: "Star/Home",
        317: "Left Stick Press",
        318: "Right Stick Press",
    }
    ABS_NAMES = {
        0: "Left Stick X",
        1: "Left Stick Y",
        3: "Right Stick X",
        4: "Right Stick Y",
        16: "D-pad X",
        17: "D-pad Y",
    }

    def name(path):
        try:
            return (Path("/sys/class/input") / Path(path).name / "device/name").read_text(
                encoding="utf-8", errors="replace"
            ).strip()
        except OSError:
            return ""

    fds = {}
    for path in sorted(glob.glob("/dev/input/event*")):
        lowered = name(path).lower()
        if "pro controller" in lowered and "imu" not in lowered:
            try:
                fds[path] = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
                print(f"Watching {path} ({name(path)})")
            except OSError:
                pass
    if not fds:
        print("No Switch Pro controller event devices found.")
        raise SystemExit(1)
    print("Press buttons or move sticks now; exiting after 12 seconds.")
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        readable, _, _ = select.select(list(fds.values()), [], [], 0.25)
        reverse = {fd: path for path, fd in fds.items()}
        for fd in readable:
            path = reverse.get(fd, "?")
            data = os.read(fd, EVENT.size * 16)
            for offset in range(0, len(data) - EVENT.size + 1, EVENT.size):
                _sec, _usec, ev_type, code, value = EVENT.unpack(data[offset : offset + EVENT.size])
                if ev_type == EV_KEY and value == 1:
                    print(f"{Path(path).name}: code {code} {NAMES.get(code, 'unknown')}")
                elif ev_type == EV_ABS and code in ABS_NAMES:
                    print(f"{Path(path).name}: axis {code} {ABS_NAMES[code]} value {value}")
  '';

  switchProButtonProbe = pkgs.writeShellScriptBin "switch-pro-button-probe" ''
    set -euo pipefail
    exec ${pkgs.python3}/bin/python3 ${switchProButtonProbePy} "$@"
  '';

  displayProfile = pkgs.writeShellScriptBin "display-profile" ''
    set -euo pipefail
    export PATH=${emu.scriptPath}:$PATH

    preferred_vendor="0x1002"
    preferred_device="0x73ef"

    connector_from_output() {
      output="$1"
      card="''${output%%-*}"
      printf '%s\n' "''${output#"$card"-}"
    }

    mode_for_output() {
      output_dir="$1"
      if [ -r "$output_dir/modes" ]; then
        sed -n '1p' "$output_dir/modes"
      fi
    }

    discover_output() {
      forced_connector="''${EMULATION_CONNECTOR:-}"
      forced_drm_card="''${EMULATION_DRM_CARD:-}"
      best_score=-1
      best_output=""
      best_card=""
      best_connector=""
      best_mode=""
      best_dgpu=false

      for status in /sys/class/drm/card*-*/status; do
        [ -e "$status" ] || continue
        grep -qx connected "$status" || continue
        output_dir="''${status%/status}"
        output="''${output_dir##*/}"
        card="''${output%%-*}"
        connector="$(connector_from_output "$output")"
        card_device="/sys/class/drm/$card/device"
        vendor="$(sed -n '1p' "$card_device/vendor" 2>/dev/null || true)"
        device="$(sed -n '1p' "$card_device/device" 2>/dev/null || true)"
        mode="$(mode_for_output "$output_dir")"
        [ -n "$mode" ] || continue

        score=10
        dgpu=false
        if [ "$vendor" = "$preferred_vendor" ] && [ "$device" = "$preferred_device" ]; then
          score=$((score + 100))
          dgpu=true
        elif [ "$vendor" = "$preferred_vendor" ]; then
          score=$((score + 50))
        fi
        if [ -n "$forced_connector" ] && [ "$connector" = "$forced_connector" ]; then
          score=$((score + 1000))
        fi
        if [ -n "$forced_drm_card" ] && [ "$card" = "$forced_drm_card" ]; then
          score=$((score + 500))
        fi
        case "$connector" in
          HDMI-A-*) score=$((score + 20)) ;;
          DP-*|DisplayPort-*) score=$((score + 10)) ;;
        esac

        if [ "$score" -gt "$best_score" ]; then
          best_score="$score"
          best_output="$output"
          best_card="$card"
          best_connector="$connector"
          best_mode="$mode"
          best_dgpu="$dgpu"
        fi
      done

      if [ -n "$best_output" ]; then
        printf '%s\t%s\t%s\t%s\t%s\n' "$best_output" "$best_card" "$best_connector" "$best_mode" "$best_dgpu"
      fi
    }

    if [ "''${1:-}" = "--matrix-test" ]; then
      tmp="$(mktemp)"
      for spec in 1280x720 1920x1080 1920x1200 2560x1080 2560x1440 2560x1600 3440x1440 3840x1600 3840x2160 5120x1440 5120x2160 7680x4320; do
        EMULATION_DISPLAY_WIDTH="''${spec%x*}" EMULATION_DISPLAY_HEIGHT="''${spec#*x}" EMULATION_EMULATOR_HEAVY=0 "$0" >>"$tmp"
        EMULATION_DISPLAY_WIDTH="''${spec%x*}" EMULATION_DISPLAY_HEIGHT="''${spec#*x}" EMULATION_EMULATOR_HEAVY=1 "$0" >>"$tmp"
      done
      jq -s . "$tmp"
      rm -f "$tmp"
      exit 0
    fi

    width="''${EMULATION_DISPLAY_WIDTH:-}"
    height="''${EMULATION_DISPLAY_HEIGHT:-}"
    refresh="''${EMULATION_DISPLAY_REFRESH:-60}"
    system_id="''${EMULATION_SYSTEM_ID:-unknown}"
    emulator_id="''${EMULATION_EMULATOR_ID:-unknown}"
    output="''${EMULATION_OUTPUT:-}"
    drm_card="''${EMULATION_DRM_CARD:-}"
    connector="''${EMULATION_CONNECTOR:-}"
    dgpu=false
    connected=false

    if [ -z "$width" ] || [ -z "$height" ] || [ -z "$connector" ]; then
      discovered="$(discover_output || true)"
      if [ -n "$discovered" ]; then
        connected=true
        IFS=$'\t' read -r output drm_card connector mode dgpu <<<"$discovered"
        if [ -z "$width" ] || [ -z "$height" ]; then
          width="''${mode%x*}"
          mode_rest="''${mode#*x}"
          height="''${mode_rest%%[^0-9]*}"
        fi
      fi
    fi

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
    drm_device=""
    if [ -n "$drm_card" ] && [ -e "/dev/dri/$drm_card" ]; then
      drm_device="/dev/dri/$drm_card"
    fi
    aspect="$(awk -v w="$width" -v h="$height" 'BEGIN { if (h == 0) h = 1; printf "%.3f", w / h }')"
    class="$(awk -v a="$aspect" 'BEGIN { if (a > 2.9) print "super-ultrawide"; else if (a > 1.9) print "ultrawide"; else if (a > 1.65) print "widescreen"; else print "standard"; }')"
    render_width="$width"
    render_height="$height"
    fsr=false
    scale_mode="fit"
    fixed_aspect="center"
    viewports_json="$(
      jq -n --argjson ow "$width" --argjson oh "$height" '
        def fit($rw; $rh):
          (if (($ow / $oh) >= ($rw / $rh)) then
            { width: (($oh * $rw / $rh) | floor), height: $oh }
          else
            { width: $ow, height: (($ow * $rh / $rw) | floor) }
          end) as $v
          | $v + {
              x: ((($ow - $v.width) / 2) | floor),
              y: ((($oh - $v.height) / 2) | floor)
            };
        {
          "4:3": fit(4; 3),
          "3:2": fit(3; 2),
          "10:9": fit(10; 9),
          "20:19": fit(20; 19),
          "16:9": fit(16; 9),
          native: { x: 0, y: 0, width: $ow, height: $oh }
        }
      '
    )"

    if [ "''${1:-}" = "gamescope-args" ]; then
      args=(-f -e -W "$width" -H "$height" -w "$render_width" -h "$render_height" -S "$scale_mode")
      printf '%q ' "''${args[@]}"
      printf '\n'
      exit 0
    fi

    jq -n \
      --arg system_id "$system_id" \
      --arg emulator_id "$emulator_id" \
      --arg output "$output" \
      --arg drm_card "$drm_card" \
      --arg drm_device "$drm_device" \
      --arg connector "$connector" \
      --argjson connected "$connected" \
      --argjson dgpu "$dgpu" \
      --argjson output_width "$width" \
      --argjson output_height "$height" \
      --arg refresh "$refresh" \
      --arg aspect "$aspect" \
      --arg class "$class" \
      --argjson render_width "$render_width" \
      --argjson render_height "$render_height" \
      --argjson fsr "$fsr" \
      --arg scale_mode "$scale_mode" \
      --arg fixed_aspect "$fixed_aspect" \
      --argjson viewports "$viewports_json" \
      '{
        system_id:$system_id,
        emulator_id:$emulator_id,
        connected:$connected,
        output:$output,
        drm_card:$drm_card,
        drm_device:$drm_device,
        connector:$connector,
        preferred_dgpu:$dgpu,
        preferred_vk_device:(if $dgpu then "1002:73ef" else "" end),
        output_width:$output_width,
        output_height:$output_height,
        refresh:$refresh,
        aspect:($aspect|tonumber),
        class:$class,
        render_width:$render_width,
        render_height:$render_height,
        fsr:$fsr,
        scale_mode:$scale_mode,
        fixed_aspect:$fixed_aspect,
        viewport_recommendations:$viewports,
        gamescope_args:["-f","-e","-W",($output_width|tostring),"-H",($output_height|tostring),"-w",($render_width|tostring),"-h",($render_height|tostring),"-S",$scale_mode],
        frontend_gamescope_args:(["--backend","drm","-f","-W",($output_width|tostring),"-H",($output_height|tostring),"--force-windows-fullscreen"] + (if $connector != "" then ["--prefer-output",$connector] else [] end) + (if $dgpu then ["--prefer-vk-device","1002:73ef"] else [] end))
      }'
  '';

  teknoparrotFree = pkgs.writeShellScriptBin "teknoparrot-free" ''
        set -euo pipefail
        export PATH=${emu.scriptPath}:${
          lib.makeBinPath [
            packages.winePackage
            pkgs.curl
            pkgs.unzip
          ]
        }:$PATH
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

  runEmulator = pkgs.writeShellScriptBin "run-emulator" ''
    set -euo pipefail
    export PATH=${emu.scriptPath}:${launcherPath}:$PATH
    export ESDE_APPDATA_DIR="${cfg.esde.appDataDir}"
    export XDG_DATA_HOME="${cfg.dataRoot}/xdg/share"
    export XDG_CONFIG_HOME="${cfg.dataRoot}/xdg/config"
    export XDG_CACHE_HOME="${cfg.dataRoot}/xdg/cache"
    export MESA_SHADER_CACHE_DIR="${cfg.dataRoot}/cache/mesa-shaders"
    export SDL_GAMECONTROLLERCONFIG_FILE="${cfg.configRoot}/controllers/gamecontrollerdb.txt"
    export SDL_GAMECONTROLLER_USE_BUTTON_LABELS=1
    export TMPDIR="${cfg.dataRoot}/tmp"

    if [ "$#" -lt 3 ]; then
      echo "Usage: run-emulator <system-id> <emulator-id> <rom-path>" >&2
      exit 64
    fi

    [ -r "${cfg.configRoot}/display.env" ] && . "${cfg.configRoot}/display.env"

    system_id="$1"
    emulator_id="$2"
    rom_path="$3"
    export EMULATION_SYSTEM_ID="$system_id"
    export EMULATION_EMULATOR_ID="$emulator_id"
    audio-route || true
    log_dir="${cfg.dataRoot}/logs/launches"
    mkdir -p "$log_dir"
    log_file="$log_dir/$(date -u +%Y%m%dT%H%M%SZ)-$system_id.jsonl"

    log_event() {
      jq -nc --arg time "$(date -u +%FT%TZ)" --arg event "$1" --arg system "$system_id" --arg emulator "$emulator_id" --arg rom "$rom_path" --arg message "''${2:-}" \
        '{time:$time,event:$event,system:$system,emulator:$emulator,rom:$rom,message:$message}' >>"$log_file"
    }

    first_command() {
      for candidate in "$@"; do
        if command -v "$candidate" >/dev/null 2>&1; then
          printf '%s\n' "$candidate"
          return 0
        fi
      done
      return 1
    }

    core_file_for() {
      case "$1" in
        retroarch-fbneo) echo fbneo_libretro.so ;;
        retroarch-mame) echo mame_libretro.so ;;
        retroarch-fceumm) echo fceumm_libretro.so ;;
        retroarch-mesen) echo mesen_libretro.so ;;
        retroarch-snes9x) echo snes9x_libretro.so ;;
        retroarch-bsnes) echo bsnes_libretro.so ;;
        retroarch-bsnes-hd) echo bsnes_hd_beta_libretro.so ;;
        retroarch-genesis-plus-gx) echo genesis_plus_gx_libretro.so ;;
        retroarch-picodrive) echo picodrive_libretro.so ;;
        retroarch-beetle-supergrafx) echo mednafen_supergrafx_libretro.so ;;
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
        retroarch-desmume) echo desmume_libretro.so ;;
        retroarch-melonds) echo melonds_libretro.so ;;
        retroarch-ppsspp) echo ppsspp_libretro.so ;;
        retroarch-pcsx2) echo pcsx2_libretro.so ;;
        retroarch-citra) echo citra_libretro.so ;;
        *) return 1 ;;
      esac
    }

    core_pattern_for() {
      case "$1" in
        retroarch-desmume) echo '*desmume*_libretro.so' ;;
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
      azahar|dolphin|cemu|xemu|ryubing|lime3ds|pcsx2|ppsspp|supermodel|teknoparrot|retroarch-beetle-psx-hw|retroarch-beetle-saturn|retroarch-mupen64plus|retroarch-parallel-n64|retroarch-flycast) heavy=1 ;;
    esac
    export EMULATION_EMULATOR_HEAVY="$heavy"
    profile_json="$(display-profile)"
    output_width="$(jq -r '.output_width' <<<"$profile_json")"
    output_height="$(jq -r '.output_height' <<<"$profile_json")"

    bootstrap_emulator_config() {
      emulator="$1"
      case "$emulator" in
        azahar|cemu|dolphin|pcsx2|ppsspp|ryubing|supermodel|xemu)
          dir="${cfg.configRoot}/emulators/$emulator"
          mkdir -p "$dir"
          jq -n \
            --arg emulator "$emulator" \
            --arg scaling_profile "''${EMULATION_PERF_SCALING_PROFILE:-default}" \
            --argjson output_width "$output_width" \
            --argjson output_height "$output_height" \
            '{
              emulator:$emulator,
              output_width:$output_width,
              output_height:$output_height,
              gamescope_fsr:false,
              aspect_policy:"preserve",
              scaling:"emulator-native",
              scaling_profile:$scaling_profile,
              generated_at:now|todate
            }' >"$dir/runtime-scaling-policy.json.tmp"
          mv "$dir/runtime-scaling-policy.json.tmp" "$dir/runtime-scaling-policy.json"
          ;;
      esac
    }
    bootstrap_emulator_config "$emulator_id"

    prepare_ryubing_runtime() {
      ryujinx_config_dir="$XDG_CONFIG_HOME/Ryujinx"
      ryujinx_system_dir="$ryujinx_config_dir/system"
      ryujinx_sdcard_dir="$ryujinx_config_dir/sdcard"
      mkdir -p "$ryujinx_system_dir" "$ryujinx_sdcard_dir"

      for key_name in prod.keys title.keys; do
        key_source="${cfg.biosRoot}/switch/$key_name"
        key_target="$ryujinx_system_dir/$key_name"
        if [ -r "$key_source" ] && { [ ! -e "$key_target" ] || [ -L "$key_target" ]; }; then
          ln -sfn "$key_source" "$key_target"
        fi
      done

      case "$system_id:$emulator_id:$rom_path" in
        switch:ryubing:*.nro|switch:ryubing:*.NRO)
          rom_dir="$(dirname "$rom_path")"
          asset_source="$rom_dir/data"
          asset_target="$ryujinx_sdcard_dir/data"
          if [ -d "$asset_source" ]; then
            if [ ! -e "$asset_target" ] || [ -L "$asset_target" ]; then
              ln -sfn "$asset_source" "$asset_target"
              log_event "runtime" "linked Ryubing homebrew data: $asset_target -> $asset_source"
            elif [ -d "$asset_target" ]; then
              log_event "runtime" "kept existing Ryubing sdcard data directory: $asset_target"
            else
              log_event "warning" "Ryubing sdcard data path exists and is not a directory or symlink: $asset_target"
            fi
          fi
          ;;
      esac
    }

    cmd=()
    run_cwd=""
    parse_gzdoom_launcher() {
      launcher="$1"
      launcher_line="$(grep -v -E '^[[:space:]]*(#|$)' "$launcher" | head -n 1 || true)"
      if [ -z "$launcher_line" ]; then
        log_event "error" "empty GZDoom launcher"
        echo "Empty GZDoom launcher: $launcher" >&2
        exit 64
      fi
      set +e
      mapfile -d "" -t gzdoom_args < <(
        GZDOOM_LAUNCHER_LINE="$launcher_line" ${pkgs.python3}/bin/python3 - <<'PY'
import os
import shlex
import sys

try:
    args = shlex.split(os.environ["GZDOOM_LAUNCHER_LINE"], comments=False, posix=True)
except ValueError as exc:
    print(f"Invalid .gzdoom launcher syntax: {exc}", file=sys.stderr)
    sys.exit(64)

for arg in args:
    sys.stdout.buffer.write(arg.encode("utf-8") + b"\0")
PY
      )
      parse_rc="$?"
      set -e
      if [ "$parse_rc" -ne 0 ]; then
        exit "$parse_rc"
      fi
      if [ "''${#gzdoom_args[@]}" -eq 0 ]; then
        log_event "error" "GZDoom launcher produced no arguments"
        echo "GZDoom launcher produced no arguments: $launcher" >&2
        exit 64
      fi
    }

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
        profile_override="''${EMULATION_RETROARCH_PROFILE:-}"
        if [ -n "$profile_override" ] && [ "$profile_override" != "default" ]; then
          case "$profile_override" in *.cfg) ;; *) profile_override="$profile_override.cfg" ;; esac
          if [ ! -r "${cfg.configRoot}/retroarch/profiles/$profile_override" ]; then
            log_event "error" "unknown RetroArch profile $profile_override"
            echo "Unknown RetroArch profile: $profile_override" >&2
            exit 64
          fi
          profile="${cfg.configRoot}/retroarch/profiles/$profile_override"
          profile_name="$profile_override"
        else
          if [ ! -r "$profile" ]; then
            profile="${cfg.configRoot}/retroarch/profiles/${cfg.visuals.defaultProfile}.cfg"
          fi
          profile_name="$(readlink "$profile" 2>/dev/null || basename "$profile")"
          if [ "$profile_name" = "${cfg.visuals.defaultProfile}.cfg" ] && [ -r "${cfg.configRoot}/retroarch/shader-policy.json" ]; then
            system_profile="$(jq -r --arg system "$system_id" '.systemDefaults[$system] // empty' "${cfg.configRoot}/retroarch/shader-policy.json")"
            if [ -n "$system_profile" ] && [ -r "${cfg.configRoot}/retroarch/profiles/$system_profile.cfg" ]; then
              profile="${cfg.configRoot}/retroarch/profiles/$system_profile.cfg"
              profile_name="$system_profile.cfg"
            fi
          fi
        fi
        shader_status="${cfg.configRoot}/retroarch/shader-status.json"
        if [ -r "$shader_status" ]; then
          case "$profile_name" in
            nnedi3*) jq -e '.nnedi3 == true' "$shader_status" >/dev/null 2>&1 || profile="${cfg.configRoot}/retroarch/profiles/sharp-bilinear-prescale.cfg" ;;
            sharp*|pixel-aa-fast.cfg|scalefx-aa-fast.cfg|xbrz-freescale.cfg) jq -e '.sharp == true' "$shader_status" >/dev/null 2>&1 || profile="${cfg.configRoot}/retroarch/profiles/no-shader.cfg" ;;
            megabezel*) jq -e '.megabezel == true' "$shader_status" >/dev/null 2>&1 || profile="${cfg.configRoot}/retroarch/profiles/sharp-bilinear-prescale.cfg" ;;
          esac
        fi
        system_override="${cfg.configRoot}/retroarch/system-overrides/$system_id.cfg"
        append_config="$profile"
        if [ -r "$system_override" ]; then
          append_config="$append_config|$system_override"
        fi
        retroachievements_config="${cfg.configRoot}/retroarch/retroachievements.cfg"
        if [ -r "$retroachievements_config" ]; then
          append_config="$append_config|$retroachievements_config"
        fi
        cmd=(retroarch --config "${cfg.configRoot}/retroarch/retroarch.cfg" --appendconfig "$append_config" -L "$core_path" "$rom_path")
        ;;
      dolphin) cmd=(dolphin-emu -b -e "$rom_path") ;;
      cemu) cmd=(cemu -f -g "$rom_path") ;;
      xemu)
        cmd=(
          xemu
          -full-screen
          -config_path "${cfg.dataRoot}/xdg/share/xemu/xemu/xemu.toml"
          -dvd_path "$rom_path"
        )
        ;;
      ryubing)
        prepare_ryubing_runtime
        cmd=(ryujinx "$rom_path")
        ;;
      azahar)
        azahar_bin="$(first_command azahar azahar-qt)"
        cmd=("$azahar_bin" "$rom_path")
        ;;
      lime3ds) cmd=(lime3ds "$rom_path") ;;
      pcsx2)
        pcsx2_bin="$(first_command pcsx2-qt pcsx2)"
        cmd=("$pcsx2_bin" -fullscreen "$rom_path")
        ;;
      ppsspp)
        ppsspp_bin="$(first_command PPSSPPSDL ppsspp ppsspp-sdl)"
        cmd=("$ppsspp_bin" "$rom_path")
        ;;
      supermodel) cmd=(supermodel "$rom_path" -res="$output_width","$output_height" -fullscreen) ;;
      gzdoom)
        run_cwd="$(dirname "$rom_path")"
        gzdoom_controls="${cfg.configRoot}/emulators/gzdoom/boomer-controls.cfg"
        gzdoom_common_args=()
        if [ -r "$gzdoom_controls" ]; then
          gzdoom_common_args=(-exec "$gzdoom_controls")
        fi
        case "$rom_path" in
          *.gzdoom|*.GZDOOM)
            parse_gzdoom_launcher "$rom_path"
            cmd=(gzdoom "''${gzdoom_common_args[@]}" "''${gzdoom_args[@]}")
            ;;
          *) cmd=(gzdoom "''${gzdoom_common_args[@]}" -iwad "$rom_path") ;;
        esac
        ;;
      pico8) cmd=(pico8 -run "$rom_path") ;;
      teknoparrot) cmd=(teknoparrot-free "$rom_path") ;;
      *)
        log_event "error" "unknown emulator"
        echo "Unknown emulator: $emulator_id" >&2
        exit 64
        ;;
    esac

    log_event "launch" "$profile_json"
    run_cmd=("''${cmd[@]}")
    if [ "''${EMULATION_MANGOHUD:-0}" = "1" ]; then
      run_cmd=(mangohud "''${run_cmd[@]}")
    fi
    use_gamescope=0
    if [ "''${EMULATION_DISABLE_GAMESCOPE:-0}" != "1" ]; then
      if [ "''${EMULATION_FORCE_GAMESCOPE:-0}" = "1" ] || { [ -z "''${WAYLAND_DISPLAY:-}" ] && [ -z "''${DISPLAY:-}" ]; }; then
        use_gamescope=1
      fi
    fi
    if [ "$use_gamescope" = "1" ]; then
      if [ -z "''${WAYLAND_DISPLAY:-}" ] && [ -z "''${DISPLAY:-}" ]; then
        mapfile -t gamescope_args < <(
          jq -r '
            ["--backend","drm","-f","-W",(.output_width|tostring),"-H",(.output_height|tostring),"-w",(.render_width|tostring),"-h",(.render_height|tostring),"-S",.scale_mode,"--force-windows-fullscreen"]
            + (if .connector != "" then ["--prefer-output",.connector] else [] end)
            + (if .preferred_vk_device != "" then ["--prefer-vk-device",.preferred_vk_device] else [] end)
            | .[]
          ' <<<"$profile_json"
        )
      else
        mapfile -t gamescope_args < <(jq -r '.gamescope_args[]' <<<"$profile_json")
      fi
      if [ "$emulator_id" = "pico8" ]; then
        gamescope_args+=("--xwayland-count" "1")
      fi
      run_cmd=(gamescope "''${gamescope_args[@]}" -- "''${run_cmd[@]}")
    fi
    if command -v gamemoderun >/dev/null 2>&1; then
      run_cmd=(gamemoderun "''${run_cmd[@]}")
    fi
    if [ -n "$run_cwd" ]; then
      cd "$run_cwd"
    fi
    setsid "''${run_cmd[@]}" &
    emulator_pid="$!"
    ${lib.getExe controllerHotkeys} --pid "$emulator_pid" --system "$system_id" --emulator "$emulator_id" --log "$log_file" &
    hotkey_pid="$!"

    process_group_alive() {
      kill -0 -- "-$1" >/dev/null 2>&1
    }

    terminate_process_group() {
      pid="$1"
      reason="$2"
      process_group_alive "$pid" || return 0
      log_event "exit-request" "$reason sent SIGTERM to emulator process group"
      kill -TERM -- "-$pid" >/dev/null 2>&1 || true
      for _ in $(seq 1 50); do
        process_group_alive "$pid" || return 0
        sleep 0.1
      done
      process_group_alive "$pid" || return 0
      log_event "force-kill" "$reason still alive after 5 seconds; sent SIGKILL to emulator process group"
      kill -KILL -- "-$pid" >/dev/null 2>&1 || true
    }

    cleanup() {
      kill "$hotkey_pid" >/dev/null 2>&1 || true
      terminate_process_group "$emulator_pid" "run-emulator cleanup"
    }
    trap cleanup INT TERM HUP
    set +e
    wait "$emulator_pid"
    status="$?"
    set -e
    kill "$hotkey_pid" >/dev/null 2>&1 || true
    wait "$hotkey_pid" >/dev/null 2>&1 || true
    exit "$status"
  '';

  romCoverageCheck = pkgs.writeShellScriptBin "rom-coverage-check" ''
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

  updateRyubingCanary = pkgs.writeShellScriptBin "update-ryubing-canary" ''
        set -euo pipefail
        export PATH=${
          lib.makeBinPath [
            pkgs.coreutils
            pkgs.curl
            pkgs.gnugrep
            pkgs.gnused
            pkgs.nix
          ]
        }:$PATH

        repo="''${1:-$PWD}"
        pin_file="$repo/modules/emulation/ryubing-canary-pin.nix"
        latest_endpoint="https://update.ryujinx.app/latest/canary"

        if [ ! -f "$pin_file" ]; then
          echo "Missing pin file: $pin_file" >&2
          exit 66
        fi

        final_url="$(curl -fsSL -o /dev/null -w '%{url_effective}' "$latest_endpoint")"
        version="$(printf '%s\n' "$final_url" | sed -n 's#.*/\([0-9][0-9.]*\)$#\1#p')"
        if [ -z "$version" ]; then
          echo "Could not resolve Ryubing Canary version from $latest_endpoint -> $final_url" >&2
          exit 65
        fi

        current="$(sed -n 's/.*version = "\(.*\)";.*/\1/p' "$pin_file")"
        if [ "''${2:-}" != "--force" ] && [ "$current" = "$version" ]; then
          echo "Ryubing Canary is already pinned to latest version $version"
          exit 0
        fi

        url="https://git.ryujinx.app/Ryubing/Canary/releases/download/$version/ryujinx-canary-$version-linux_x64.tar.gz"
        hash_base32="$(nix-prefetch-url "$url")"
        hash_sri="$(nix hash convert --hash-algo sha256 --to sri "$hash_base32")"

        tmp="$(mktemp)"
        cat >"$tmp" <<EOF
    {
      version = "$version";
      url = "$url";
      hash = "$hash_sri";
    }
EOF
        mv "$tmp" "$pin_file"
        echo "Pinned Ryubing Canary $version"
        echo "$hash_sri"
  '';

  syncEmulatorConfigs = pkgs.writeShellScriptBin "sync-emulator-configs" ''
        set -euo pipefail
        export PATH=${emu.scriptPath}:$PATH
        install -d -m 0755 -o ${cfg.user} -g ${cfg.group} \
          "${cfg.configRoot}/display" \
          "${cfg.configRoot}/emulators" \
          "${cfg.configRoot}/emulators/azahar" \
          "${cfg.configRoot}/emulators/dolphin" \
          "${cfg.configRoot}/emulators/cemu" \
          "${cfg.configRoot}/emulators/pcsx2" \
          "${cfg.configRoot}/emulators/ppsspp" \
          "${cfg.configRoot}/emulators/xemu" \
          "${cfg.configRoot}/emulators/ryubing" \
          "${cfg.configRoot}/emulators/supermodel" \
          "${cfg.configRoot}/emulators/gzdoom" \
          "${cfg.configRoot}/emulators/pico8" \
          "${cfg.configRoot}/emulators/teknoparrot" \
          "${cfg.configRoot}/teknoparrot"
        install -D -m 0644 -o ${cfg.user} -g ${cfg.group} ${displayPolicy} "${cfg.configRoot}/display/policy.json"
        xemu_data_dir="${cfg.dataRoot}/xdg/share/xemu/xemu"
        xemu_bios_dir="${cfg.biosRoot}/xbox"
        install -d -m 0755 -o ${cfg.user} -g ${cfg.group} "$xemu_data_dir"
        if [ ! -f "$xemu_data_dir/eeprom.bin" ]; then
          dd if=/dev/zero of="$xemu_data_dir/eeprom.bin" bs=256 count=1 status=none
          chown ${cfg.user}:${cfg.group} "$xemu_data_dir/eeprom.bin"
          chmod 0644 "$xemu_data_dir/eeprom.bin"
        fi
        printf '%s\n' \
          '[sys.files]' \
          "bootrom_path = '$xemu_bios_dir/mcpx_1.0.bin'" \
          "flashrom_path = '$xemu_bios_dir/Complex_4627.bin'" \
          "eeprom_path = '$xemu_data_dir/eeprom.bin'" \
          "hdd_path = '$xemu_bios_dir/xbox_hdd.qcow2'" \
          >"$xemu_data_dir/xemu.toml"
        chown ${cfg.user}:${cfg.group} "$xemu_data_dir/xemu.toml"
        chmod 0644 "$xemu_data_dir/xemu.toml"
        dolphin_config_dir="${cfg.dataRoot}/xdg/config/dolphin-emu"
        install -d -m 0755 -o ${cfg.user} -g ${cfg.group} "$dolphin_config_dir"
        cat >"$dolphin_config_dir/Dolphin.ini" <<'EOF'
    [Analytics]
    PermissionAsked = True
    Enabled = False
    [Core]
    CPUThread = True
    SkipIPL = True
    GFXBackend = Vulkan
    SIDevice0 = 6
    SIDevice1 = 0
    SIDevice2 = 0
    SIDevice3 = 0
    WiimoteContinuousScanning = True
    WiimoteEnableSpeaker = False
    [Display]
    Fullscreen = True
    RenderWindowWidth = 1920
    RenderWindowHeight = 1080
    RenderWindowAutoSize = False
    [Interface]
    ConfirmStop = False
    [DSP]
    DSPThread = True
    Backend = Cubeb
    Volume = 100
EOF
        cat >"$dolphin_config_dir/GFX.ini" <<'EOF'
    [Settings]
    BackendMultithreading = True
    InternalResolution = 3
    AspectRatio = 0
    ShaderCompilationMode = 2
    ShaderCache = True
    WaitForShadersBeforeStarting = False
    BorderlessFullscreen = True
    [Hardware]
    VSync = False
    [Enhancements]
    MaxAnisotropy = 4
EOF
        : >"$dolphin_config_dir/GCPadNew.ini"
        for slot in 1 2 3 4; do
          index=$((slot - 1))
          cat >>"$dolphin_config_dir/GCPadNew.ini" <<EOF
    [GCPad$slot]
    Device = SDL/$index/Nintendo Switch Pro Controller
    Buttons/A = \`Button 1\`
    Buttons/B = \`Button 0\`
    Buttons/X = \`Button 3\`
    Buttons/Y = \`Button 2\`
    Buttons/Z = \`Button 7\`
    Buttons/Start = \`Button 9\`
    Main Stick/Up = \`Axis 1-\`
    Main Stick/Down = \`Axis 1+\`
    Main Stick/Left = \`Axis 0-\`
    Main Stick/Right = \`Axis 0+\`
    Main Stick/Calibration = 100.00 141.42 100.00 141.42 100.00 141.42 100.00 141.42
    C-Stick/Up = \`Axis 3-\`
    C-Stick/Down = \`Axis 3+\`
    C-Stick/Left = \`Axis 2-\`
    C-Stick/Right = \`Axis 2+\`
    C-Stick/Calibration = 100.00 141.42 100.00 141.42 100.00 141.42 100.00 141.42
    Triggers/L = \`Button 4\`
    Triggers/R = \`Button 5\`
    D-Pad/Up = \`Hat 0 N\`
    D-Pad/Down = \`Hat 0 S\`
    D-Pad/Left = \`Hat 0 W\`
    D-Pad/Right = \`Hat 0 E\`
EOF
        done
        : >"$dolphin_config_dir/WiimoteNew.ini"
        for slot in 1 2 3 4; do
          index=$((slot - 1))
          cat >>"$dolphin_config_dir/WiimoteNew.ini" <<EOF
    [Wiimote$slot]
    Source = 1
    Device = SDL/$index/Nintendo Switch Pro Controller
    Buttons/A = \`Button 1\`
    Buttons/B = \`Button 7\`
    Buttons/1 = \`Button 0\`
    Buttons/2 = \`Button 2\`
    Buttons/- = \`Button 8\`
    Buttons/+ = \`Button 9\`
    Buttons/Home = \`Button 13\`
    D-Pad/Up = \`Hat 0 N\`
    D-Pad/Down = \`Hat 0 S\`
    D-Pad/Left = \`Hat 0 W\`
    D-Pad/Right = \`Hat 0 E\`
    IR/Up = \`Axis 3-\`
    IR/Down = \`Axis 3+\`
    IR/Left = \`Axis 2-\`
    IR/Right = \`Axis 2+\`
    Shake/X = \`Button 10\`
    Shake/Y = \`Button 10\`
    Shake/Z = \`Button 10\`
    Extension = Nunchuk
    Nunchuk/Buttons/C = \`Button 4\`
    Nunchuk/Buttons/Z = \`Button 5\`
    Nunchuk/Stick/Up = \`Axis 1-\`
    Nunchuk/Stick/Down = \`Axis 1+\`
    Nunchuk/Stick/Left = \`Axis 0-\`
    Nunchuk/Stick/Right = \`Axis 0+\`
    Nunchuk/Stick/Calibration = 100.00 141.42 100.00 141.42 100.00 141.42 100.00 141.42
EOF
        done
        cat >>"$dolphin_config_dir/WiimoteNew.ini" <<'EOF'
    [BalanceBoard]
    Source = 0
EOF
        cat >"$dolphin_config_dir/Logger.ini" <<'EOF'
    [Options]
    Verbosity = 1
    WriteToFile = False
    WriteToConsole = False
EOF
        chown -R ${cfg.user}:${cfg.group} "$dolphin_config_dir"
        find "$dolphin_config_dir" -type f -exec chmod 0644 {} +
        cat >"${cfg.configRoot}/emulators/gzdoom/boomer-controls.cfg" <<'EOF'
    // Boomer controller defaults. Managed by Nix.
    use_joystick true
    freelook true
    lookstrafe false

    unbind pad_back
    unbind joy9
    unbind joy14
    unbind axis1plus
    unbind axis1minus
    unbind axis2plus
    unbind axis2minus
    unbind axis3plus
    unbind axis3minus
    unbind axis4plus
    unbind axis4minus
    unbind axis5plus
    unbind axis5minus
    unbind axis6plus
    unbind axis6minus
    unbind axis7plus
    unbind axis7minus
    unbind axis8plus
    unbind axis8minus
    unbind dpadup
    unbind dpaddown
    unbind dpadleft
    unbind dpadright
    unbind pov1up
    unbind pov1down
    unbind pov1left
    unbind pov1right

    bind pad_a +use
    bind pad_b +jump
    bind pad_x togglemap
    bind pad_y crouch
    bind joy2 +use
    bind joy1 +jump
    bind joy4 togglemap
    bind joy3 crouch
    bind rtrigger +attack
    bind ltrigger +altattack
    bind joy7 +altattack
    bind joy8 +attack
    bind lshoulder weapprev
    bind rshoulder weapnext
    bind joy5 weapprev
    bind joy6 weapnext
    bind pad_start menu_main
    bind joy10 menu_main
    bind lthumb crouch
    bind rthumb centerview
    bind axis1minus +moveleft
    bind axis1plus +moveright
    bind axis2minus +forward
    bind axis2plus +back
    bind dpadup +forward
    bind dpaddown +back
    bind dpadleft +moveleft
    bind dpadright +moveright
    bind pov1up +forward
    bind pov1down +back
    bind pov1left +moveleft
    bind pov1right +moveright

    mapbind pad_x togglemap
    mapbind pad_a am_setmark
    mapbind pad_b am_clearmarks
    mapbind joy4 togglemap
    mapbind joy2 am_setmark
    mapbind joy1 am_clearmarks
    mapbind axis1minus +am_panleft
    mapbind axis1plus +am_panright
    mapbind axis2minus +am_panup
    mapbind axis2plus +am_pandown
    mapbind dpadright +am_panright
    mapbind dpadleft +am_panleft
    mapbind dpadup +am_panup
    mapbind dpaddown +am_pandown
    mapbind pov1right +am_panright
    mapbind pov1left +am_panleft
    mapbind pov1up +am_panup
    mapbind pov1down +am_pandown
    mapbind lshoulder +am_zoomout
    mapbind rshoulder +am_zoomin
    mapbind joy5 +am_zoomout
    mapbind joy6 +am_zoomin
EOF
        chown ${cfg.user}:${cfg.group} "${cfg.configRoot}/emulators/gzdoom/boomer-controls.cfg"
        chmod 0644 "${cfg.configRoot}/emulators/gzdoom/boomer-controls.cfg"
        user_home="$(awk -F: -v user=${lib.escapeShellArg cfg.user} '$1 == user { print $6; exit }' /etc/passwd)"
        if [ -n "$user_home" ]; then
          gzdoom_ini="$user_home/.config/gzdoom/gzdoom.ini"
          install -d -m 0755 -o ${cfg.user} -g ${cfg.group} "$(dirname "$gzdoom_ini")"
          ${pkgs.python3}/bin/python3 - "$gzdoom_ini" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
lines = path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True) if path.exists() else []

# GZDoom's Linux SDL joystick backend reads these per-device AxisNmap keys
# from [Joy:JS:N]. Values are EJoyAxis: -1 none, 0 yaw, 1 pitch,
# 2 forward, 3 strafe. SDL exposes Switch Pro as left X/Y, right X/Y,
# ZL/ZR trigger axes, then D-pad hat axes.
axis_settings = {
    "Axis0deadzone": "0.20",
    "Axis0map": "3",
    "Axis1deadzone": "0.20",
    "Axis1map": "2",
    "Axis2deadzone": "0.20",
    "Axis2map": "0",
    "Axis3deadzone": "0.20",
    "Axis3map": "1",
    "Axis3scale": "0.25",
    "Axis4deadzone": "0.25",
    "Axis4map": "-1",
    "Axis5deadzone": "0.25",
    "Axis5map": "-1",
    "Axis6deadzone": "0.10",
    "Axis6map": "3",
    "Axis7deadzone": "0.10",
    "Axis7map": "2",
}
binding_settings = {
    "Pad_A": "+use",
    "Pad_B": "+jump",
    "Pad_X": "togglemap",
    "Pad_Y": "crouch",
    "LTrigger": "+altattack",
    "RTrigger": "+attack",
    "Joy1": "+jump",
    "Joy2": "+use",
    "Joy3": "crouch",
    "Joy4": "togglemap",
    "Joy5": "weapprev",
    "Joy6": "weapnext",
    "Joy7": "+altattack",
    "Joy8": "+attack",
    "Joy9": None,
    "Joy10": "menu_main",
    "Joy11": None,
    "Joy12": None,
    "Joy13": None,
    "Joy14": None,
    "Joy15": None,
    "Joy16": None,
    "Pad_Back": None,
    "Pad_Start": "menu_main",
    "Axis1Minus": "+moveleft",
    "Axis1Plus": "+moveright",
    "Axis2Minus": "+forward",
    "Axis2Plus": "+back",
    "Axis3Minus": None,
    "Axis3Plus": None,
    "Axis4Minus": None,
    "Axis4Plus": None,
    "Axis5Minus": None,
    "Axis5Plus": None,
    "Axis6Minus": None,
    "Axis6Plus": None,
    "Axis7Minus": None,
    "Axis7Plus": None,
    "Axis8Minus": None,
    "Axis8Plus": None,
    "DPadUp": "+forward",
    "DPadDown": "+back",
    "DPadLeft": "+moveleft",
    "DPadRight": "+moveright",
    "POV1Up": "+forward",
    "POV1Down": "+back",
    "POV1Left": "+moveleft",
    "POV1Right": "+moveright",
}
automap_settings = {
    "Pad_A": "am_setmark",
    "Joy2": "am_setmark",
    "Pad_B": "am_clearmarks",
    "Joy1": "am_clearmarks",
    "Pad_X": "togglemap",
    "Pad_Y": None,
    "Joy3": None,
    "Joy4": "togglemap",
    "Axis1Minus": "+am_panleft",
    "Axis1Plus": "+am_panright",
    "Axis2Minus": "+am_panup",
    "Axis2Plus": "+am_pandown",
    "DPadUp": "+am_panup",
    "DPadDown": "+am_pandown",
    "DPadLeft": "+am_panleft",
    "DPadRight": "+am_panright",
    "POV1Up": "+am_panup",
    "POV1Down": "+am_pandown",
    "POV1Left": "+am_panleft",
    "POV1Right": "+am_panright",
}

def upsert_section(input_lines, section, settings):
    out = []
    in_section = False
    found_section = False
    seen = set()

    def append_missing():
        for key, value in settings.items():
            if key not in seen and value is not None:
                out.append(f"{key}={value}\n")
                seen.add(key)

    for line in input_lines:
        stripped = line.strip()
        starts_section = stripped.startswith("[") and stripped.endswith("]")
        if starts_section:
            if in_section:
                append_missing()
            in_section = stripped == f"[{section}]"
            if in_section:
                found_section = True
                seen = set()
            out.append(line)
            continue
        if in_section and "=" in line:
            key = line.split("=", 1)[0].strip()
            if key in settings:
                if settings[key] is not None:
                    out.append(f"{key}={settings[key]}\n")
                seen.add(key)
                continue
        out.append(line)

    if in_section:
        append_missing()
    if not found_section:
        if out and not out[-1].endswith("\n"):
            out[-1] += "\n"
        if out and out[-1].strip():
            out.append("\n")
        out.append(f"[{section}]\n")
        for key, value in settings.items():
            out.append(f"{key}={value}\n")
    return out

for index in range(4):
    lines = upsert_section(lines, f"Joy:JS:{index}", axis_settings)
lines = upsert_section(lines, "Doom.Bindings", binding_settings)
lines = upsert_section(lines, "Doom.AutomapBindings", automap_settings)

path.write_text("".join(lines), encoding="utf-8")
PY
          chown ${cfg.user}:${cfg.group} "$gzdoom_ini"
          chmod 0644 "$gzdoom_ini"
        fi
        for dir in azahar dolphin cemu pcsx2 ppsspp xemu ryubing supermodel gzdoom pico8 teknoparrot; do
          readme="${cfg.configRoot}/emulators/$dir/README.txt"
          if [ ! -e "$readme" ]; then
            printf '%s\n' "Runtime config scaffold for $dir. Durable defaults are managed by Nix; hardware tuning can start here." >"$readme"
            chown ${cfg.user}:${cfg.group} "$readme"
            chmod 0644 "$readme"
          fi
        done
        cat >"${cfg.configRoot}/emulators/scaling-policy.json" <<'EOF'
    {
      "gamescope_fsr": false,
      "aspect_policy": "preserve",
      "standalone_defaults": {
        "azahar": "use emulator internal resolution scaling",
        "cemu": "use Vulkan and graphics packs/internal resolution",
        "dolphin": "use standalone internal resolution; RA profile keeps dual core disabled",
        "pcsx2": "use Vulkan hardware renderer and internal resolution",
        "ppsspp": "use Vulkan and PPSSPP rendering resolution",
        "ryubing": "use Vulkan, docked mode, 16x AF, and emulator-native scaling/filtering",
        "supermodel": "launch with -res=<output_width>,<output_height>",
        "xemu": "use xemu internal resolution scale"
      }
    }
EOF
        chown ${cfg.user}:${cfg.group} "${cfg.configRoot}/emulators/scaling-policy.json"
        chmod 0644 "${cfg.configRoot}/emulators/scaling-policy.json"
        cat >"${cfg.configRoot}/emulators/controller-policy.json" <<'EOF'
    {
      "primary_controller": "Nintendo Switch Pro Controller",
      "vendor_product": "057e:2009",
      "button_policy": "physical_switch_labels",
      "global_sdl_hints": {
        "SDL_GAMECONTROLLER_USE_BUTTON_LABELS": "1"
      },
      "hotkey_policy": {
        "menu": "Square/Capture opens emulator quick menu where stable, home screen where supported, otherwise no-op",
        "modifier": "Select/-",
        "turbo": "Star/Home when exposed by the controller firmware",
        "normal_exit": "Select/- held plus Start/+ double-press sends SIGTERM, then SIGKILL after 5 seconds if needed",
        "gzdoom_menu": "Start/+ opens the GZDoom menu; X toggles the map; Square/Capture is intentionally unbound"
      },
      "managed_defaults": {
        "retroarch": "Switch Pro autoconfig maps physical A/B/X/Y to matching RetroPad labels, Square/Capture to menu, and Select/- as the hotkey modifier",
        "dolphin": "GameCube and Wii profiles map physical A/B/X/Y to matching labels and use SDL slots 0-3; Wii Home uses Square where Dolphin exposes it",
        "ppsspp": "inherits SDL Switch label hints from run-emulator; Square/Home is no-op unless emulator-native support is configured",
        "pcsx2": "inherits SDL Switch label hints from run-emulator; Square/Home is no-op unless emulator-native support is configured",
        "azahar": "inherits SDL Switch label hints from run-emulator; Square/Home is no-op unless emulator-native support is configured",
        "cemu": "inherits SDL Switch label hints from run-emulator; Square/Home is no-op unless emulator-native support is configured",
        "xemu": "inherits SDL Switch label hints from run-emulator; Square/Home is no-op unless emulator-native support is configured",
        "ryubing": "inherits SDL Switch label hints from run-emulator and uses emulator-native controller support; Square/Home is no-op unless emulator-native support is configured",
        "supermodel": "inherits SDL Switch label hints from run-emulator; Square/Home is no-op unless emulator-native support is configured",
        "gzdoom": "run-emulator executes boomer-controls.cfg; A is Use/Confirm, B is Jump/Back, X toggles map, Y toggles crouch, Start/+ opens menu, and right stick controls look"
      },
      "known_gaps": {
        "motion": "hid_nintendo exposes a separate IMU device; emulator support varies",
        "rumble": "hid_nintendo exposes force feedback through ff-memless; emulator support varies"
      }
    }
EOF
        chown ${cfg.user}:${cfg.group} "${cfg.configRoot}/emulators/controller-policy.json"
        chmod 0644 "${cfg.configRoot}/emulators/controller-policy.json"
  '';
in
{
  config = lib.mkIf cfg.enable {
    ghostship.emulation.internal.scripts = {
      inherit
        controllerHotkeys
        controllerHotkeysSmokeTest
        displayProfile
        romCoverageCheck
        runEmulator
        switchProButtonProbe
        syncEmulatorConfigs
        teknoparrotFree
        updateRyubingCanary
        ;
    };
    ghostship.emulation.internal.setupScripts = [ syncEmulatorConfigs ];
  };
}
