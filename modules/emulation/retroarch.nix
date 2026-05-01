{ config, lib, pkgs, ... }:

let
  cfg = config.ghostship.emulation;
  packages = config.ghostship.emulation.internal.packages;

  retroarchCfg = pkgs.writeText "emulation-retroarch.cfg" ''
    video_driver = "vulkan"
    audio_driver = "pipewire"
    input_driver = "udev"
    vulkan_gpu_index = "1"
    menu_driver = "ozone"
    menu_swap_ok_cancel = "false"
    video_fullscreen = "true"
    video_vsync = "true"
    video_shader_enable = "true"
    video_shader_dir = "${cfg.configRoot}/retroarch/shaders"
    libretro_directory = "${packages.retroarchPackage}/lib/retroarch/cores"
    libretro_info_path = "${cfg.configRoot}/retroarch/info"
    system_directory = "${cfg.biosRoot}"
    savefile_directory = "${cfg.dataRoot}/saves"
    savestate_directory = "${cfg.dataRoot}/states"
    screenshot_directory = "${cfg.dataRoot}/screenshots"
    input_autodetect_enable = "true"
    joypad_autoconfig_dir = "${cfg.configRoot}/retroarch/autoconfig"
    input_menu_toggle_gamepad_combo = "0"
    input_enable_hotkey_btn = "9"
    input_menu_toggle_btn = "2"
    input_exit_emulator_btn = "10"
    input_save_state_btn = "6"
    input_load_state_btn = "5"
    input_reset_btn = "0"
    input_fps_toggle_btn = "3"
    input_screenshot_btn = "1"
    input_hold_fast_forward_btn = "8"
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

  globalShaderPreset = pkgs.writeText "emulation-global.slangp" ''
    #reference "${cfg.configRoot}/retroarch/shaders/shaders_slang/edge-smoothing/nnedi3/nnedi3-nns16-2x-rgb.slangp"
  '';

  coreOptions = {
    "retroarch-fbneo.opt" = ''
      fbneo-allow-patched-romsets = "enabled"
    '';
    "retroarch-fceumm.opt" = ''
      fceumm_region = "Auto"
      fceumm_ramstate = "enabled"
    '';
    "retroarch-beetle-supergrafx.opt" = ''
      sgx_cdimagecache = "enabled"
      sgx_cdbios = "System Card 3"
      sgx_default_joypad_type_p1 = "6 Buttons"
      sgx_default_joypad_type_p2 = "6 Buttons"
      sgx_default_joypad_type_p3 = "6 Buttons"
      sgx_default_joypad_type_p4 = "6 Buttons"
      sgx_default_joypad_type_p5 = "6 Buttons"
      sgx_multitap = "enabled"
    '';
    "retroarch-beetle-pce-fast.opt" = ''
      pce_fast_cdimagecache = "enabled"
      pce_fast_cdbios = "System Card 3"
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
      reicast_threaded_rendering = "disabled"
    '';
  };

  profiles = {
    "nnedi3-clean.cfg" = ''
      video_shader_enable = "true"
      video_shader = "${cfg.configRoot}/retroarch/shaders/shaders_slang/edge-smoothing/nnedi3/nnedi3-nns16-2x-rgb.slangp"
      video_smooth = "false"
      video_scale_integer = "false"
    '';
    "nnedi3-quality.cfg" = ''
      video_shader_enable = "true"
      video_shader = "${cfg.configRoot}/retroarch/shaders/shaders_slang/edge-smoothing/nnedi3/nnedi3-nns32-4x-rgb.slangp"
      video_smooth = "false"
      video_scale_integer = "false"
    '';
    "nnedi3-balanced.cfg" = ''
      video_shader_enable = "true"
      video_shader = "${cfg.configRoot}/retroarch/shaders/shaders_slang/edge-smoothing/nnedi3/nnedi3-nns32-2x-rgb-nns32-4x-luma.slangp"
      video_smooth = "false"
      video_scale_integer = "false"
    '';
    "nnedi3-fast.cfg" = ''
      video_shader_enable = "true"
      video_shader = "${cfg.configRoot}/retroarch/shaders/shaders_slang/edge-smoothing/nnedi3/nnedi3-nns16-2x-rgb.slangp"
      video_smooth = "false"
      video_scale_integer = "false"
    '';
    "sharp-bilinear-prescale.cfg" = ''
      video_shader_enable = "true"
      video_shader = "${cfg.configRoot}/retroarch/shaders/shaders_slang/pixel-art-scaling/sharp-bilinear-2x-prescale.slangp"
      video_smooth = "false"
      video_scale_integer = "false"
    '';
    "sharp-bilinear-simple.cfg" = ''
      video_shader_enable = "true"
      video_shader = "${cfg.configRoot}/retroarch/shaders/shaders_slang/pixel-art-scaling/sharp-bilinear-simple.slangp"
      video_smooth = "false"
      video_scale_integer = "false"
    '';
    "pixel-aa-fast.cfg" = ''
      video_shader_enable = "true"
      video_shader = "${cfg.configRoot}/retroarch/shaders/shaders_slang/pixel-art-scaling/pixel_aa_fast.slangp"
      video_smooth = "false"
      video_scale_integer = "false"
    '';
    "scalefx-aa-fast.cfg" = ''
      video_shader_enable = "true"
      video_shader = "${cfg.configRoot}/retroarch/shaders/shaders_slang/presets/scalefx-plus-smoothing/scalefx-aa-fast.slangp"
      video_smooth = "false"
      video_scale_integer = "false"
    '';
    "xbrz-freescale.cfg" = ''
      video_shader_enable = "true"
      video_shader = "${cfg.configRoot}/retroarch/shaders/shaders_slang/edge-smoothing/xbrz/xbrz-freescale-multipass.slangp"
      video_smooth = "false"
      video_scale_integer = "false"
    '';
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
      video_shader = "${cfg.configRoot}/retroarch/shaders/shaders_slang/pixel-art-scaling/sharp-bilinear-2x-prescale.slangp"
    '';
    "no-shader.cfg" = ''
      video_shader_enable = "false"
      video_smooth = "false"
      video_scale_integer = "false"
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
  '';

  autoconfigSwitchPro = pkgs.writeText "Nintendo Switch Pro Controller.cfg" ''
    input_device = "Nintendo Switch Pro Controller"
    input_device_alt1 = "Nintendo Co., Ltd. Pro Controller"
    input_device_alt2 = "Pro Controller"
    input_driver = "udev"
    input_vendor_id = "1406"
    input_product_id = "8201"
    input_b_btn = "1"
    input_y_btn = "3"
    input_select_btn = "9"
    input_start_btn = "10"
    input_up_btn = "h0up"
    input_down_btn = "h0down"
    input_left_btn = "h0left"
    input_right_btn = "h0right"
    input_a_btn = "0"
    input_x_btn = "2"
    input_l_btn = "5"
    input_r_btn = "6"
    input_l2_btn = "7"
    input_r2_btn = "8"
    input_l3_btn = "12"
    input_r3_btn = "13"
    input_l_x_plus_axis = "+0"
    input_l_x_minus_axis = "-0"
    input_l_y_plus_axis = "+1"
    input_l_y_minus_axis = "-1"
    input_r_x_plus_axis = "+2"
    input_r_x_minus_axis = "-2"
    input_r_y_plus_axis = "+3"
    input_r_y_minus_axis = "-3"
    input_b_btn_label = "B"
    input_y_btn_label = "Y"
    input_select_btn_label = "Minus"
    input_start_btn_label = "Plus"
    input_up_btn_label = "D-Pad Up"
    input_down_btn_label = "D-Pad Down"
    input_left_btn_label = "D-Pad Left"
    input_right_btn_label = "D-Pad Right"
    input_a_btn_label = "A"
    input_x_btn_label = "X"
    input_l_btn_label = "L"
    input_r_btn_label = "R"
    input_l2_btn_label = "ZL"
    input_r2_btn_label = "ZR"
    input_l3_btn_label = "Left Stick Press"
    input_r3_btn_label = "Right Stick Press"
  '';

  systemShaderDefaults = {
    fbneo = "nnedi3-clean.cfg";
    pcengine = "nnedi3-clean.cfg";
    pcenginecd = "nnedi3-clean.cfg";
    gb = "nnedi3-clean.cfg";
    gbc = "nnedi3-clean.cfg";
    gba = "nnedi3-clean.cfg";
    n64 = "no-shader";
    nds = "nnedi3-clean.cfg";
    nes = "nnedi3-clean.cfg";
    snes = "nnedi3-clean.cfg";
    virtualboy = "sharp-bilinear-prescale";
    neogeocd = "nnedi3-clean.cfg";
    ngpc = "nnedi3-clean.cfg";
    dreamcast = "no-shader";
    gamegear = "nnedi3-clean.cfg";
    genesis = "nnedi3-clean.cfg";
    mastersystem = "nnedi3-clean.cfg";
    saturn = "sharp-bilinear-simple";
    segacd = "nnedi3-clean.cfg";
    psx = "sharp-bilinear-simple";
  };

  shaderPolicy = pkgs.writeText "emulation-shader-policy.json" (builtins.toJSON {
    default = "nnedi3-clean";
    fallback = "sharp-bilinear-prescale";
    profiles = builtins.attrNames profiles;
    systemDefaults = systemShaderDefaults;
    cleanScaling = {
      quality = "nnedi3-quality";
      balanced = "nnedi3-balanced";
      fast = "nnedi3-fast";
      sharp = "sharp-bilinear-prescale";
      raw = "integer-raw";
    };
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
      "${cfg.configRoot}/retroarch/info" \
      "${cfg.configRoot}/retroarch/profiles" \
      "${cfg.configRoot}/retroarch/remaps" \
      "${cfg.configRoot}/retroarch/shaders" \
      "${cfg.configRoot}/retroarch/shaders-user" \
      "${cfg.configRoot}/retroarch/system-overrides" \
      "${cfg.dataRoot}/xdg/config/retroarch/config" \
      "${cfg.dataRoot}/logs/retroarch"

    install -D -m 0644 -o ${cfg.user} -g ${cfg.group} ${retroarchCfg} "${cfg.configRoot}/retroarch/retroarch.cfg"
    install -D -m 0644 -o ${cfg.user} -g ${cfg.group} ${globalShaderPreset} "${cfg.dataRoot}/xdg/config/retroarch/config/global.slangp"
    install -D -m 0644 -o ${cfg.user} -g ${cfg.group} ${shaderPolicy} "${cfg.configRoot}/retroarch/shader-policy.json"
    if [ -d "${packages.libretroCoreInfo}/share/retroarch/cores" ]; then
      cp -R --no-preserve=mode,ownership "${packages.libretroCoreInfo}/share/retroarch/cores/." "${cfg.configRoot}/retroarch/info/" || true
    fi
    chown -R ${cfg.user}:${cfg.group} "${cfg.configRoot}/retroarch/info" "${cfg.dataRoot}/logs/retroarch"
    touch "${cfg.dataRoot}/logs/retroarch/retroarch.log"
    chown ${cfg.user}:${cfg.group} "${cfg.dataRoot}/logs/retroarch/retroarch.log"
    chmod 0644 "${cfg.dataRoot}/logs/retroarch/retroarch.log"
    if [ -d "${packages.joypadAutoconfig}/share/libretro/autoconfig" ]; then
      cp -R --no-preserve=mode,ownership "${packages.joypadAutoconfig}/share/libretro/autoconfig/." "${cfg.configRoot}/retroarch/autoconfig/" || true
    fi
    install -D -m 0644 -o ${cfg.user} -g ${cfg.group} ${autoconfig8BitDo} "${cfg.configRoot}/retroarch/autoconfig/8BitDo Ultimate 2C Wireless Controller.cfg"
    install -D -m 0644 -o ${cfg.user} -g ${cfg.group} ${autoconfigSwitchPro} "${cfg.configRoot}/retroarch/autoconfig/Nintendo Switch Pro Controller.cfg"
    install -D -m 0644 -o ${cfg.user} -g ${cfg.group} ${autoconfigSwitchPro} "${cfg.configRoot}/retroarch/autoconfig/udev/Nintendo Switch Pro Controller.cfg"

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
      if [ -e "$override" ]; then
        rm "$override"
      fi
    done

    if [ ! -e "${cfg.configRoot}/retroarch/profiles/current.cfg" ]; then
      ln -s "nnedi3-clean.cfg" "${cfg.configRoot}/retroarch/profiles/current.cfg"
    else
      current_target="$(readlink "${cfg.configRoot}/retroarch/profiles/current.cfg" 2>/dev/null || true)"
      case "$current_target" in
        ""|megabezel-auto.cfg)
          ln -sfn "nnedi3-clean.cfg" "${cfg.configRoot}/retroarch/profiles/current.cfg"
          ;;
      esac
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
    nnedi3=false
    sharp=false
    megabezel=false
    glsl=false
    cg=false

    if [ -e "$shader_root/shaders_slang" ]; then slang=true; else missing=1; fi
    if [ -e "$shader_root/shaders_slang/edge-smoothing/nnedi3/nnedi3-nns32-4x-rgb.slangp" ]; then nnedi3=true; else missing=1; fi
    if [ -e "$shader_root/shaders_slang/pixel-art-scaling/sharp-bilinear-2x-prescale.slangp" ]; then sharp=true; else missing=1; fi
    if [ -e "$shader_root/shaders_slang/bezel/Mega_Bezel" ]; then megabezel=true; else missing=1; fi
    if [ -e "$shader_root/shaders_glsl" ]; then glsl=true; else missing=1; fi
    if [ -e "$shader_root/shaders_cg" ]; then cg=true; else missing=1; fi

    install -d -m 0755 -o ${cfg.user} -g ${cfg.group} "$(dirname "$status")"
    jq -n \
      --argjson slang "$slang" \
      --argjson nnedi3 "$nnedi3" \
      --argjson sharp "$sharp" \
      --argjson megabezel "$megabezel" \
      --argjson glsl "$glsl" \
      --argjson cg "$cg" \
      --arg checked_at "$(date -u +%FT%TZ)" \
      '{checked_at:$checked_at, slang:$slang, nnedi3:$nnedi3, sharp:$sharp, megabezel:$megabezel, glsl:$glsl, cg:$cg}' >"$status.tmp"
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
