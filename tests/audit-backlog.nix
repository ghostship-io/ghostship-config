# The kernel audit backlog limit, as the host actually hands it to the kernel.
#
# `security.audit.backlogLimit` reaches the kernel twice: NixOS writes it into
# the generated audit rules (`-b <limit>`, loaded by audit-rules-nixos.service
# with `auditctl -R`) and into the kernel command line
# (`audit_backlog_limit=<limit>`). A third path exists here: the
# ghostship-audit-backlog unit runs `auditctl -b <limit>` after those rules were
# loaded, so it decides the value the kernel ends up with. It must carry the
# same limit, or it silently lowers the one the other two paths set.
#
# A larger backlog is the only thing that keeps a restart burst (many
# containers starting at once, each generating a complain-mode audit record)
# from filling the queue: a full queue drops records, and a dropped record is
# a detection that never happened. Nothing else may change with it: the
# failure mode, the rate limit and the rules stay as they are.
let
  flake = builtins.getFlake (toString ../.);
  base = flake.nixosConfigurations.chill-penguin;
  inherit (base.pkgs) lib;
  config = base.config;
  audit = config.security.audit;
  expected = 131072;
  kernelParam = "audit_backlog_limit=${toString expected}";
  runtimeExecStart = config.systemd.services.ghostship-audit-backlog.serviceConfig.ExecStart;
  runtimeLimit =
    let
      matched = builtins.match ".*-b ([0-9]+).*" runtimeExecStart;
    in
    if matched == null then "unset" else builtins.head matched;
in
assert lib.assertMsg (audit.backlogLimit == expected)
  "security.audit.backlogLimit must be ${toString expected}, not ${toString audit.backlogLimit}.";
assert lib.assertMsg (builtins.elem kernelParam config.boot.kernelParams)
  "The kernel command line must carry ${kernelParam}.";
assert lib.assertMsg (runtimeLimit == toString expected)
  "The ghostship-audit-backlog unit must set auditctl -b ${toString expected}, not ${runtimeLimit}.";
assert lib.assertMsg (audit.failureMode == "printk")
  "The audit failure mode must stay printk, not ${audit.failureMode}.";
assert lib.assertMsg (audit.rateLimit == 0)
  "The audit rate limit must stay 0 (unlimited), not ${toString audit.rateLimit}.";
true
