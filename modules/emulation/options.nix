{ config, lib, ... }:

let
  cfg = config.ghostship.emulation;
  inherit (lib) mkEnableOption mkIf mkOption types;
in
{
  options.ghostship.emulation = {
    enable = mkEnableOption "dedicated ES-DE emulation PC profile";
    user = mkOption {
      type = types.str;
      default = "kiosk";
      description = "User that runs the emulation kiosk session.";
    };
    group = mkOption {
      type = types.str;
      default = "kiosk";
      description = "Primary group for emulation runtime state.";
    };
    dataRoot = mkOption {
      type = types.path;
      default = "/srv/emulation";
      description = "Writable root for emulation state.";
    };
    romRoot = mkOption {
      type = types.path;
      default = "/srv/emulation/roms";
      description = "Local ROM root. The future 4TB SSD should mount here.";
    };
    biosRoot = mkOption {
      type = types.path;
      default = "/srv/emulation/bios";
      description = "BIOS, firmware, keys, and other user-provided emulator files.";
    };
    configRoot = mkOption {
      type = types.path;
      default = "/srv/emulation/config";
      description = "Writable configuration root for emulator overrides.";
    };
    frontend = mkOption {
      type = types.enum [ "es-de" ];
      default = "es-de";
      description = "Frontend to launch from the kiosk session.";
    };
    theme = mkOption {
      type = types.enum [ "art-book-next" ];
      default = "art-book-next";
      description = "Default ES-DE theme.";
    };
    esde.appDataDir = mkOption {
      type = types.path;
      default = "/srv/emulation/es-de";
      description = "ES-DE application data directory.";
    };
    visuals.defaultProfile = mkOption {
      type = types.enum [
        "nnedi3-clean"
        "nnedi3-quality"
        "nnedi3-balanced"
        "nnedi3-fast"
        "sharp-bilinear-prescale"
        "sharp-bilinear-simple"
        "pixel-aa-fast"
        "scalefx-aa-fast"
        "xbrz-freescale"
        "megabezel-auto"
        "megabezel-standard"
        "megabezel-potato"
        "megabezel-passthrough"
        "sharp-clean"
        "no-shader"
        "integer-raw"
        "performance"
      ];
      default = "nnedi3-clean";
      description = "Default RetroArch shader/profile policy.";
    };
    visuals.upscaler = mkOption {
      type = types.enum [ "none" ];
      default = "none";
      description = "Cross-emulator upscaling policy.";
    };
    controllers.assignment = mkOption {
      type = types.enum [ "connection-order-persistent" ];
      default = "connection-order-persistent";
      description = "Player assignment policy for Bluetooth controllers.";
    };
    startup.mode = mkOption {
      type = types.enum [ "kiosk" "console" ];
      default = "kiosk";
      description = "Whether the emulation host boots directly into ES-DE or a local debug console.";
    };
    romDisk = {
      uuid = mkOption {
        type = types.nullOr types.str;
        default = null;
        description = "Optional filesystem UUID for the future local ROM SSD mounted at romRoot.";
      };
      fsType = mkOption {
        type = types.str;
        default = "ext4";
        description = "Filesystem type for the optional local ROM SSD.";
      };
      mountOptions = mkOption {
        type = types.listOf types.str;
        default = [ "nofail" "x-systemd.device-timeout=10s" ];
        description = "Mount options for the optional local ROM SSD.";
      };
    };

    internal = {
      lib = mkOption {
        type = types.attrsOf types.anything;
        default = { };
        internal = true;
        description = "Internal shared emulation metadata.";
      };
      packages = mkOption {
        type = types.attrsOf types.anything;
        default = { };
        internal = true;
        description = "Internal shared emulation packages.";
      };
      scripts = mkOption {
        type = types.attrsOf types.package;
        default = { };
        internal = true;
        description = "Internal shared emulation scripts.";
      };
      setupScripts = mkOption {
        type = types.listOf types.package;
        default = [ ];
        internal = true;
        description = "Additional setup scripts called before ES-DE starts.";
      };
    };
  };

  config = mkIf cfg.enable {
    assertions = [
      {
        assertion = cfg.frontend == "es-de";
        message = "The emulation profile only supports ES-DE.";
      }
    ];
  };
}
