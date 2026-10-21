{ config, lib, ... }:
let
  cfg = config.ghostship.t3code.hardening;
in
{
  options.ghostship.t3code.hardening.enable =
    lib.mkEnableOption "the verified T3 platform with a separate rootless development engine";

  config = {
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
      cap_add_allow.t3code = [ "CAP_SYS_RESOURCE" ];
      socket_mount_allow = [ "/run/t3code-docker/docker.sock" ];
    };
  };
}
