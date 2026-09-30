{
  config,
  lib,
  pkgs,
  ...
}:

# Btrfs never returns allocated but empty metadata chunks to the device on its
# own; without periodic reclamation the chunk tree fills, the global reserve is
# exhausted, and the kernel latches the filesystem read-only while `df` still
# reports free space. These timers consolidate near-empty chunks and bound the
# sources of churn that grow metadata.
lib.mkIf ((config.fileSystems."/".fsType or "") == "btrfs") {
  # Bound journal growth: it once reached several GiB and its active file could
  # not rotate while the filesystem was read-only.
  services.journald.settings.Journal.SystemMaxUse = "1G";

  # Reclaim metadata: relocates only chunks below the usage thresholds, so
  # nearly-empty chunks are consolidated and returned to the device. Serialized
  # against backups and container updates through the shared maintenance lock.
  systemd.services.ghostship-btrfs-balance = {
    description = "Balance near-empty Btrfs metadata and data chunks";
    serviceConfig = {
      Type = "oneshot";
      ExecStart = "${pkgs.util-linux}/bin/flock -w 300 /run/ghostship-maintenance.lock ${pkgs.btrfs-progs}/bin/btrfs balance start -dusage=5 -musage=5 /";
      TimeoutStartSec = "4h";
      Nice = 10;
      IOSchedulingClass = "idle";
    };
    onFailure = [ "ghostship-failure@%n.service" ];
  };
  systemd.timers.ghostship-btrfs-balance = {
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnCalendar = "weekly";
      Persistent = true;
      RandomizedDelaySec = "1h";
    };
  };

  # Bound image churn: superseded tags from `pull = "always"` containers
  # accumulate across updates. Images older than a week that no container
  # references are removed; active images are re-pulled on their next start.
  systemd.services.ghostship-image-prune = {
    description = "Prune unused Podman images";
    serviceConfig = {
      Type = "oneshot";
      ExecStart = "${pkgs.util-linux}/bin/flock -w 300 /run/ghostship-maintenance.lock ${pkgs.podman}/bin/podman image prune -a -f --filter until=168h";
      Nice = 10;
      IOSchedulingClass = "idle";
    };
    onFailure = [ "ghostship-failure@%n.service" ];
  };
  systemd.timers.ghostship-image-prune = {
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnCalendar = "weekly";
      Persistent = true;
      RandomizedDelaySec = "1h";
    };
  };
}
