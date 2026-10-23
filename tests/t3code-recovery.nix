# Inspect the actual rendered host policy without starting any host services.
let
  flake = builtins.getFlake (toString ../.);
  c = flake.nixosConfigurations.chill-penguin.config;
  inherit (flake.nixosConfigurations.chill-penguin.pkgs) lib;
  controller = c.systemd.services.t3code-recovery.serviceConfig;
  advisor = c.systemd.services.t3code-recovery-advisor.serviceConfig;
  rendered = c.systemd.units."t3code-recovery-advisor.service".text;
  auth = "/srv/apps/t3code/home/.codex/auth.json";
in
assert lib.hasInfix "Type=exec" rendered;
assert lib.hasInfix "RuntimeMaxSec=480" rendered;
assert lib.hasInfix "CapabilityBoundingSet=" rendered;
assert lib.hasInfix "approval = \"owner-automation-request-2026-10-23\"" (
  builtins.readFile ../modules/self-hosted/t3code-recovery.nix
);
assert builtins.elem "t3code-recovery-advisor-auth.service"
  c.systemd.services.t3code-recovery-advisor.requires;
assert c.systemd.services.t3code-recovery-advisor-auth.serviceConfig.User == "root";
assert !(advisor ? ExecStartPre);
assert advisor.BindPaths == [ "/run/t3code-recovery/advisor/proposal.json" ];
assert advisor.ReadWritePaths == [ "/run/t3code-recovery/advisor/proposal.json" ];
assert controller.User == "root";
assert controller.Restart == "always";
assert controller.RuntimeMaxSec == 1200;
assert controller.MemoryMax == "1G" && controller.TasksMax == 256 && controller.CPUQuota == "100%";
assert advisor.Type == "exec" && advisor.RuntimeMaxSec == 480;
assert advisor.User == "3000" && advisor.Group == "3000";
assert advisor.MemoryMax == "1G" && advisor.TasksMax == 256 && advisor.CPUQuota == "100%";
assert advisor.CapabilityBoundingSet == "" && advisor.NoNewPrivileges;
assert advisor.ProtectSystem == "strict" && advisor.ProtectHome == "tmpfs";
assert advisor.PrivateTmp && advisor.ProtectProc == "invisible";
assert builtins.elem "/srv:ro" advisor.TemporaryFileSystem;
assert builtins.elem "/var:ro" advisor.TemporaryFileSystem;
assert builtins.elem "/workspace:ro" advisor.TemporaryFileSystem;
assert builtins.elem "${auth}:/run/t3code-advisor/home/auth.json" advisor.BindReadOnlyPaths;
assert builtins.length (builtins.filter (p: lib.hasInfix "/srv/" p) advisor.BindReadOnlyPaths) == 1;
assert !c.systemd.services.podman-t3code.restartIfChanged;
assert !c.systemd.services.podman-t3code.stopIfChanged;
assert c.system.build ? t3codeRecoveryController;
assert c.system.build ? t3codeRecoveryAdvisor;
assert c.system.build ? t3codeRecoveryConfig;
assert c.system.build.t3codeRecoveryCodex.version == "0.163.0";
assert c.system.build ? t3codeRecoveryUnits;
true
