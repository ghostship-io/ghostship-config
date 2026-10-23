{ config, lib, ... }:

# Notification coverage: every ghostship-* and podman-* unit, and each custom
# unit named below, reports its failure to the operations topic through
# ghostship-failure@ (monitoring.nix). Backup jobs also publish a silent
# summary to informational through ghostship-success@. Exempting a unit needs
# a reason; the assertions fail the build when a covered unit loses its path
# or an entry here names a unit that no longer exists.
let
  failure = "ghostship-failure@%n.service";
  success = "ghostship-success@%n.service";

  # Custom units whose names carry no covered prefix.
  extraUnits = [
    "agent-desktop-mcp"
    "agent-desktop-ssh"
    "chill-penguin-retired-artifact-cleanup"
    "falco"
    "flaresolverr-egress"
    "gluetun-network-monitor"
    "gluetun-pia-selector"
    "homepage-podman-broker"
    "init-agent-desktop-net"
    "init-ghostship-github-net"
    "init-ghostship-net"
    "init-ghostship-siem-net"
    "prometheus-node-exporter"
    "pyload-restart-failed"
    "qbittorrent-auto-resume"
    "romm-recovery"
    "siem-egress"
    "t3code-deploy-when-idle"
    "t3code-nix-store-gc"
    "tdarr-language-policy"
    "tdarr-staged-guard"
    "vector"
  ]
  # A host that still upgrades unattended keeps its nixos-upgrade failure
  # path. The deployment host turns that unit off, so naming it there would
  # trip the stale-entry assertion below.
  ++ lib.optional config.system.autoUpgrade.enable "nixos-upgrade";

  exemptions = {
    "ghostship-failure@" = "the failure notifier itself; a failing notifier would notify about itself";
    "ghostship-success@" =
      "the summary notifier; its failure is the missing summary and stays in the journal";
    "ghostship-monitoring-heartbeats" =
      "Uptime Kuma alerts operations when its five-minute pushes stop, so a failure path would duplicate it";
  };

  covered =
    name:
    (lib.hasPrefix "ghostship-" name || lib.hasPrefix "podman-" name || builtins.elem name extraUnits)
    && !(exemptions ? ${name});
  summarized = name: lib.hasPrefix "ghostship-backup-" name;

  services = config.systemd.services;
  missing = lib.filter (name: covered name && !(builtins.elem failure services.${name}.onFailure)) (
    builtins.attrNames services
  );
  stale = lib.filter (name: !(services ? ${name})) (extraUnits ++ builtins.attrNames exemptions);
  unexplained = lib.filter (name: exemptions.${name} == "") (builtins.attrNames exemptions);
in
{
  options.systemd.services = lib.mkOption {
    type = lib.types.attrsOf (
      lib.types.submodule (
        { name, ... }:
        {
          onFailure = lib.mkIf (covered name) [ failure ];
          onSuccess = lib.mkIf (summarized name) [ success ];
        }
      )
    );
  };

  config.assertions = [
    {
      assertion = missing == [ ];
      message = "Units without a notification path (restore ${failure} or exempt them in notify-coverage.nix): ${toString missing}";
    }
    {
      assertion = stale == [ ];
      message = "notify-coverage.nix names units that no longer exist: ${toString stale}";
    }
    {
      assertion = unexplained == [ ];
      message = "notify-coverage.nix exemptions need a reason: ${toString unexplained}";
    }
  ];
}
