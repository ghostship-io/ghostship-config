{ config, lib, pkgs, ... }:

let
  cfg = config.ghostship.emulation;
  emu = config.ghostship.emulation.internal.lib;

  smokePath = lib.makeBinPath [
    config.ghostship.emulation.internal.scripts.runEmulator
    pkgs.coreutils
    pkgs.findutils
    pkgs.gawk
    pkgs.gnugrep
    pkgs.gnused
    pkgs.jq
    pkgs.rsync
  ];

  smokeRomSelect = pkgs.writeShellScriptBin "smoke-rom-select" ''
    set -euo pipefail
    export PATH=${smokePath}:$PATH

    source_root="''${1:-/mnt/z/Library/ROMs/roms}"
    manifest="''${2:-${cfg.configRoot}/smoke/roms.json}"
    if [ ! -d "$source_root" ]; then
      source_root="${cfg.romRoot}"
    fi
    if [ ! -d "$source_root" ]; then
      echo "No ROM source root found." >&2
      exit 66
    fi

    preferred_regex='metroid|god[ _:-]*of[ _:-]*war|halo|resident[ _:-]*evil|conker|star[ _:-]*ocean|gran[ _:-]*turismo|forza|f-zero|mario[ _:-]*kart|zelda|xenoblade|hyrule|pokemon|tekken|ridge[ _:-]*racer|soulcalibur|panzer[ _:-]*dragoon|virtua|daytona|outrun|doom|quake|final[ _:-]*fantasy|kingdom[ _:-]*hearts|samba[ _:-]*de[ _:-]*amigo|sonic[ _:-]*adventure'

    manifest_dir="$(dirname "$manifest")"
    mkdir -p "$manifest_dir"
    chmod 0755 "$manifest_dir" 2>/dev/null || true
    chown ${cfg.user}:${cfg.group} "$manifest_dir" 2>/dev/null || true
    systems_tmp="$(mktemp)"
    printf '%s' '${emu.allSystemsJson}' | jq -c '.[]' | while read -r system; do
      folder="$(jq -r '.folder' <<<"$system")"
      system_dir="$source_root/$folder"
      [ -d "$system_dir" ] || continue

      scored_tmp="$(mktemp)"
      find "$system_dir" -mindepth 1 -maxdepth 1 -print0 | while IFS= read -r -d "" entry; do
        [ -e "$entry" ] || continue
        name="''${entry##*/}"
        size="$(du -sb "$entry" 2>/dev/null | awk '{print $1}')"
        [ -n "$size" ] || size=0
        boost=0
        if printf '%s\n' "$name" | grep -Eiq "$preferred_regex"; then
          boost=1000000000000000
        fi
        printf '%020d\t%s\t%s\n' "$((boost + size))" "$size" "$entry"
      done >"$scored_tmp"

      [ -s "$scored_tmp" ] || {
        rm -f "$scored_tmp"
        continue
      }

      entries_tmp="$(mktemp)"
      sorted_tmp="$(mktemp)"
      sort -r "$scored_tmp" >"$sorted_tmp"
      head -n 3 "$sorted_tmp" | while IFS=$'\t' read -r _score size entry; do
        name="''${entry##*/}"
        jq -n \
          --arg name "$name" \
          --arg source_path "$entry" \
          --arg smoke_path "${cfg.dataRoot}/smoke-roms/$folder/$name" \
          --argjson size "$size" \
          '{name:$name, source_path:$source_path, smoke_path:$smoke_path, size:$size}'
      done >"$entries_tmp"

        jq -n \
          --argjson system "$system" \
          --slurpfile entries "$entries_tmp" \
          '{id:$system.id, folder:$system.folder, fullname:$system.fullname, emulator:$system.emulator, entries:$entries}'

      rm -f "$scored_tmp" "$entries_tmp" "$sorted_tmp"
    done >"$systems_tmp"

    jq -s \
      --arg generated_at "$(date -u +%FT%TZ)" \
      --arg source_root "$source_root" \
      --arg target_root "${cfg.dataRoot}/smoke-roms" \
      '{generated_at:$generated_at, source_root:$source_root, target_root:$target_root, systems:.}' \
      "$systems_tmp" >"$manifest.tmp"
    rm -f "$systems_tmp"
    chown ${cfg.user}:${cfg.group} "$manifest.tmp" 2>/dev/null || true
    chmod 0644 "$manifest.tmp"
    mv "$manifest.tmp" "$manifest"
    jq '{generated_at, source_root, systems: [.systems[] | {id, count:(.entries | length)}]}' "$manifest"
  '';

  smokeRomSync = pkgs.writeShellScriptBin "smoke-rom-sync" ''
    set -euo pipefail
    export PATH=${smokePath}:${lib.makeBinPath [ smokeRomSelect ]}:$PATH

    source_root="''${1:-/mnt/z/Library/ROMs/roms}"
    manifest="${cfg.configRoot}/smoke/roms.json"
    smoke-rom-select "$source_root" "$manifest"
    install -d -m 0755 "${cfg.dataRoot}/smoke-roms"
    chown ${cfg.user}:${cfg.group} "${cfg.dataRoot}/smoke-roms" 2>/dev/null || true

    jq -c '.systems[] as $system | $system.entries[] | {system_id:$system.id, folder:$system.folder, emulator:$system.emulator, name:.name, source_path:.source_path, smoke_path:.smoke_path}' "$manifest" |
      while read -r item; do
        source_path="$(jq -r '.source_path' <<<"$item")"
        smoke_path="$(jq -r '.smoke_path' <<<"$item")"
        [ -e "$source_path" ] || {
          echo "missing source: $source_path" >&2
          continue
        }
        if [ -d "$source_path" ]; then
          install -d -m 0755 "$smoke_path"
          chown ${cfg.user}:${cfg.group} "$smoke_path" 2>/dev/null || true
          rsync -a --delete "$source_path/" "$smoke_path/"
        else
          install -d -m 0755 "$(dirname "$smoke_path")"
          chown ${cfg.user}:${cfg.group} "$(dirname "$smoke_path")" 2>/dev/null || true
          rsync -a "$source_path" "$smoke_path"
        fi
      done

    chown -R ${cfg.user}:${cfg.group} "${cfg.dataRoot}/smoke-roms" "${cfg.configRoot}/smoke" 2>/dev/null || true
    smoke-report --manifest "$manifest" || true
  '';

  smokeTest = pkgs.writeShellScriptBin "smoke-test" ''
    set -euo pipefail
    export PATH=${smokePath}:${lib.makeBinPath [ smokeRomSelect smokeReport ]}:$PATH

    if [ "$(id -u)" = "0" ] && [ "''${EMULATION_SMOKE_NO_REEXEC:-0}" != "1" ]; then
      unit="emulation-smoke-test-$(date -u +%Y%m%dT%H%M%SZ)"
      ${pkgs.systemd}/bin/systemctl stop emulation-session.service getty@tty1.service || true
      set +e
      ${pkgs.systemd}/bin/systemd-run --unit="$unit" --wait --collect \
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
        -p CapabilityBoundingSet= \
        -p AmbientCapabilities= \
        -p After=emulation-setup.service \
        -p Conflicts=emulation-session.service \
        ${pkgs.coreutils}/bin/env \
        XDG_RUNTIME_DIR="/run/user/1001" \
        DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/1001/bus" \
        ESDE_APPDATA_DIR="${cfg.esde.appDataDir}" \
        EMULATION_SMOKE_NO_REEXEC=1 \
        EMULATION_SMOKE_DURATION="''${EMULATION_SMOKE_DURATION:-90}" \
        "$0" "$@"
      rc=$?
      set -e
      ${pkgs.systemd}/bin/systemctl start getty@tty1.service || true
      ${pkgs.systemd}/bin/journalctl -u "$unit" --no-pager -n 120 >&2 || true
      exit "$rc"
    fi

    dry_run=0
    manifest="${cfg.configRoot}/smoke/roms.json"
    duration="''${EMULATION_SMOKE_DURATION:-90}"
    while [ "$#" -gt 0 ]; do
      case "$1" in
        --dry-run) dry_run=1 ;;
        --manifest) shift; manifest="$1" ;;
        --duration) shift; duration="$1" ;;
        *) echo "Usage: smoke-test [--dry-run] [--manifest FILE] [--duration SECONDS]" >&2; exit 64 ;;
      esac
      shift
    done

    [ -r "$manifest" ] || smoke-rom-select "${cfg.romRoot}" "$manifest"
    current_systems='${emu.allSystemsJson}'
    if [ "$dry_run" = 1 ]; then
      jq -r --argjson current "$current_systems" '
        def current_emulator($id): (($current[] | select(.id == $id) | .emulator) // empty);
        .systems[] as $system
        | $system.entries[]
        | "run-emulator " + ($system.id | @sh) + " " + ((current_emulator($system.id) // $system.emulator) | @sh) + " " + ((if (.smoke_path | length) > 0 then .smoke_path else .source_path end) | @sh)
      ' "$manifest"
      exit 0
    fi

    log_root="${cfg.dataRoot}/logs/smoke"
    run_id="$(date -u +%Y%m%dT%H%M%SZ)"
    run_dir="$log_root/$run_id"
    perf_dir="$run_dir/perf"
    install -d -m 0755 "$run_dir" "$perf_dir"
    chown ${cfg.user}:${cfg.group} "$run_dir" "$perf_dir" 2>/dev/null || true
    report="$run_dir/results.jsonl"

    jq -c --argjson current "$current_systems" '
      def current_emulator($id): (($current[] | select(.id == $id) | .emulator) // empty);
      .systems[] as $system
      | $system.entries[]
      | {system_id:$system.id, folder:$system.folder, emulator:(current_emulator($system.id) // $system.emulator), name:.name, source_path:.source_path, smoke_path:.smoke_path}
    ' "$manifest" |
      while read -r item; do
        system_id="$(jq -r '.system_id' <<<"$item")"
        emulator="$(jq -r '.emulator' <<<"$item")"
        name="$(jq -r '.name' <<<"$item")"
        rom_path="$(jq -r '.smoke_path' <<<"$item")"
        [ -e "$rom_path" ] || rom_path="$(jq -r '.source_path' <<<"$item")"
        safe_name="$(printf '%s' "$name" | tr '/ ' '__')"
        stdout="$run_dir/$system_id-$safe_name.out"
        stderr="$run_dir/$system_id-$safe_name.err"
        retroarch_log="$run_dir/$system_id-$safe_name.retroarch.log"
        start_epoch="$(date +%s)"
        status="pass"
        rc=0

        if [ ! -e "$rom_path" ]; then
          status="missing-rom"
          rc=66
        else
          if printf '%s' "$emulator" | grep -q '^retroarch-'; then
            : >"${cfg.dataRoot}/logs/retroarch/retroarch.log" 2>/dev/null || true
          fi
          set +e
          EMULATION_MANGOHUD=1 \
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
          elapsed_after="$(( $(date +%s) - start_epoch ))"
          case "$rc" in
            0)
              if [ "$elapsed_after" -lt 5 ] && [ "''${duration%%.*}" -ge 8 ]; then
                status="fail-early-exit"
              else
                status="pass-exited"
              fi
              ;;
            124) status="pass-timeout" ;;
            *) status="fail-exited" ;;
          esac
          if grep -Eiq 'missing RetroArch core|failed to open libretro core|failed to load content|failed to extract content|could not read content file|core failed to load|required firmware|no bios detected|cannot open bios|bios.*(missing|not found)|file format is unknown|unknown disk format|not a psp game|no content, starting dummy core|CPU_Init.*recognize|failed to (create|initialize).*Vulkan|Vulkan.*initialization.*failed|VK_ERROR_(INITIALIZATION_FAILED|DEVICE_LOST|OUT_OF_DEVICE_MEMORY)|segmentation fault|Trace/breakpoint trap' "$stderr" 2>/dev/null; then
            status="fail-fatal-log"
          fi
        fi

        end_epoch="$(date +%s)"
        jq -nc \
          --arg run_id "$run_id" \
          --arg system_id "$system_id" \
          --arg emulator "$emulator" \
          --arg name "$name" \
          --arg rom_path "$rom_path" \
          --arg status "$status" \
          --arg stdout "$stdout" \
          --arg stderr "$stderr" \
          --arg retroarch_log "$retroarch_log" \
          --argjson exit_code "$rc" \
          --argjson duration_seconds "$((end_epoch - start_epoch))" \
          '{run_id:$run_id, system_id:$system_id, emulator:$emulator, name:$name, rom_path:$rom_path, status:$status, exit_code:$exit_code, duration_seconds:$duration_seconds, stdout:$stdout, stderr:$stderr, retroarch_log:$retroarch_log}' >>"$report"
      done

    chown -R ${cfg.user}:${cfg.group} "$run_dir" 2>/dev/null || true
    smoke-report "$report"
  '';

  smokeReport = pkgs.writeShellScriptBin "smoke-report" ''
    set -euo pipefail
    export PATH=${smokePath}:$PATH

    if [ "''${1:-}" = "--manifest" ]; then
      manifest="$2"
      jq --argjson current '${emu.allSystemsJson}' '
        def current_emulator($id): (($current[] | select(.id == $id) | .emulator) // empty);
        {generated_at, source_root, target_root, systems: [.systems[] | {id, emulator:(current_emulator(.id) // .emulator), count:(.entries | length), entries:[.entries[].name]}]}
      ' "$manifest"
      exit 0
    fi

    report="''${1:-}"
    if [ -z "$report" ]; then
      report="$(find "${cfg.dataRoot}/logs/smoke" -type f -name results.jsonl 2>/dev/null | sort | tail -n 1)"
    fi
    [ -n "$report" ] && [ -r "$report" ] || {
      echo "No smoke-test report found."
      exit 0
    }
    jq -s --arg report "$report" '
      {
        report:$report,
        total:length,
        passed:([.[] | select(.status | startswith("pass"))] | length),
        failed:([.[] | select((.status | startswith("fail")) or .status == "missing-rom")] | length),
        dry_run:([.[] | select(.status == "dry-run")] | length),
        entries:[.[] | {system_id, emulator, name, status, exit_code, duration_seconds}]
      }
    ' "$report"
  '';
in
{
  config = lib.mkIf cfg.enable {
    ghostship.emulation.internal.scripts = {
      inherit
        smokeReport
        smokeRomSelect
        smokeRomSync
        smokeTest
        ;
    };
  };
}
