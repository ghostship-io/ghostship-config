{
  config,
  lib,
  pkgs,
  ...
}:
let
  backup = pkgs.writeShellApplication {
    name = "ghostship-backup";
    runtimeInputs = with pkgs; [
      restic
      btrfs-progs
      util-linux
      coreutils
      systemd
      podman
      python3
    ];
    excludeShellChecks = [ "SC1091" ];
    text = builtins.replaceStrings [ "@restoreCheck@" ] [ "${./restore-check.sh}" ] (
      builtins.readFile ./backup.sh
    );
  };
  jobs = {
    backup = "23:00";
    check = "Sun 21:00";
    sample = "*-*-01 20:00";
    prune = "Sun 19:00";
  };
in
{
  config = lib.mkMerge [
    {
      environment.systemPackages = [ backup ];
      systemd.tmpfiles.rules = [
        "d /var/lib/ghostship-backup 0700 root root -"
        "d /var/cache/ghostship-backup 0700 root root -"
        "d /srv/retired-apps 0700 root root -"
      ];
      systemd.services = lib.mapAttrs' (
        name: _:
        lib.nameValuePair "ghostship-backup-${name}" {
          description = "Ghostship Restic ${name}";
          wants = [ "network-online.target" ];
          after = [
            "network-online.target"
            "podman-romm-db.service"
            "podman-grimmory-db.service"
          ];
          unitConfig.RequiresMountsFor = [
            "/mnt/share"
            "/srv"
          ];
          serviceConfig = {
            Type = "oneshot";
            ExecStart = "${backup}/bin/ghostship-backup ${name}";
            TimeoutStartSec = "8h";
            UMask = "0077";
            Nice = 10;
            IOSchedulingClass = "idle";
          };
        }
      ) jobs;
      systemd.timers = lib.mapAttrs' (
        name: calendar:
        lib.nameValuePair "ghostship-backup-${name}" {
          wantedBy = [ "timers.target" ];
          timerConfig = {
            OnCalendar = calendar;
            Persistent = true;
            RandomizedDelaySec = "10min";
          };
        }
      ) jobs;
    }
    {
      systemd.services.podman-auto-update.preStart = lib.mkAfter ''
        # Keep updates automatic, but never migrate state without a recent backup.
        stamp=/var/lib/ghostship-backup/last-success
        if [ ! -s "$stamp" ] || [ "$(( $(${pkgs.coreutils}/bin/date +%s) - $(cat "$stamp") ))" -gt 108000 ]; then
          echo "Container updates deferred: no successful backup within 30 hours" >&2
          exit 1
        fi
      '';
      systemd.services.podman-auto-update.serviceConfig.ExecStart =
        lib.mkForce "${pkgs.util-linux}/bin/flock -w 300 /run/ghostship-maintenance.lock ${pkgs.podman}/bin/podman auto-update";
    }
  ];
}
