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

  audioRoute = pkgs.writeShellScriptBin "audio-route" ''
    set -euo pipefail
    volume="''${EMULATION_AUDIO_VOLUME:-0.85}"
    export PATH=${
      lib.makeBinPath [
        pkgs.coreutils
        pkgs.gawk
        pkgs.gnugrep
        pkgs.gnused
        pkgs.jq
        pkgs.pulseaudio
        pkgs.util-linux
        pkgs.wireplumber
      ]
    }:$PATH

    if [ "$(id -un)" != "${cfg.user}" ]; then
      uid="$(id -u ${cfg.user})"
      exec runuser -u ${cfg.user} -- env \
        HOME="/home/${cfg.user}" \
        USER="${cfg.user}" \
        LOGNAME="${cfg.user}" \
        XDG_RUNTIME_DIR="/run/user/$uid" \
        DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$uid/bus" \
        EMULATION_AUDIO_VOLUME="$volume" \
        "$0" "$@"
    fi

    export HOME="''${HOME:-/home/${cfg.user}}"
    export XDG_RUNTIME_DIR="''${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
    export PULSE_SERVER="unix:$XDG_RUNTIME_DIR/pulse/native"
    for _ in $(seq 1 20); do
      [ -S "$XDG_RUNTIME_DIR/bus" ] && [ -S "$XDG_RUNTIME_DIR/pulse/native" ] && break
      sleep 0.25
    done
    if [ -S "$XDG_RUNTIME_DIR/bus" ]; then
      export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"
    fi

    pactl() {
      command pactl --server="$PULSE_SERVER" "$@"
    }

    audio_pref="${cfg.configRoot}/audio/output.json"

    choose_bluetooth_sink() {
      preferred="''${1:-}"
      pactl --format=json list sinks 2>/dev/null | jq -r --arg preferred "$preferred" '
        [
          .[]
          | select(
              if $preferred != "" then
                .name == $preferred
              else
                ((.properties["device.bus"] // "") == "bluetooth")
                or ((.name // "") | test("bluez"; "i"))
                or ((.description // "") | test("bluetooth|headphone|headset"; "i"))
              end
            )
          | {
              name: .name,
              description: .description,
              preferred: (.name == $preferred)
            }
        ]
        | sort_by(.preferred)
        | reverse
        | .[0] // empty
        | if . == "" then empty else [.name, .description] | @tsv end
      '
    }

    choose_profile() {
      pactl --format=json list cards 2>/dev/null | jq -r '
        [
          .[]
          | select((.properties["device.bus"] // "") == "pci")
          | select(
              (.properties["device.vendor.id"] // "") == "0x1002"
              or ((.properties["device.description"] // "") | test("HDMI|Radeon|Navi"; "i"))
            )
          | . as $card
          | ($card.ports // {} | to_entries[]?
            | select(((.value.properties["port.type"] // .value.type // "") | ascii_downcase) == "hdmi")
            | select((.value.availability // "available") == "available")
            | . as $port
            | ($port.value.profiles[]? | select(startswith("output:hdmi-stereo")))
            | select(($card.profiles[.].available // false) == true)
            | {
                card: $card.name,
                profile: .,
                port: $port.key,
                description: $port.value.description,
                priority: ($port.value.priority // 0)
              }
          )
        ]
        | sort_by(.priority)
        | reverse
        | .[0] // empty
        | if . == "" then empty else [.card, .profile, .port, .description] | @tsv end
      '
    }

    choose_sink() {
      pactl --format=json list sinks 2>/dev/null | jq -r '
        [
          .[]
          | select((.properties["device.bus"] // "") == "pci")
          | select(
              (.properties["device.vendor.id"] // "") == "0x1002"
              or ((.description // "") | test("HDMI|DisplayPort|Radeon|Navi"; "i"))
            )
          | select(
              ((.active_port // "") | test("hdmi"; "i"))
              or ((.description // "") | test("HDMI|DisplayPort"; "i"))
            )
          | . as $sink
          | select(((($sink.ports // []) | map(select(.name == ($sink.active_port // ""))) | .[0].availability) // "available") != "not available")
          | {
              name: $sink.name,
              description: $sink.description,
              priority: (((($sink.ports // []) | map(select(.name == ($sink.active_port // ""))) | .[0].priority) // 0) | tonumber? // 0)
            }
        ]
        | sort_by(.priority)
        | reverse
        | .[0] // empty
        | if . == "" then empty else [.name, .description] | @tsv end
      '
    }

    preferred_bluetooth_sink=""
    if [ -r "$audio_pref" ]; then
      preferred_bluetooth_sink="$(jq -r 'select(.mode == "bluetooth") | .sink // empty' "$audio_pref" 2>/dev/null || true)"
    fi
    if [ -n "$preferred_bluetooth_sink" ]; then
      for attempt in $(seq 1 10); do
        sink_line="$(choose_bluetooth_sink "$preferred_bluetooth_sink" || true)"
        if [ -n "$sink_line" ]; then
          sink_name="$(printf '%s\n' "$sink_line" | awk -F '\t' '{print $1}')"
          sink_description="$(printf '%s\n' "$sink_line" | awk -F '\t' '{print $2}')"
          pactl set-default-sink "$sink_name"
          pactl set-sink-mute "$sink_name" 0
          wpctl set-volume @DEFAULT_AUDIO_SINK@ "$volume"
          echo "Default audio sink set to $sink_name ($sink_description) at volume $volume"
          wpctl status | sed -n '/Audio/,/Video/p'
          exit 0
        fi
        sleep 1
      done
      echo "Preferred Bluetooth audio sink is unavailable; falling back to HDMI." >&2
    fi

    sink_name=""
    sink_description=""
    profile_line=""
    for attempt in $(seq 1 20); do
      profile_line="$(choose_profile || true)"
      if [ -n "$profile_line" ]; then
        card="$(printf '%s\n' "$profile_line" | awk -F '\t' '{print $1}')"
        profile="$(printf '%s\n' "$profile_line" | awk -F '\t' '{print $2}')"
        pactl set-card-profile "$card" "$profile" >/dev/null 2>&1 || true
      fi

      sink_line="$(choose_sink || true)"
      if [ -n "$sink_line" ]; then
        sink_name="$(printf '%s\n' "$sink_line" | awk -F '\t' '{print $1}')"
        sink_description="$(printf '%s\n' "$sink_line" | awk -F '\t' '{print $2}')"
        [ -n "$sink_name" ] && break
      fi

      status="$(wpctl status 2>/dev/null || true)"
      wpctl_sink="$(printf '%s\n' "$status" | awk '
        /Navi 21\/23 HDMI\/DP Audio Controller Digital Stereo/ {
          for (i = 1; i <= NF; i++) if ($i ~ /^[0-9]+\.$/) { sub(/\./, "", $i); print $i; exit }
        }
      ')"
      if [ -z "$wpctl_sink" ]; then
        wpctl_sink="$(printf '%s\n' "$status" | awk '
          /Digital Stereo \(HDMI/ {
            for (i = 1; i <= NF; i++) if ($i ~ /^[0-9]+\.$/) { sub(/\./, "", $i); print $i; exit }
          }
        ')"
      fi
      if [ -n "$wpctl_sink" ]; then
        wpctl set-default "$wpctl_sink"
        wpctl set-volume "$wpctl_sink" "$volume"
        echo "Default audio sink set to PipeWire node $wpctl_sink at volume $volume"
        wpctl status | sed -n '/Audio/,/Video/p'
        exit 0
      fi
      sleep 1
    done

    if [ -z "$sink_name" ]; then
      echo "No HDMI audio sink found; leaving PipeWire default unchanged." >&2
      wpctl status || true
      exit 0
    fi

    pactl set-default-sink "$sink_name"
    pactl set-sink-mute "$sink_name" 0
    wpctl set-volume @DEFAULT_AUDIO_SINK@ "$volume"
    echo "Default audio sink set to $sink_name ($sink_description) at volume $volume"
    wpctl status | sed -n '/Audio/,/Video/p'
  '';
in
{
  config = lib.mkIf cfg.enable (
    lib.mkMerge [
      {
        nixpkgs.config.allowUnfreePredicate =
          pkg:
          let
            name = lib.getName pkg;
          in
          lib.hasPrefix "libretro-" name
          || builtins.elem name [
            "pico-8"
            "steam-run"
            "steam-unwrapped"
          ];

        users.groups.${cfg.group} = { };
        users.users.${cfg.user} = {
          isNormalUser = true;
          group = cfg.group;
          extraGroups = [
            "audio"
            "input"
            "render"
            "video"
            "networkmanager"
          ];
          home = "/home/${cfg.user}";
          createHome = true;
        };

        boot.kernelParams = [ "amd_pstate=active" ];
        boot.kernelModules = [ "amdgpu" ];

        powerManagement.cpuFreqGovernor = "performance";
        security.rtkit.enable = true;
        services.upower.enable = true;
        systemd.services.upower.wantedBy = lib.mkForce [ "multi-user.target" ];

        services.pipewire = {
          enable = true;
          alsa = {
            enable = true;
            support32Bit = true;
          };
          pulse.enable = true;
          extraConfig.pipewire."91-emulation-stable-audio" = {
            "context.properties" = {
              "default.clock.rate" = 48000;
              "default.clock.quantum" = 1024;
              "default.clock.min-quantum" = 512;
              "default.clock.max-quantum" = 2048;
            };
          };
          extraConfig.pipewire-pulse."91-emulation-stable-audio" = {
            "pulse.properties" = {
              "pulse.min.req" = "512/48000";
              "pulse.default.req" = "1024/48000";
              "pulse.default.tlength" = "4096/48000";
              "pulse.min.quantum" = "512/48000";
            };
          };
        };

        systemd.user.services.emulation-audio-route = {
          description = "Prefer HDMI audio for the emulation kiosk session";
          wantedBy = [ "default.target" ];
          after = [
            "pipewire.service"
            "pipewire-pulse.service"
            "wireplumber.service"
          ];
          wants = [
            "pipewire.service"
            "pipewire-pulse.service"
            "wireplumber.service"
          ];
          serviceConfig = {
            Type = "oneshot";
            ExecStart = "${lib.getExe audioRoute}";
          };
        };

        hardware.graphics = {
          enable = true;
          enable32Bit = true;
        };

        networking.networkmanager.enable = lib.mkDefault true;
        programs.gamemode.enable = true;
        programs.ydotool = {
          enable = true;
          group = cfg.group;
        };
        services.libinput.enable = true;

        environment.sessionVariables = {
          ESDE_APPDATA_DIR = cfg.esde.appDataDir;
          EMULATION_DATA_ROOT = cfg.dataRoot;
          EMULATION_CONFIG_ROOT = cfg.configRoot;
          MESA_SHADER_CACHE_DIR = "${cfg.dataRoot}/cache/mesa-shaders";
          RADV_PERFTEST = "gpl";
        };

        environment.systemPackages = [
          packages.artBookNext
          packages.esdePackage
          packages.joypadAutoconfig
          packages.pico8Package
          packages.retroarchPackage
          packages.ryubingCanaryPackage
          packages.shaderCg
          packages.shaderGlsl
          packages.shaderSlang
          pkgs.bluez
          pkgs.bluez-tools
          pkgs.alsa-utils
          pkgs.foot
          pkgs.gamemode
          pkgs.gamescope
          pkgs.jq
          pkgs.mangohud
          pkgs.mesa-demos
          pkgs.networkmanager
          pkgs.pipewire
          pkgs.pulseaudio
          pkgs.vkbasalt
          pkgs.vulkan-tools
          pkgs.wireplumber
          pkgs.winetricks
          pkgs.ydotool
          packages.winePackage
        ]
        ++ builtins.attrValues config.ghostship.emulation.internal.scripts
        ++ emu.optionalPackages [
          "azahar"
          "cemu"
          "dolphin-emu"
          "joycond"
          "joycond-cemuhook"
          "lime3ds"
          "pcsx2"
          "ppsspp-sdl"
          "protontricks"
          "xemu"
        ]
        ++ lib.optional (packages.gzdoomPackage != null) packages.gzdoomPackage
        ++ lib.optional (packages.supermodelPackage != null) packages.supermodelPackage;

        systemd.tmpfiles.rules = [
          "d ${cfg.dataRoot} 0755 ${cfg.user} ${cfg.group} -"
          "d ${cfg.romRoot} 0755 ${cfg.user} ${cfg.group} -"
          "d ${cfg.biosRoot} 0755 ${cfg.user} ${cfg.group} -"
          "d ${cfg.dataRoot}/saves 0755 ${cfg.user} ${cfg.group} -"
          "d ${cfg.dataRoot}/states 0755 ${cfg.user} ${cfg.group} -"
          "d ${cfg.dataRoot}/screenshots 0755 ${cfg.user} ${cfg.group} -"
          "d ${cfg.dataRoot}/cache 0755 ${cfg.user} ${cfg.group} -"
          "d ${cfg.dataRoot}/cache/mesa-shaders 0755 ${cfg.user} ${cfg.group} -"
          "d ${cfg.dataRoot}/xdg 0755 ${cfg.user} ${cfg.group} -"
          "d ${cfg.dataRoot}/xdg/cache 0755 ${cfg.user} ${cfg.group} -"
          "d ${cfg.dataRoot}/xdg/config 0755 ${cfg.user} ${cfg.group} -"
          "d ${cfg.dataRoot}/xdg/share 0755 ${cfg.user} ${cfg.group} -"
          "d ${cfg.configRoot} 0755 ${cfg.user} ${cfg.group} -"
          "d ${cfg.configRoot}/controllers 0755 ${cfg.user} ${cfg.group} -"
          "d ${cfg.configRoot}/display 0755 ${cfg.user} ${cfg.group} -"
          "d ${cfg.configRoot}/emulators 0755 ${cfg.user} ${cfg.group} -"
          "d ${cfg.configRoot}/perf 0755 ${cfg.user} ${cfg.group} -"
          "d ${cfg.configRoot}/smoke 0755 ${cfg.user} ${cfg.group} -"
          "d ${cfg.configRoot}/retroarch 0755 ${cfg.user} ${cfg.group} -"
          "d ${cfg.configRoot}/retroarch/shaders 0755 ${cfg.user} ${cfg.group} -"
          "d ${cfg.configRoot}/retroarch/shaders-user 0755 ${cfg.user} ${cfg.group} -"
          "d ${cfg.configRoot}/es-de 0755 ${cfg.user} ${cfg.group} -"
          "d ${cfg.dataRoot}/logs 0755 ${cfg.user} ${cfg.group} -"
          "d ${cfg.dataRoot}/logs/esde-session 0755 ${cfg.user} ${cfg.group} -"
          "d ${cfg.dataRoot}/logs/perf 0755 ${cfg.user} ${cfg.group} -"
          "d ${cfg.dataRoot}/logs/smoke 0755 ${cfg.user} ${cfg.group} -"
          "d ${cfg.dataRoot}/smoke-roms 0755 ${cfg.user} ${cfg.group} -"
          "d ${cfg.dataRoot}/tmp 0755 ${cfg.user} ${cfg.group} -"
          "d /run/ghostship-emulation 0755 ${cfg.user} ${cfg.group} -"
          "d /run/ghostship-emulation/controllers 0755 ${cfg.user} ${cfg.group} -"
          "d /run/ghostship-secrets 0755 root root -"
          "L+ /home/${cfg.user}/Emulation - - - - ${cfg.dataRoot}"
        ];

        ghostship.emulation.internal.scripts.audioRoute = audioRoute;
      }

      (lib.mkIf (cfg.romDisk.uuid != null) {
        fileSystems.${cfg.romRoot} = {
          device = "/dev/disk/by-uuid/${cfg.romDisk.uuid}";
          fsType = cfg.romDisk.fsType;
          options = cfg.romDisk.mountOptions;
        };
      })
    ]
  );
}
