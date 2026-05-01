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
    input_player1_analog_dpad_mode = "1"
    input_player2_analog_dpad_mode = "1"
    input_player3_analog_dpad_mode = "1"
    input_player4_analog_dpad_mode = "1"
    input_player5_analog_dpad_mode = "1"
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
    cheevos_enable = "true"
    cheevos_hardcore_mode_enable = "false"
    cheevos_verbose_enable = "true"
    cheevos_start_active = "true"
    cheevos_auto_screenshot = "true"
    cheevos_badges_enable = "true"
    cheevos_challenge_indicators = "true"
    cheevos_richpresence_enable = "true"
    cheevos_visibility_account = "true"
    cheevos_visibility_unlock = "true"
    cheevos_visibility_mastery = "true"
    cheevos_visibility_lboard_start = "true"
    cheevos_visibility_lboard_submit = "true"
    cheevos_visibility_lboard_trackers = "false"
    cheevos_unlock_sound_enable = "true"
    cheevos_test_unofficial = "false"
  '';

  globalShaderPreset = pkgs.writeText "emulation-global.slangp" ''
    #reference "${cfg.configRoot}/retroarch/shaders/shaders_slang/edge-smoothing/nnedi3/nnedi3-nns16-2x-rgb.slangp"
  '';

  coreOptions = {
    "FinalBurn Neo" = ''
      fbneo-allow-patched-romsets = "enabled"
    '';
    "FCEUmm" = ''
      fceumm_region = "Auto"
      fceumm_ramstate = "enabled"
    '';
    "Beetle SuperGrafx" = ''
      sgx_cdimagecache = "enabled"
      sgx_cdbios = "System Card 3"
      sgx_default_joypad_type_p1 = "6 Buttons"
      sgx_default_joypad_type_p2 = "6 Buttons"
      sgx_default_joypad_type_p3 = "6 Buttons"
      sgx_default_joypad_type_p4 = "6 Buttons"
      sgx_default_joypad_type_p5 = "6 Buttons"
      sgx_multitap = "enabled"
    '';
    "Beetle PCE Fast" = ''
      pce_fast_cdimagecache = "enabled"
      pce_fast_cdbios = "System Card 3"
      pce_fast_default_joypad_type_p1 = "6 Buttons"
      pce_fast_default_joypad_type_p2 = "6 Buttons"
      pce_fast_default_joypad_type_p3 = "6 Buttons"
      pce_fast_default_joypad_type_p4 = "6 Buttons"
      pce_fast_default_joypad_type_p5 = "6 Buttons"
    '';
    "Beetle PSX HW" = ''
      beetle_psx_hw_renderer = "hardware_vk"
      beetle_psx_hw_pgxp_mode = "memory + CPU"
      beetle_psx_hw_internal_resolution = "4x"
    '';
    "Beetle Saturn" = ''
      beetle_saturn_virtuagun_crosshair = "Cross"
    '';
    "Mupen64Plus-Next" = ''
      mupen64plus-rdp-plugin = "gliden64"
      mupen64plus-cpucore = "dynamic_recompiler"
      mupen64plus-rsp-plugin = "hle"
      mupen64plus-EnableNativeResFactor = "3"
      mupen64plus-aspect = "4:3"
      mupen64plus-43screensize = "960x720"
      mupen64plus-EnableFBEmulation = "True"
      mupen64plus-EnableCopyColorToRDRAM = "Async"
      mupen64plus-EnableCopyDepthToRDRAM = "Software"
      mupen64plus-BilinearMode = "3point"
      mupen64plus-MultiSampling = "0"
      mupen64plus-FXAA = "0"
      mupen64plus-EnableShadersStorage = "True"
      mupen64plus-CountPerOp = "0"
      mupen64plus-ForceDisableExtraMem = "False"
      mupen64plus-pak1 = "rumble"
      mupen64plus-pak2 = "rumble"
      mupen64plus-pak3 = "rumble"
      mupen64plus-pak4 = "rumble"
    '';
    "melonDS" = ''
      melonds_boot_directly = "enabled"
    '';
    "PPSSPP" = ''
      ppsspp_internal_resolution = "4"
    '';
    "LRPS2" = ''
      pcsx2_renderer = "Vulkan"
      pcsx2_upscale_multiplier = "3"
    '';
    "Flycast" = ''
      flycast_renderer = "vulkan"
      reicast_threaded_rendering = "disabled"
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
    input_up_btn = "h0up"
    input_down_btn = "h0down"
    input_left_btn = "h0left"
    input_right_btn = "h0right"
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

  coreOptionFiles = lib.mapAttrsToList
    (corename: text: {
      inherit corename;
      file = pkgs.writeText "emulation-${corename}.opt" text;
    })
    coreOptions;

  syncRetroarchConfig = pkgs.writeShellScriptBin "sync-retroarch-config" ''
    set -euo pipefail
    export PATH=${config.ghostship.emulation.internal.lib.scriptPath}:$PATH

    install -d -m 0755 -o ${cfg.user} -g ${cfg.group} \
      "${cfg.configRoot}/retroarch" \
      "${cfg.configRoot}/retroarch/autoconfig" \
      "${cfg.configRoot}/retroarch/info" \
      "${cfg.configRoot}/retroarch/remaps" \
      "${cfg.configRoot}/retroarch/shaders" \
      "${cfg.configRoot}/retroarch/shaders-user" \
      "${cfg.dataRoot}/xdg/config/retroarch/config" \
      "${cfg.dataRoot}/logs/retroarch"

    install -D -m 0644 -o ${cfg.user} -g ${cfg.group} ${retroarchCfg} "${cfg.configRoot}/retroarch/retroarch.cfg"
    install -D -m 0644 -o ${cfg.user} -g ${cfg.group} ${globalShaderPreset} "${cfg.dataRoot}/xdg/config/retroarch/config/global.slangp"
    rm -f "${cfg.configRoot}/retroarch/shader-policy.json"
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

    rm -rf "${cfg.configRoot}/retroarch/core-options"
    rm -rf "${cfg.configRoot}/retroarch/profiles" "${cfg.configRoot}/retroarch/system-overrides"
    rm -f "${cfg.dataRoot}/xdg/config/retroarch/config/ParaLLEl N64/ParaLLEl N64.opt"
    ${lib.concatMapStringsSep "\n" (entry: ''
      install -d -m 0755 -o ${cfg.user} -g ${cfg.group} "${cfg.dataRoot}/xdg/config/retroarch/config/${entry.corename}"
      install -D -m 0644 -o ${cfg.user} -g ${cfg.group} ${entry.file} "${cfg.dataRoot}/xdg/config/retroarch/config/${entry.corename}/${entry.corename}.opt"
    '') coreOptionFiles}

    ln -sfn ${packages.shaderSlang}/share/libretro/shaders_slang "${cfg.configRoot}/retroarch/shaders/shaders_slang"
    ln -sfn ${packages.shaderGlsl}/share/libretro/shaders_glsl "${cfg.configRoot}/retroarch/shaders/shaders_glsl"
    ln -sfn ${packages.shaderCg}/share/libretro/shaders_cg "${cfg.configRoot}/retroarch/shaders/shaders_cg"
  '';

  retroarchShaderSmokeTest = pkgs.writeShellScriptBin "retroarch-shader-smoke-test" ''
    set -euo pipefail
    export PATH=${config.ghostship.emulation.internal.lib.scriptPath}:$PATH
    shader_root="${cfg.configRoot}/retroarch/shaders"
    status="${cfg.dataRoot}/logs/retroarch/shader-status.json"
    missing=0
    slang=false
    nnedi3=false
    glsl=false
    cg=false

    if [ -e "$shader_root/shaders_slang" ]; then slang=true; else missing=1; fi
    if [ -e "$shader_root/shaders_slang/edge-smoothing/nnedi3/nnedi3-nns32-4x-rgb.slangp" ]; then nnedi3=true; else missing=1; fi
    if [ -e "$shader_root/shaders_glsl" ]; then glsl=true; else missing=1; fi
    if [ -e "$shader_root/shaders_cg" ]; then cg=true; else missing=1; fi

    install -d -m 0755 -o ${cfg.user} -g ${cfg.group} "$(dirname "$status")"
    jq -n \
      --argjson slang "$slang" \
      --argjson nnedi3 "$nnedi3" \
      --argjson glsl "$glsl" \
      --argjson cg "$cg" \
      --arg checked_at "$(date -u +%FT%TZ)" \
      '{checked_at:$checked_at, slang:$slang, nnedi3:$nnedi3, glsl:$glsl, cg:$cg}' >"$status.tmp"
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
