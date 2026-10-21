let
  flake = builtins.getFlake (toString ../.);
  base = flake.nixosConfigurations.chill-penguin;
  inherit (base.pkgs) lib;
  candidate =
    extra:
    (base.extendModules {
      modules = [
        ../modules/self-hosted/t3code-docker.nix
        extra
      ];
    }).config;
  enabled = {
    ghostship.t3codeDocker = {
      enable = true;
      egressInterface = "eth0";
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
# Admission: accidental activation changes the active T3 deployment.
assert !(candidate { }).ghostship.t3codeDocker.enable;
assert !(candidate { }).systemd.services ? t3code-docker-network;
assert failures { } == [ ];
# Admission: UID reuse or subordinate overlap turns dev access into apps access.
assert builtins.elem "T3 Docker must not reuse the apps UID/GID." (failures {
  ghostship.t3codeDocker.uid = 3000;
});
assert builtins.elem "T3 Docker subordinate UID range overlaps another account." (failures {
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
# Force generation of actual system unit text, including the template drop-in.
{
  system = cfg.system.build.toplevel.drvPath;
  manager = cfg.systemd.units."user@62040.service".text;
  network = cfg.systemd.units."t3code-docker-network.service".text;
  rootfs = cfg.systemd.units."t3code-docker-rootfs.service".text;
  socket = cfg.systemd.units."t3code-docker.socket".text;
}
