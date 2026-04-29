{ config
, lib
, pkgs
, ...
}:

let
  cfg = config.ghostship.emulation;
  emu = config.ghostship.emulation.internal.lib;

  perfPolicy = pkgs.writeText "emulation-perf-policy.json" (builtins.toJSON {
    modes = {
      quick = {
        duration = 75;
        warmup = 15;
        entriesPerSystem = 1;
      };
      overnight = {
        duration = 180;
        warmup = 30;
        entriesPerSystem = 3;
      };
    };
    thresholds = {
      twoD60 = {
        avgFps = 59.5;
        onePercentLow = 57.0;
        p99FrameMs = 20.0;
      };
      threeD60 = {
        avgFps = 58.0;
        onePercentLow = 54.0;
        p99FrameMs = 24.0;
      };
      thirty = {
        avgFps = 29.5;
        onePercentLow = 28.0;
        p99FrameMs = 38.0;
      };
    };
    shaderProfiles = [
      "default"
      "nnedi3-fast"
      "nnedi3-clean"
      "sharp-bilinear-prescale"
      "no-shader"
    ];
    scalingProfiles = [
      "baseline"
      "quality"
      "performance"
    ];
    tuningMatrix = {
      retroarchGlobal = [
        "Vulkan video driver"
        "PipeWire audio"
        "VSync enabled"
        "video_smooth disabled"
        "video_scale_integer disabled by default"
        "threaded_video disabled except performance fallback"
      ];
      retroarch2d = [
        "NNEDI3 clean default"
        "NNEDI3 fast handheld fallback"
        "sharp-bilinear-prescale performance fallback"
        "run-ahead 1 frame only after baseline stability passes"
      ];
      standalone = [
        "Use emulator-native internal resolution before compositor scaling"
        "Keep Gamescope FSR disabled"
        "Prefer Vulkan when stable on AMDGPU"
        "Preserve aspect ratio on odd and ultrawide displays"
      ];
    };
  });

  perfPath = lib.makeBinPath ([
    config.ghostship.emulation.internal.scripts.runEmulator
    config.ghostship.emulation.internal.scripts.displayProfile
    config.ghostship.emulation.internal.packages.retroarchPackage
    pkgs.coreutils
    pkgs.findutils
    pkgs.gawk
    pkgs.gamescope
    pkgs.git
    pkgs.gnugrep
    pkgs.gnused
    pkgs.jq
    pkgs.mangohud
    pkgs.procps
    pkgs.python3
    pkgs.systemd
    pkgs.util-linux
    pkgs.vulkan-tools
    pkgs.wireplumber
  ]
  ++ lib.optionals (config.ghostship.emulation.internal.scripts ? audioRoute) [ config.ghostship.emulation.internal.scripts.audioRoute ]
  ++ lib.optionals (config.ghostship.emulation.internal.scripts ? smokeRomSelect) [ config.ghostship.emulation.internal.scripts.smokeRomSelect ]);

  perfReport = pkgs.writeShellScriptBin "perf-report" ''
        set -euo pipefail
        export PATH=${perfPath}:$PATH

        python3 - "$@" <<'PY'
    import glob
    import json
    import os
    import sys


    def resolve_report(arg):
        if arg:
            if os.path.isdir(arg):
                return os.path.join(arg, "results.jsonl")
            return arg
        reports = sorted(glob.glob("${cfg.dataRoot}/logs/perf/*/results.jsonl"))
        return reports[-1] if reports else ""


    json_mode = False
    args = []
    for arg in sys.argv[1:]:
        if arg == "--json":
            json_mode = True
        else:
            args.append(arg)

    report = resolve_report(args[0] if args else "")
    if not report or not os.path.exists(report):
        print("No perf-test report found.")
        sys.exit(0)

    rows = []
    with open(report, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))

    summary = {
        "report": report,
        "total": len(rows),
        "passed": sum(1 for row in rows if str(row.get("status", "")).startswith("pass")),
        "failed": sum(1 for row in rows if str(row.get("status", "")).startswith("fail")),
        "blocked": sum(1 for row in rows if str(row.get("status", "")).startswith("blocked") or row.get("status") == "missing-rom"),
        "entries": rows,
    }

    if json_mode:
        print(json.dumps(summary, indent=2, sort_keys=True))
        sys.exit(0)

    print("Perf report: {}".format(report))
    print("total={} passed={} failed={} blocked={}".format(summary["total"], summary["passed"], summary["failed"], summary["blocked"]))
    print()
    header = "{:<12} {:<28} {:<23} {:>7} {:>7} {:>7} {:<24} {}".format(
        "SYSTEM", "EMULATOR", "PROFILE", "AVG", "1%LOW", "P99", "STATUS", "ROM"
    )
    print(header)
    print("-" * len(header))
    for row in rows:
        metrics = row.get("metrics") or {}
        avg = metrics.get("avg_fps")
        low = metrics.get("p01_fps")
        p99 = metrics.get("p99_frametime_ms")
        profile = row.get("shader_profile") or row.get("scaling_profile") or "default"
        print("{:<12} {:<28} {:<23} {:>7} {:>7} {:>7} {:<24} {}".format(
            row.get("system_id", "")[:12],
            row.get("emulator", "")[:28],
            profile[:23],
            "{:.2f}".format(avg) if isinstance(avg, (int, float)) else "-",
            "{:.2f}".format(low) if isinstance(low, (int, float)) else "-",
            "{:.2f}".format(p99) if isinstance(p99, (int, float)) else "-",
            row.get("status", "")[:24],
            row.get("name", ""),
        ))

    recommendations = []
    recommendation_path = os.path.join(os.path.dirname(report), "recommended-changes.json")
    if os.path.exists(recommendation_path):
        with open(recommendation_path, encoding="utf-8") as handle:
            recommendations = json.load(handle)
    if recommendations:
        print()
        print("Recommendations:")
        for item in recommendations:
            print("- {} / {}: {}".format(item.get("system_id"), item.get("name"), item.get("recommendation")))
    PY
  '';

  perfCompare = pkgs.writeShellScriptBin "perf-compare" ''
        set -euo pipefail
        export PATH=${perfPath}:$PATH

        python3 - "$@" <<'PY'
    import glob
    import json
    import os
    import sys


    def resolve_report(arg):
        if os.path.isdir(arg):
            return os.path.join(arg, "results.jsonl")
        return arg


    reports = [resolve_report(arg) for arg in sys.argv[1:]]
    if len(reports) < 2:
        latest = sorted(glob.glob("${cfg.dataRoot}/logs/perf/*/results.jsonl"))
        reports = latest[-2:]
    if len(reports) < 2 or not all(os.path.exists(path) for path in reports):
        print("Usage: perf-compare <old-run-dir-or-results.jsonl> <new-run-dir-or-results.jsonl>")
        sys.exit(64)


    def load(path):
        rows = {}
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                row = json.loads(line)
                key = "|".join([
                    row.get("system_id", ""),
                    row.get("emulator", ""),
                    row.get("name", ""),
                    row.get("mode", ""),
                    row.get("shader_profile", ""),
                    row.get("scaling_profile", ""),
                ])
                rows[key] = row
        return rows


    old = load(reports[0])
    new = load(reports[1])
    regressions = []
    print("Comparing {} -> {}".format(reports[0], reports[1]))
    print("{:<12} {:<38} {:>9} {:>9} {:>9} {:>9} {}".format("SYSTEM", "ROM", "OLD FPS", "NEW FPS", "OLD P99", "NEW P99", "RESULT"))
    for key in sorted(set(old) & set(new)):
        left = old[key]
        right = new[key]
        left_metrics = left.get("metrics") or {}
        right_metrics = right.get("metrics") or {}
        old_fps = left_metrics.get("avg_fps")
        new_fps = right_metrics.get("avg_fps")
        old_p99 = left_metrics.get("p99_frametime_ms")
        new_p99 = right_metrics.get("p99_frametime_ms")
        result = "ok"
        if isinstance(old_fps, (int, float)) and isinstance(new_fps, (int, float)) and old_fps > 0:
            if (old_fps - new_fps) / old_fps > 0.03:
                result = "fps-regression"
        if isinstance(old_p99, (int, float)) and isinstance(new_p99, (int, float)):
            if new_p99 - old_p99 > 2.0:
                result = "frametime-regression" if result == "ok" else result + "+frametime"
        if result != "ok":
            regressions.append({"key": key, "result": result})
        print("{:<12} {:<38} {:>9} {:>9} {:>9} {:>9} {}".format(
            right.get("system_id", "")[:12],
            right.get("name", "")[:38],
            "{:.2f}".format(old_fps) if isinstance(old_fps, (int, float)) else "-",
            "{:.2f}".format(new_fps) if isinstance(new_fps, (int, float)) else "-",
            "{:.2f}".format(old_p99) if isinstance(old_p99, (int, float)) else "-",
            "{:.2f}".format(new_p99) if isinstance(new_p99, (int, float)) else "-",
            result,
        ))

    sys.exit(1 if regressions else 0)
    PY
  '';

  perfProfile = pkgs.writeShellScriptBin "perf-profile" ''
    set -euo pipefail
    export PATH=${perfPath}:$PATH
    command="''${1:-show}"
    case "$command" in
      show|matrix|list)
        jq . "${cfg.configRoot}/perf/policy.json"
        ;;
      current)
        echo "RetroArch current profile:"
        readlink "${cfg.configRoot}/retroarch/profiles/current.cfg" 2>/dev/null || echo "custom or missing"
        echo
        echo "Standalone runtime scaling policies:"
        find "${cfg.configRoot}/emulators" -maxdepth 2 -name runtime-scaling-policy.json -print 2>/dev/null | sort | while read -r policy; do
          echo "== $policy =="
          jq . "$policy" || true
        done
        ;;
      latest-recommendations)
        latest="$(find "${cfg.dataRoot}/logs/perf" -mindepth 2 -maxdepth 2 -name recommended-changes.json 2>/dev/null | sort | tail -n 1)"
        [ -n "$latest" ] && jq . "$latest" || echo "No performance recommendations found."
        ;;
      *)
        echo "Usage: perf-profile [show|current|latest-recommendations]" >&2
        exit 64
        ;;
    esac
  '';

  perfTest = pkgs.writeShellScriptBin "perf-test" ''
        set -euo pipefail
        export PATH=${perfPath}:${lib.makeBinPath [ perfReport perfProfile ]}:$PATH

        reexec_for_tty=1
        for arg in "$@"; do
          if [ "$arg" = "--dry-run" ]; then
            reexec_for_tty=0
          fi
        done

        if [ "$(id -u)" = "0" ] && [ "$reexec_for_tty" = 1 ] && [ "''${EMULATION_PERF_NO_REEXEC:-0}" != "1" ]; then
          unit="emulation-perf-test-$(date -u +%Y%m%dT%H%M%SZ)"
          systemctl stop emulation-session.service getty@tty1.service || true
          set +e
          systemd-run --unit="$unit" --wait --collect \
            -p User=${cfg.user} \
            -p Group=${cfg.group} \
            -p PAMName=login \
            -p TTYPath=/dev/tty1 \
            -p TTYReset=yes \
            -p TTYVHangup=yes \
            -p TTYVTDisallocate=yes \
            -p StandardInput=tty \
            -p StandardOutput=journal+console \
            -p StandardError=journal+console \
            -p WorkingDirectory=/home/${cfg.user} \
            -p After=emulation-setup.service \
            -p Conflicts=emulation-session.service \
            env \
            XDG_RUNTIME_DIR="/run/user/1001" \
            DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/1001/bus" \
            ESDE_APPDATA_DIR="${cfg.esde.appDataDir}" \
            EMULATION_PERF_NO_REEXEC=1 \
            "$0" "$@"
          rc=$?
          set -e
          systemctl start getty@tty1.service || true
          journalctl -u "$unit" --no-pager -n 160 >&2 || true
          exit "$rc"
        fi

        mode="quick"
        duration=""
        warmup=""
        manifest="${cfg.configRoot}/smoke/roms.json"
        systems_filter=""
        dry_run=0
        single_system=""
        single_rom=""

        while [ "$#" -gt 0 ]; do
          case "$1" in
            --quick) mode="quick" ;;
            --overnight) mode="overnight" ;;
            --shader-matrix) mode="shader-matrix" ;;
            --scaling-matrix) mode="scaling-matrix" ;;
            --single)
              mode="single"
              shift
              single_system="''${1:-}"
              shift
              single_rom="''${1:-}"
              ;;
            --manifest) shift; manifest="$1" ;;
            --duration) shift; duration="$1" ;;
            --warmup) shift; warmup="$1" ;;
            --systems) shift; systems_filter="$1" ;;
            --dry-run) dry_run=1 ;;
            *) echo "Usage: perf-test [--quick|--overnight|--shader-matrix|--scaling-matrix|--single SYSTEM ROM] [--duration SECONDS] [--warmup SECONDS] [--systems a,b] [--dry-run]" >&2; exit 64 ;;
          esac
          shift
        done

        case "$mode" in
          overnight)
            duration="''${duration:-180}"
            warmup="''${warmup:-30}"
            entries_per_system=3
            ;;
          *)
            duration="''${duration:-75}"
            warmup="''${warmup:-15}"
            entries_per_system=1
            ;;
        esac

        if [ "$mode" != "single" ] && [ ! -r "$manifest" ]; then
          smoke-rom-select "${cfg.romRoot}" "$manifest" >/dev/null
        fi

        run_id="$(date -u +%Y%m%dT%H%M%SZ)"
        if [ "$dry_run" = 1 ]; then
          run_dir="$(mktemp -d)"
          trap 'rm -rf "$run_dir"' EXIT
        else
          log_root="${cfg.dataRoot}/logs/perf"
          run_dir="$log_root/$run_id"
          perf_dir="$run_dir/mangohud"
          install -d -m 0755 "$run_dir" "$perf_dir"
        fi
        report="$run_dir/results.jsonl"
        jobs="$run_dir/jobs.jsonl"
        current_systems='${emu.allSystemsJson}'

        if [ "$dry_run" != 1 ]; then
          display_json="$(display-profile 2>/dev/null || echo '{}')"
          audio_summary="$(wpctl status 2>/dev/null | sed -n '/Audio/,/Video/p' || true)"
          vulkan_summary="$(vulkaninfo --summary 2>/dev/null | head -n 120 || true)"
          retroarch_version="$(retroarch --version 2>/dev/null | head -n 1 || true)"
          gamescope_version="$(gamescope --version 2>/dev/null | head -n 1 || true)"
          mangohud_version="$(mangohud --version 2>/dev/null | head -n 1 || true)"
          git_rev="$(git -C /etc/nixos rev-parse --short HEAD 2>/dev/null || git -C /home/nixos/nixos-config rev-parse --short HEAD 2>/dev/null || echo unknown)"
          jq -n \
            --arg run_id "$run_id" \
            --arg mode "$mode" \
            --arg git_rev "$git_rev" \
            --arg hostname "$(hostname)" \
            --arg kernel "$(uname -r)" \
            --arg retroarch_version "$retroarch_version" \
            --arg gamescope_version "$gamescope_version" \
            --arg mangohud_version "$mangohud_version" \
            --arg audio_summary "$audio_summary" \
            --arg vulkan_summary "$vulkan_summary" \
            --argjson display "$display_json" \
            --argjson systems "$current_systems" \
            '{run_id:$run_id, mode:$mode, git_rev:$git_rev, hostname:$hostname, kernel:$kernel, versions:{retroarch:$retroarch_version,gamescope:$gamescope_version,mangohud:$mangohud_version}, audio_summary:$audio_summary, vulkan_summary:$vulkan_summary, display_profile:$display, systems:$systems}' >"$run_dir/context.json"
        fi

        case "$mode" in
          single)
            [ -n "$single_system" ] && [ -n "$single_rom" ] || { echo "--single requires SYSTEM and ROM" >&2; exit 64; }
            jq -nc --arg system_id "$single_system" --arg rom "$single_rom" --argjson current "$current_systems" '
              ($current[] | select(.id == $system_id)) as $system
              | {system_id:$system.id, folder:$system.folder, emulator:$system.emulator, name:($rom | split("/") | last), rom_path:$rom, mode:"single", shader_profile:"default", scaling_profile:"default"}
            ' >"$jobs"
            ;;
          shader-matrix)
            jq -c --argjson current "$current_systems" --arg systems_filter "$systems_filter" '
              def selected($id): ($systems_filter == "" or (($systems_filter | split(",")) | index($id) != null));
              def current_system($id): (($current[] | select(.id == $id)) // empty);
              ["default","nnedi3-fast","nnedi3-clean","sharp-bilinear-prescale","no-shader"] as $profiles
              | .systems[] as $system
              | select(selected($system.id))
              | (current_system($system.id) // $system) as $cur
              | select(($cur.emulator // $system.emulator) | startswith("retroarch-"))
              | ($system.entries[:1][]?)
              | . as $entry
              | $profiles[]
              | {system_id:$system.id, folder:$system.folder, emulator:($cur.emulator // $system.emulator), name:$entry.name, rom_path:(if (($entry.smoke_path // "") | length) > 0 then $entry.smoke_path else $entry.source_path end), mode:"shader-matrix", shader_profile:., scaling_profile:"default"}
            ' "$manifest" >"$jobs"
            ;;
          scaling-matrix)
            jq -c --argjson current "$current_systems" --arg systems_filter "$systems_filter" '
              def selected($id): ($systems_filter == "" or (($systems_filter | split(",")) | index($id) != null));
              def current_system($id): (($current[] | select(.id == $id)) // empty);
              ["baseline","quality","performance"] as $profiles
              | .systems[] as $system
              | select(selected($system.id))
              | (current_system($system.id) // $system) as $cur
              | select((($cur.emulator // $system.emulator) | startswith("retroarch-")) | not)
              | ($system.entries[:1][]?)
              | . as $entry
              | $profiles[]
              | {system_id:$system.id, folder:$system.folder, emulator:($cur.emulator // $system.emulator), name:$entry.name, rom_path:(if (($entry.smoke_path // "") | length) > 0 then $entry.smoke_path else $entry.source_path end), mode:"scaling-matrix", shader_profile:"default", scaling_profile:.}
            ' "$manifest" >"$jobs"
            ;;
          quick|overnight)
            jq -c --argjson current "$current_systems" --arg systems_filter "$systems_filter" --argjson entries_per_system "$entries_per_system" '
              def selected($id): ($systems_filter == "" or (($systems_filter | split(",")) | index($id) != null));
              def current_system($id): (($current[] | select(.id == $id)) // empty);
              .systems[] as $system
              | select(selected($system.id))
              | (current_system($system.id) // $system) as $cur
              | ($system.entries[:$entries_per_system][]?)
              | {system_id:$system.id, folder:$system.folder, emulator:($cur.emulator // $system.emulator), name:.name, rom_path:(if ((.smoke_path // "") | length) > 0 then .smoke_path else .source_path end), mode:"'$mode'", shader_profile:"default", scaling_profile:"default"}
            ' "$manifest" >"$jobs"
            ;;
        esac

        if [ ! -s "$jobs" ]; then
          echo "No performance jobs selected." >&2
          exit 66
        fi

        if [ "$dry_run" = 1 ]; then
          jq . "$jobs"
          exit 0
        fi

        finalize_result() {
          python3 - "$@" <<'PY'
    import csv
    import json
    import math
    import os
    import re
    import statistics
    import sys

    csv_path, warmup, duration, run_id, system_id, emulator, name, rom_path, mode, shader_profile, scaling_profile, launch_status, exit_code, stdout_path, stderr_path, retroarch_log, display_path = sys.argv[1:]
    warmup = float(warmup)
    duration = float(duration)
    exit_code = int(exit_code)


    def percentile(values, percent):
        if not values:
            return None
        ordered = sorted(values)
        if len(ordered) == 1:
            return ordered[0]
        rank = (len(ordered) - 1) * percent / 100.0
        low = int(math.floor(rank))
        high = int(math.ceil(rank))
        if low == high:
            return ordered[low]
        return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)


    def number(row, key):
        try:
            value = row.get(key, "")
            if value == "":
                return None
            return float(value)
        except Exception:
            return None


    def parse_csv(path):
        if not path or not os.path.exists(path):
            return None
        with open(path, newline="", encoding="utf-8", errors="replace") as handle:
            rows = list(csv.reader(handle))
        if len(rows) < 4:
            return None
        header_index = 2
        header = rows[header_index]
        data = [dict(zip(header, row)) for row in rows[header_index + 1:] if row]
        if not data:
            return None
        elapsed_values = [number(row, "elapsed") for row in data]
        elapsed_values = [value for value in elapsed_values if value is not None]
        filtered = data
        cooldown = min(3.0, max(0.0, duration - warmup) / 4.0)
        if elapsed_values and max(elapsed_values) > warmup * 1000000:
            scale = 1000000000
            start_threshold = warmup * scale
            end_threshold = max(elapsed_values) - (cooldown * scale)
            candidate = [
                row for row in data
                if (number(row, "elapsed") or 0) >= start_threshold
                and (number(row, "elapsed") or 0) <= end_threshold
            ]
            if candidate:
                filtered = candidate
        fps = [number(row, "fps") for row in filtered]
        fps = [value for value in fps if value is not None]
        frametime = [number(row, "frametime") for row in filtered]
        frametime = [value for value in frametime if value is not None]
        metrics = {
            "csv": path,
            "samples": len(filtered),
            "warmup_seconds": warmup,
            "cooldown_seconds": cooldown,
            "duration_seconds": duration,
            "avg_fps": statistics.fmean(fps) if fps else None,
            "p01_fps": percentile(fps, 1) if fps else None,
            "p001_fps": percentile(fps, 0.1) if fps else None,
            "min_fps": min(fps) if fps else None,
            "avg_frametime_ms": statistics.fmean(frametime) if frametime else None,
            "p95_frametime_ms": percentile(frametime, 95) if frametime else None,
            "p99_frametime_ms": percentile(frametime, 99) if frametime else None,
        }
        for source, target in [
            ("gpu_load", "avg_gpu_load"),
            ("cpu_load", "avg_cpu_load"),
            ("gpu_core_clock", "avg_gpu_core_clock"),
            ("gpu_mem_clock", "avg_gpu_mem_clock"),
            ("gpu_temp", "avg_gpu_temp"),
            ("cpu_temp", "avg_cpu_temp"),
            ("ram_used", "avg_ram_used_gib"),
            ("gpu_vram_used", "avg_gpu_vram_used_gib"),
        ]:
            values = [number(row, source) for row in filtered]
            values = [value for value in values if value is not None]
            metrics[target] = statistics.fmean(values) if values else None
        return metrics


    def text(path):
        if not path or not os.path.exists(path):
            return ""
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read()


    def threshold_for(system, emulator_id):
        two_d = {
            "fbneo", "pcengine", "pcenginecd", "gb", "gbc", "gba", "nes", "snes",
            "neogeocd", "ngpc", "gamegear", "genesis", "mastersystem", "segacd",
            "virtualboy", "pico8",
        }
        thirty = {"psp", "ps2", "switch", "xbox", "n3ds", "teknoparrot"}
        compat = {"doom"}
        if system in two_d:
            return {"class": "2d60", "avg_fps": 59.5, "p01_fps": 57.0, "p99_frametime_ms": 20.0}
        if system in thirty:
            return {"class": "30", "avg_fps": 29.5, "p01_fps": 28.0, "p99_frametime_ms": 38.0}
        if system in compat:
            return {"class": "compat", "avg_fps": 0.0, "p01_fps": 0.0, "p99_frametime_ms": 9999.0}
        return {"class": "3d60", "avg_fps": 58.0, "p01_fps": 54.0, "p99_frametime_ms": 24.0}


    def recommendation(status, metrics, threshold):
        if status == "blocked-missing-runtime":
            return "Add the required BIOS, firmware, keys, or emulator runtime files and rerun this job."
        if status == "missing-rom":
            return "Fix the smoke ROM manifest path or sync the selected smoke ROM."
        if status == "fail-no-metrics":
            return "Launch completed but MangoHud did not emit CSV metrics; verify MangoHud support for this emulator path."
        if status == "fail-fatal-log":
            return "Inspect stderr and emulator logs before tuning; this is a launch/runtime error, not a frame pacing failure."
        if not str(status).startswith("fail"):
            return ""
        gpu = (metrics or {}).get("avg_gpu_load")
        cpu = (metrics or {}).get("avg_cpu_load")
        if emulator.startswith("retroarch-"):
            if shader_profile.startswith("nnedi3"):
                return "Try nnedi3-fast, then sharp-bilinear-prescale. If it still misses frame budget, test the performance profile with threaded_video."
            if shader_profile in {"sharp-bilinear-prescale", "sharp-bilinear-simple"}:
                return "Try no-shader, then the performance profile. Keep Gamescope FSR off."
            return "Try the RetroArch performance profile and inspect core-specific dynarec/internal-resolution options."
        if gpu is not None and gpu >= 90:
            return "GPU-bound: lower emulator-native internal resolution or expensive AA/filtering before changing Gamescope."
        if cpu is not None and cpu >= 80:
            return "CPU-bound: prefer dynarec/performance core options or emulator performance profile; avoid global accuracy increases."
        return "Lower emulator-native internal resolution one step and rerun the same ROM."


    combined_log = (text(stderr_path) + "\n" + text(retroarch_log)).lower()
    status = launch_status
    if launch_status == "missing-rom":
        status = "missing-rom"
    elif re.search(r"(missing|not found|required|cannot open|no).*?(bios|firmware|keys|prod\.keys|title\.keys|mcpx|bootrom|system card)|(bios|firmware|keys|prod\.keys|title\.keys|mcpx|bootrom|system card).*?(missing|not found|required|cannot open)", combined_log):
        status = "blocked-missing-runtime"
    elif re.search(r"failed to open libretro core|failed to load content|failed to extract content|could not read content file|file format is unknown|unknown disk format|not a psp game|failed to (create|initialize).*vulkan|vk_error_|segmentation fault|trace/breakpoint trap", combined_log):
        status = "fail-fatal-log"

    metrics = parse_csv(csv_path)
    threshold = threshold_for(system_id, emulator)
    if status.startswith("pass"):
        if metrics is None:
            status = "fail-no-metrics"
        elif threshold["class"] == "compat":
            status = "pass-performance"
        else:
            avg = metrics.get("avg_fps")
            low = metrics.get("p01_fps")
            p99 = metrics.get("p99_frametime_ms")
            if (
                isinstance(avg, (int, float))
                and isinstance(low, (int, float))
                and isinstance(p99, (int, float))
                and avg >= threshold["avg_fps"]
                and low >= threshold["p01_fps"]
                and p99 <= threshold["p99_frametime_ms"]
            ):
                status = "pass-performance"
            else:
                status = "fail-performance"

    display = {}
    if os.path.exists(display_path):
        try:
            with open(display_path, encoding="utf-8") as handle:
                display = json.load(handle)
        except Exception:
            display = {}

    result = {
        "run_id": run_id,
        "system_id": system_id,
        "emulator": emulator,
        "name": name,
        "rom_path": rom_path,
        "mode": mode,
        "shader_profile": shader_profile,
        "scaling_profile": scaling_profile,
        "launch_status": launch_status,
        "status": status,
        "exit_code": exit_code,
        "stdout": stdout_path,
        "stderr": stderr_path,
        "retroarch_log": retroarch_log,
        "mangohud_csv": csv_path,
        "display_profile": display,
        "metrics": metrics,
        "threshold": threshold,
    }
    rec = recommendation(status, metrics, threshold)
    if rec:
        result["recommendation"] = rec
    print(json.dumps(result, sort_keys=True))
    PY
        }

        index=0
        while read -r job; do
          index=$((index + 1))
          system_id="$(jq -r '.system_id' <<<"$job")"
          emulator="$(jq -r '.emulator' <<<"$job")"
          name="$(jq -r '.name' <<<"$job")"
          rom_path="$(jq -r '.rom_path' <<<"$job")"
          shader_profile="$(jq -r '.shader_profile' <<<"$job")"
          scaling_profile="$(jq -r '.scaling_profile' <<<"$job")"
          job_mode="$(jq -r '.mode' <<<"$job")"
          safe_name="$(printf '%s' "$name" | tr -c 'A-Za-z0-9_.-' '_')"
          prefix="$(printf '%03d-%s-%s' "$index" "$system_id" "$safe_name")"
          stdout="$run_dir/$prefix.out"
          stderr="$run_dir/$prefix.err"
          retroarch_log="$run_dir/$prefix.retroarch.log"
          display_file="$run_dir/$prefix.display.json"
          display-profile >"$display_file" 2>/dev/null || echo '{}' >"$display_file"
          before_csv="$(mktemp)"
          after_csv="$(mktemp)"
          find "$perf_dir" -type f -name '*.csv' 2>/dev/null | sort >"$before_csv"
          start_epoch="$(date +%s)"
          rc=0
          launch_status="pass"

          if [ ! -e "$rom_path" ]; then
            launch_status="missing-rom"
            rc=66
          else
            if printf '%s' "$emulator" | grep -q '^retroarch-'; then
              : >"${cfg.dataRoot}/logs/retroarch/retroarch.log" 2>/dev/null || true
            fi
            set +e
            EMULATION_MANGOHUD=1 \
            EMULATION_RETROARCH_PROFILE="$shader_profile" \
            EMULATION_PERF_SCALING_PROFILE="$scaling_profile" \
            MANGOHUD_CONFIG="autostart_log=1,output_folder=$perf_dir,log_duration=$duration" \
            timeout --kill-after=5s "$duration" run-emulator "$system_id" "$emulator" "$rom_path" >"$stdout" 2>"$stderr"
            rc=$?
            set -e
            if printf '%s' "$emulator" | grep -q '^retroarch-' && [ -s "${cfg.dataRoot}/logs/retroarch/retroarch.log" ]; then
              cp "${cfg.dataRoot}/logs/retroarch/retroarch.log" "$retroarch_log" || true
              {
                printf '\n==== retroarch.log ====\n'
                cat "$retroarch_log"
              } >>"$stderr" || true
            fi
            elapsed="$(( $(date +%s) - start_epoch ))"
            case "$rc" in
              0)
                if [ "$elapsed" -lt 5 ] && [ "''${duration%%.*}" -ge 8 ]; then
                  launch_status="fail-early-exit"
                else
                  launch_status="pass-exited"
                fi
                ;;
              124) launch_status="pass-timeout" ;;
              *) launch_status="fail-exited" ;;
            esac
          fi

          find "$perf_dir" -type f -name '*.csv' 2>/dev/null | sort >"$after_csv"
          csv_path=""
          while read -r candidate; do
            csv_path="$candidate"
          done < <(comm -13 "$before_csv" "$after_csv" || true)
          rm -f "$before_csv" "$after_csv"

          finalize_result "$csv_path" "$warmup" "$duration" "$run_id" "$system_id" "$emulator" "$name" "$rom_path" "$job_mode" "$shader_profile" "$scaling_profile" "$launch_status" "$rc" "$stdout" "$stderr" "$retroarch_log" "$display_file" >>"$report"
          tail -n 1 "$report" | jq -r '"\(.system_id) \(.name): \(.status) avg=\((.metrics.avg_fps // "-")|tostring) p99=\((.metrics.p99_frametime_ms // "-")|tostring)"'
        done <"$jobs"

        jq -s '[.[] | select(.recommendation != null) | {system_id, emulator, name, mode, shader_profile, scaling_profile, status, recommendation}]' "$report" >"$run_dir/recommended-changes.json"
        chown -R ${cfg.user}:${cfg.group} "$run_dir" 2>/dev/null || true
        perf-report "$report"
  '';

  syncPerfConfig = pkgs.writeShellScriptBin "sync-perf-config" ''
    set -euo pipefail
    install -d -m 0755 -o ${cfg.user} -g ${cfg.group} \
      "${cfg.configRoot}/perf" \
      "${cfg.dataRoot}/logs/perf"
    install -D -m 0644 -o ${cfg.user} -g ${cfg.group} ${perfPolicy} "${cfg.configRoot}/perf/policy.json"
  '';
in
{
  config = lib.mkIf cfg.enable {
    ghostship.emulation.internal.scripts = {
      inherit
        perfCompare
        perfProfile
        perfReport
        perfTest
        syncPerfConfig
        ;
    };
    ghostship.emulation.internal.setupScripts = [ syncPerfConfig ];
  };
}
