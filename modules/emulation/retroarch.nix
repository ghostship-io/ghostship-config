{ config, lib, pkgs, ... }:

let
  cfg = config.ghostship.emulation;
  packages = config.ghostship.emulation.internal.packages;

  retroarchCfg = pkgs.writeText "emulation-retroarch.cfg" ''
    video_driver = "vulkan"
    audio_driver = "pipewire"
    input_driver = "udev"
    menu_driver = "ozone"
    video_fullscreen = "true"
    video_vsync = "true"
    video_shader_enable = "true"
    video_shader = "${cfg.configRoot}/retroarch/shaders/shaders_slang/bezel/Mega_Bezel/Presets/Base_CRT_Presets_DREZ/MBZ__3__STD__GDV__DREZ-VIEWPORT.slangp"
    video_shader_dir = "${cfg.configRoot}/retroarch/shaders"
    libretro_directory = "${packages.retroarchPackage}/lib/retroarch/cores"
    libretro_info_path = "${packages.retroarchPackage}/share/libretro/info"
    system_directory = "${cfg.biosRoot}"
    savefile_directory = "${cfg.dataRoot}/saves"
    savestate_directory = "${cfg.dataRoot}/states"
    screenshot_directory = "${cfg.dataRoot}/screenshots"
    input_autodetect_enable = "true"
    joypad_autoconfig_dir = "${cfg.configRoot}/retroarch/autoconfig"
    input_menu_toggle_gamepad_combo = "3"
    input_enable_hotkey_btn = "8"
    input_menu_toggle_btn = "3"
    input_exit_emulator_btn = "9"
    input_save_state_btn = "5"
    input_load_state_btn = "4"
    config_save_on_exit = "false"
    log_verbosity = "true"
    log_to_file = "true"
    log_dir = "${cfg.dataRoot}/logs/retroarch"
    video_smooth = "false"
    video_scale_integer = "false"
    video_aspect_ratio_auto = "true"
    run_ahead_enabled = "false"
    threaded_video = "false"
    auto_remaps_enable = "true"
    remap_directory = "${cfg.configRoot}/retroarch/remaps"
    core_options_path = "${cfg.configRoot}/retroarch/core-options/default.opt"
  '';

  coreOptions = {
    "retroarch-fbneo.opt" = ''
      fbneo-allow-patched-romsets = "enabled"
    '';
    "retroarch-beetle-psx-hw.opt" = ''
      beetle_psx_hw_renderer = "hardware_vk"
      beetle_psx_hw_pgxp_mode = "memory + CPU"
      beetle_psx_hw_internal_resolution = "4x"
    '';
    "retroarch-beetle-saturn.opt" = ''
      beetle_saturn_virtuagun_crosshair = "Cross"
    '';
    "retroarch-mupen64plus.opt" = ''
      mupen64plus-rdp-plugin = "parallel"
      mupen64plus-cpucore = "dynamic_recompiler"
    '';
    "retroarch-parallel-n64.opt" = ''
      parallel-n64-gfxplugin = "parallel"
    '';
    "retroarch-melonds.opt" = ''
      melonds_boot_directly = "enabled"
    '';
    "retroarch-ppsspp.opt" = ''
      ppsspp_internal_resolution = "4"
    '';
    "retroarch-pcsx2.opt" = ''
      pcsx2_renderer = "Vulkan"
      pcsx2_upscale_multiplier = "3"
    '';
    "retroarch-flycast.opt" = ''
      flycast_renderer = "vulkan"
    '';
  };

  profiles = {
    "megabezel-auto.cfg" = ''
      video_shader_enable = "true"
      video_shader = "${cfg.configRoot}/retroarch/shaders/shaders_slang/bezel/Mega_Bezel/Presets/Base_CRT_Presets_DREZ/MBZ__3__STD__GDV__DREZ-VIEWPORT.slangp"
    '';
    "megabezel-standard.cfg" = ''
      video_shader_enable = "true"
      video_shader = "${cfg.configRoot}/retroarch/shaders/shaders_slang/bezel/Mega_Bezel/Presets/Base_CRT_Presets_DREZ/MBZ__3__STD__GDV__DREZ-VIEWPORT.slangp"
    '';
    "megabezel-potato.cfg" = ''
      video_shader_enable = "true"
      video_shader = "${cfg.configRoot}/retroarch/shaders/shaders_slang/bezel/Mega_Bezel/Presets/Base_CRT_Presets_DREZ/MBZ__5__POTATO__GDV__DREZ-VIEWPORT.slangp"
    '';
    "megabezel-passthrough.cfg" = ''
      video_shader_enable = "true"
      video_shader = "${cfg.configRoot}/retroarch/shaders/shaders_slang/bezel/Mega_Bezel/Presets/Base_CRT_Presets_DREZ/MBZ__3__STD__PASSTHROUGH__DREZ-VIEWPORT.slangp"
    '';
    "sharp-clean.cfg" = ''
      video_shader_enable = "true"
      video_shader = "${cfg.configRoot}/retroarch/shaders/shaders_slang/interpolation/sharp-bilinear.slangp"
    '';
    "integer-raw.cfg" = ''
      video_shader_enable = "false"
      video_scale_integer = "true"
      video_smooth = "false"
    '';
    "performance.cfg" = ''
      video_shader_enable = "false"
      video_smooth = "false"
      threaded_video = "true"
    '';
  };

  autoconfig8BitDo = pkgs.writeText "8BitDo Ultimate 2C Wireless Controller.cfg" ''
    input_device = "8BitDo Ultimate 2C Wireless Controller"
    input_driver = "udev"
    input_vendor_id = "11720"
    input_product_id = "12555"
    input_b_btn = "1"
    input_y_btn = "3"
    input_select_btn = "8"
    input_start_btn = "9"
    input_a_btn = "0"
    input_x_btn = "2"
    input_l_btn = "4"
    input_r_btn = "5"
    input_l2_axis = "+2"
    input_r2_axis = "+5"
    input_l3_btn = "10"
    input_r3_btn = "11"
    input_l_x_plus_axis = "+0"
    input_l_x_minus_axis = "-0"
    input_l_y_plus_axis = "+1"
    input_l_y_minus_axis = "-1"
    input_r_x_plus_axis = "+3"
    input_r_x_minus_axis = "-3"
    input_r_y_plus_axis = "+4"
    input_r_y_minus_axis = "-4"
    input_menu_toggle_btn = "3"
  '';

  autoconfigSwitchPro = pkgs.writeText "Nintendo Switch Pro Controller.cfg" ''
    input_device = "Nintendo Switch Pro Controller"
    input_driver = "udev"
    input_vendor_id = "1406"
    input_product_id = "8201"
    input_b_btn = "1"
    input_y_btn = "3"
    input_select_btn = "8"
    input_start_btn = "9"
    input_a_btn = "0"
    input_x_btn = "2"
    input_l_btn = "4"
    input_r_btn = "5"
    input_l2_btn = "6"
    input_r2_btn = "7"
    input_l3_btn = "10"
    input_r3_btn = "11"
    input_l_x_plus_axis = "+0"
    input_l_x_minus_axis = "-0"
    input_l_y_plus_axis = "+1"
    input_l_y_minus_axis = "-1"
    input_r_x_plus_axis = "+2"
    input_r_x_minus_axis = "-2"
    input_r_y_plus_axis = "+3"
    input_r_y_minus_axis = "-3"
    input_menu_toggle_btn = "3"
  '';

  shaderPolicy = pkgs.writeText "emulation-shader-policy.json" (builtins.toJSON {
    default = "megabezel-auto";
    fallback = "sharp-clean";
    profiles = builtins.attrNames profiles;
    megabezel = {
      requiredPath = "shaders_slang/bezel/Mega_Bezel";
      highQuality = "megabezel-standard";
      lowCost = "megabezel-potato";
      passthrough = "megabezel-passthrough";
    };
  });

  profileFiles = lib.mapAttrsToList
    (name: text: {
      inherit name;
      file = pkgs.writeText "emulation-${name}" text;
    })
    profiles;

  coreOptionFiles = lib.mapAttrsToList
    (name: text: {
      inherit name;
      file = pkgs.writeText "emulation-${name}" text;
    })
    coreOptions;

  syncRetroarchConfig = pkgs.writeShellScriptBin "sync-retroarch-config" ''
    set -euo pipefail
    export PATH=${config.ghostship.emulation.internal.lib.scriptPath}:$PATH

    install -d -m 0755 -o ${cfg.user} -g ${cfg.group} \
      "${cfg.configRoot}/retroarch" \
      "${cfg.configRoot}/retroarch/autoconfig" \
      "${cfg.configRoot}/retroarch/core-options" \
      "${cfg.configRoot}/retroarch/profiles" \
      "${cfg.configRoot}/retroarch/remaps" \
      "${cfg.configRoot}/retroarch/shaders" \
      "${cfg.configRoot}/retroarch/shaders-user" \
      "${cfg.configRoot}/retroarch/system-overrides" \
      "${cfg.dataRoot}/logs/retroarch"

    install -D -m 0644 -o ${cfg.user} -g ${cfg.group} ${retroarchCfg} "${cfg.configRoot}/retroarch/retroarch.cfg"
    install -D -m 0644 -o ${cfg.user} -g ${cfg.group} ${shaderPolicy} "${cfg.configRoot}/retroarch/shader-policy.json"
    if [ -d "${packages.joypadAutoconfig}/share/libretro/autoconfig" ]; then
      cp -R --no-preserve=mode,ownership "${packages.joypadAutoconfig}/share/libretro/autoconfig/." "${cfg.configRoot}/retroarch/autoconfig/" || true
    fi
    install -D -m 0644 -o ${cfg.user} -g ${cfg.group} ${autoconfig8BitDo} "${cfg.configRoot}/retroarch/autoconfig/8BitDo Ultimate 2C Wireless Controller.cfg"
    install -D -m 0644 -o ${cfg.user} -g ${cfg.group} ${autoconfigSwitchPro} "${cfg.configRoot}/retroarch/autoconfig/Nintendo Switch Pro Controller.cfg"

    install -m 0644 -o ${cfg.user} -g ${cfg.group} /dev/null "${cfg.configRoot}/retroarch/core-options/default.opt"
    ${lib.concatMapStringsSep "\n" (entry: ''
      install -D -m 0644 -o ${cfg.user} -g ${cfg.group} ${entry.file} "${cfg.configRoot}/retroarch/core-options/${entry.name}"
    '') coreOptionFiles}
    ${lib.concatMapStringsSep "\n" (entry: ''
      install -D -m 0644 -o ${cfg.user} -g ${cfg.group} ${entry.file} "${cfg.configRoot}/retroarch/profiles/${entry.name}"
    '') profileFiles}

    printf '%s' '${config.ghostship.emulation.internal.lib.allSystemsJson}' | jq -c '.[]' | while read -r system; do
      id="$(jq -r '.id' <<<"$system")"
      emulator="$(jq -r '.emulator' <<<"$system")"
      override="${cfg.configRoot}/retroarch/system-overrides/$id.cfg"
      if printf '%s' "$emulator" | grep -q '^retroarch-'; then
        option_file="${cfg.configRoot}/retroarch/core-options/$emulator.opt"
        [ -e "$option_file" ] || option_file="${cfg.configRoot}/retroarch/core-options/default.opt"
        {
          printf 'core_options_path = "%s"\n' "$option_file"
          printf 'video_smooth = "false"\n'
          printf 'video_aspect_ratio_auto = "true"\n'
        } >"$override"
        chown ${cfg.user}:${cfg.group} "$override"
        chmod 0644 "$override"
      fi
    done

    if [ ! -e "${cfg.configRoot}/retroarch/profiles/current.cfg" ]; then
      ln -s "megabezel-auto.cfg" "${cfg.configRoot}/retroarch/profiles/current.cfg"
    fi
    chown -h ${cfg.user}:${cfg.group} "${cfg.configRoot}/retroarch/profiles/current.cfg" || true

    ln -sfn ${packages.shaderSlang}/share/libretro/shaders_slang "${cfg.configRoot}/retroarch/shaders/shaders_slang"
    ln -sfn ${packages.shaderGlsl}/share/libretro/shaders_glsl "${cfg.configRoot}/retroarch/shaders/shaders_glsl"
    ln -sfn ${packages.shaderCg}/share/libretro/shaders_cg "${cfg.configRoot}/retroarch/shaders/shaders_cg"
  '';

  retroarchShaderSmokeTest = pkgs.writeShellScriptBin "retroarch-shader-smoke-test" ''
    set -euo pipefail
    export PATH=${config.ghostship.emulation.internal.lib.scriptPath}:$PATH
    shader_root="${cfg.configRoot}/retroarch/shaders"
    status="${cfg.configRoot}/retroarch/shader-status.json"
    missing=0
    slang=false
    megabezel=false
    glsl=false
    cg=false

    if [ -e "$shader_root/shaders_slang" ]; then slang=true; else missing=1; fi
    if [ -e "$shader_root/shaders_slang/bezel/Mega_Bezel" ]; then megabezel=true; else missing=1; fi
    if [ -e "$shader_root/shaders_glsl" ]; then glsl=true; else missing=1; fi
    if [ -e "$shader_root/shaders_cg" ]; then cg=true; else missing=1; fi

    install -d -m 0755 -o ${cfg.user} -g ${cfg.group} "$(dirname "$status")"
    jq -n \
      --argjson slang "$slang" \
      --argjson megabezel "$megabezel" \
      --argjson glsl "$glsl" \
      --argjson cg "$cg" \
      --arg checked_at "$(date -u +%FT%TZ)" \
      '{checked_at:$checked_at, slang:$slang, megabezel:$megabezel, glsl:$glsl, cg:$cg}' >"$status.tmp"
    chown ${cfg.user}:${cfg.group} "$status.tmp"
    chmod 0644 "$status.tmp"
    mv "$status.tmp" "$status"

    jq . "$status"
    ${packages.retroarchPackage}/bin/retroarch --version | head -n 1
    exit "$missing"
  '';
in
{
  config = lib.mkIf cfg.enable {
    ghostship.emulation.internal.scripts = {
      inherit retroarchShaderSmokeTest syncRetroarchConfig;
    };
    ghostship.emulation.internal.setupScripts = [ syncRetroarchConfig ];
  };
}
