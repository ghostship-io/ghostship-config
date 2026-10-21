{ config, lib, ... }:
let
  cfg = config.ghostship.t3code.hardening;
in
{
  options.ghostship.t3code.hardening = {
    enable = lib.mkEnableOption "the verified T3 platform with a separate rootless development engine";
    sharedMounts = lib.mkOption {
      type = lib.types.attrsOf lib.types.bool;
      default = {
        "Library/ROMS" = true;
        "Projects/goship-roms" = false;
        "Downloads/PyLoad" = false;
      };
      description = "NAS directories needed by local ROM workflows; values select read-only access. Other host administration uses root SSH.";
    };
  };

  config = {
    assertions = [
      {
        assertion = lib.all (path: builtins.match "[A-Za-z0-9_-]+(/[A-Za-z0-9_-]+)*" path != null) (
          builtins.attrNames cfg.sharedMounts
        );
        message = "T3 shared mounts must be explicit relative directory paths without traversal.";
      }
    ];
    security.apparmor.policies.ghostship-t3code = {
      state = "complain";
      profile = builtins.readFile ./apparmor/t3code.profile;
    };
    ghostship.apps.t3code = lib.mkIf cfg.enable {
      apparmorProfile = "ghostship-t3code";
      apparmorHeartbeat = [
        "/bin/cat"
        "/proc/sys/kernel/random/boot_id"
      ];
    };
    ghostship.security = lib.mkIf cfg.enable {
      privileged_allow = lib.mkForce [ ];
      cap_add_allow.t3code = map (cap: "CAP_${cap}") (
        builtins.fromJSON (builtins.readFile ../../packages/t3code/runtime-caps.json)
      );
      socket_mount_allow = [ "/run/t3code-docker/docker.sock" ];
    };
  };
}
