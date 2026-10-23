# The host's unattended-upgrade decommission and the daily configuration
# drift check, as the host actually evaluates them.
#
# The deployment host must not upgrade itself any more: no
# `myOptions.autoUpgrade`, no `system.autoUpgrade` and no `nixos-upgrade`
# service or timer. The replacement is a daily persistent timer that runs the
# read-only configuration drift check. Its service may read the two host links
# and write only its private state directory; the host links are read-only and
# the unit holds no capability. The other hosts keep their unattended upgrade.
let
  flake = builtins.getFlake (toString ../.);
  host = flake.nixosConfigurations.chill-penguin;
  inherit (host.pkgs) lib;
  config = host.config;
  drift = config.ghostship.configurationDrift;
  service = config.systemd.services.ghostship-configuration-drift;
  timer = config.systemd.timers.ghostship-configuration-drift;
  hardening = service.serviceConfig;
  calendar = lib.toList timer.timerConfig.OnCalendar;
  revision = config.system.configurationRevision;
  automation = builtins.readFile ../modules/common/automation.nix;
  driftModule = builtins.readFile ../modules/self-hosted/configuration-drift.nix;
in
assert lib.assertMsg (!config.myOptions.autoUpgrade.enable)
  "chill-penguin must not enable myOptions.autoUpgrade.";
assert lib.assertMsg (!config.system.autoUpgrade.enable)
  "chill-penguin must not enable system.autoUpgrade.";
assert lib.assertMsg (!(config.systemd.services ? nixos-upgrade))
  "chill-penguin must not render the nixos-upgrade service.";
assert lib.assertMsg (!(config.systemd.timers ? nixos-upgrade))
  "chill-penguin must not render the nixos-upgrade timer.";
assert lib.assertMsg drift.enable
  "chill-penguin must enable the configuration drift check.";
assert lib.assertMsg (timer.wantedBy == [ "timers.target" ])
  "the configuration drift timer must be wanted by timers.target, not ${lib.concatStringsSep ", " timer.wantedBy}.";
assert lib.assertMsg timer.timerConfig.Persistent
  "the configuration drift timer must be persistent.";
assert lib.assertMsg (lib.elem "daily" calendar)
  "the configuration drift timer must run daily, not ${lib.concatStringsSep ", " calendar}.";
assert lib.assertMsg (timer.timerConfig.Unit == "ghostship-configuration-drift.service")
  "the configuration drift timer must run ghostship-configuration-drift.service, not ${timer.timerConfig.Unit}.";
assert lib.assertMsg (lib.hasInfix "configuration-drift.py" hardening.ExecStart)
  "the configuration drift service must run configuration-drift.py, not ${hardening.ExecStart}.";
assert lib.assertMsg (hardening.Type == "oneshot")
  "the configuration drift service must be a oneshot, not ${hardening.Type}.";
assert lib.assertMsg (hardening.StateDirectory == "ghostship-configuration-drift")
  "the configuration drift service must keep its state in ghostship-configuration-drift, not ${hardening.StateDirectory}.";
assert lib.assertMsg (hardening.StateDirectoryMode == "0700")
  "the configuration drift state directory must be 0700, not ${hardening.StateDirectoryMode}.";
assert lib.assertMsg (hardening.UMask == "0077")
  "the configuration drift service must run with UMask 0077, not ${hardening.UMask}.";
assert lib.assertMsg (hardening.ProtectSystem == "strict")
  "the configuration drift service must mount the host read-only (ProtectSystem=strict).";
assert lib.assertMsg hardening.ProtectHome
  "the configuration drift service must hide the home directories.";
assert lib.assertMsg hardening.PrivateTmp
  "the configuration drift service must use a private /tmp.";
assert lib.assertMsg hardening.NoNewPrivileges
  "the configuration drift service must not gain privileges.";
assert lib.assertMsg (hardening.CapabilityBoundingSet == "")
  "the configuration drift service must hold no capability, not ${toString hardening.CapabilityBoundingSet}.";
assert lib.assertMsg (lib.elem "/run/current-system" hardening.ReadOnlyPaths)
  "the running system must be a read-only path.";
assert lib.assertMsg (lib.elem "/nix/var/nix/profiles/system" hardening.ReadOnlyPaths)
  "the system profile must be a read-only path.";
assert lib.assertMsg (revision != null && (revision == "dirty" || builtins.match "[0-9a-f]{40}" revision != null))
  "system.configurationRevision must record the flake revision or dirty, not ${toString revision}.";
assert lib.assertMsg (lib.hasInfix "https://github.com/ghostship-io/ghostship-config.git" driftModule)
  "the configuration drift module must fetch the same repository as the unattended upgrade.";
assert lib.assertMsg (lib.hasInfix "github.com/ghostship-io/ghostship-config.git" automation)
  "modules/common/automation.nix must still name the source repository.";
assert lib.assertMsg flake.nixosConfigurations.armored-armadillo.config.system.autoUpgrade.enable
  "armored-armadillo must keep its unattended upgrade.";
assert lib.assertMsg flake.nixosConfigurations.launch-octopus.config.system.autoUpgrade.enable
  "launch-octopus must keep its unattended upgrade.";
true
