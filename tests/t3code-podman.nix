let
  flake = builtins.getFlake (toString ../.);
  base = flake.nixosConfigurations.chill-penguin;
  inherit (base.pkgs) lib;
  candidate =
    extra:
    (base.extendModules {
      modules = [ extra ];
    }).config;
  enabled = {
    ghostship.t3codePodman = {
      enable = true;
    };
  };
  failures =
    extra:
    map (a: a.message) (
      builtins.filter (a: !a.assertion)
        (candidate {
          config = lib.mkMerge [
            enabled
            extra
          ];
        }).assertions
    );
  cfg = candidate enabled;
in
# The dedicated rootless engine replaces the legacy inner daemon.
assert (candidate { }).ghostship.t3codePodman.enable;
assert !(candidate { }).ghostship.t3codePodman.candidate;
assert failures { } == [ ];
# Admission: UID reuse or subordinate overlap turns dev access into apps access.
assert builtins.elem "T3 Podman must not reuse the apps UID/GID." (failures {
  ghostship.t3codePodman.uid = 3000;
});
assert builtins.elem "T3 Podman subordinate UID range overlaps another account." (failures {
  users.users.collision = {
    isSystemUser = true;
    group = "apps";
    subUidRanges = [
      {
        startUid = 2000100;
        count = 65536;
      }
    ];
  };
});
# Runtime policy is evaluated, so aliases and native module fields cannot
# bypass the source scanner. These are actual extended NixOS modules.
assert builtins.elem "The container runtime must be Podman." (failures {
  virtualisation.docker.enable = true;
});
assert builtins.elem "Runtime compatibility binaries and sockets are not allowed." (failures {
  virtualisation.podman.dockerCompat = true;
});
assert builtins.elem "Only Podman runtime packages may be installed." (failures {
  environment.systemPackages = [ base.pkgs.docker ];
});
assert !(cfg.systemd.services ? docker);
assert !(cfg.users.users ? t3code-docker);
assert builtins.elem "/run/t3code-podman/podman.sock:/var/run/podman/podman.sock:rw"
  cfg.virtualisation.oci-containers.containers.t3code.volumes;
# A public hostname on the container also becomes a Podman DNS alias and a
# self hosts-file entry. It shadows the Cloudflare HTTPS edge with port 3773's
# HTTP-only origin for both the desktop and the container itself.
assert builtins.elem "--hostname=t3code"
  cfg.virtualisation.oci-containers.containers.t3code.extraOptions;
assert
  !(builtins.elem "--hostname=${cfg.ghostship.apps.t3code.hostname}" cfg.virtualisation.oci-containers.containers.t3code.extraOptions);
# Relays follow the manager so socket activation can recover after its exit.
assert builtins.elem "user@62040.service" cfg.systemd.services.t3code-podman.bindsTo;
assert builtins.elem "user@62040.service" cfg.systemd.services.t3code-podman-ports.bindsTo;
# Preserved private roots must migrate before the per-user manager reexec.
assert builtins.elem "t3code-podman-identity"
  cfg.system.activationScripts.t3code-podman-reexec-alias.deps;
assert lib.hasInfix "rootfs.py reconcile /run/t3code-podman-rootfs "
  cfg.system.activationScripts.t3code-podman-reexec-alias.text;
# The rendered manager must select the dedicated directory that declares the
# mandatory activation unit; testing a mock manager cannot prove this contract.
assert
  let
    unitPath = cfg.systemd.services."user@62040".environment.SYSTEMD_UNIT_PATH;
    manager = cfg.systemd.units."user@62040.service".text;
    activation = builtins.readFile "${unitPath}/nixos-activation.service";
  in
  lib.hasInfix (builtins.unsafeDiscardStringContext "SYSTEMD_UNIT_PATH=${unitPath}") manager
  && lib.hasInfix "Type=oneshot" activation
  && lib.hasInfix "RemainAfterExit=yes" activation
  && lib.hasInfix (builtins.unsafeDiscardStringContext "ExecStart=${base.pkgs.coreutils}/bin/true") activation;
assert !(cfg.system.activationScripts ? t3code-podman-user-activation);
# Force generation of actual system unit text, including the template drop-in.
{
  system = cfg.system.build.toplevel.drvPath;
  manager = cfg.systemd.units."user@62040.service".text;
  network = cfg.systemd.units."t3code-podman-network.service".text;
  rootfs = cfg.systemd.units."t3code-podman-rootfs.service".text;
  socket = cfg.systemd.units."t3code-podman.socket".text;
}
