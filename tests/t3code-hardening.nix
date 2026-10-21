let
  flake = builtins.getFlake (toString ../.);
  base = flake.nixosConfigurations.chill-penguin;
  inherit (base.pkgs) lib;
  candidate =
    (base.extendModules {
      modules = [ { ghostship.t3code.hardening.enable = true; } ];
    }).config;
  runtime = candidate.virtualisation.oci-containers.containers.t3code;
  has = value: builtins.elem value runtime.extraOptions;
  service = candidate.systemd.services.podman-t3code;
in
# A hardened candidate must not recover blanket host privileges through Docker
# or an alternate runtime flag. The accepted root-SSH administration path stays.
assert !(has "--privileged");
assert !(has "--cap-add=SYS_ADMIN");
assert !(has "--cap-add=SYS_PTRACE");
assert !(has "--cap-add=NET_ADMIN");
assert has "--cap-drop=ALL";
assert !(has "--security-opt=seccomp=unconfined");
assert has "--security-opt=apparmor=ghostship-t3code";
assert builtins.elem "t3code" candidate.ghostship.security.host_ssh_clients;
assert builtins.elem "/run/t3code-docker/docker.sock:/var/run/docker.sock:rw" runtime.volumes;
assert !(lib.any (mount: lib.hasInfix ":/var/lib/docker:" mount) runtime.volumes);
assert !(lib.any (mount: lib.hasInfix ":/mnt/share:" mount) runtime.volumes);
assert builtins.elem "/mnt/share/Library/ROMS:/mnt/share/Library/ROMS:ro,nosuid,nodev"
  runtime.volumes;
# Preparing or activating the candidate must preserve the current session.
assert service.restartIfChanged == false;
assert service.stopIfChanged == false;
true
