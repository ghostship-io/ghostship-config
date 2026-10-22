{
  config,
  lib,
  pkgs,
  ...
}:
let
  apps = builtins.attrValues config.ghostship.apps;
  profiled = lib.filter (app: app.apparmorProfile != null) apps;
  public = lib.filter (app: app.public) apps;
  profileText =
    builtins.replaceStrings
      [
        "<plex-apparmor-runtime.inc>"
        "<plex-apparmor-startup.inc>"
        "<plex-apparmor-python.inc>"
      ]
      [
        ''"${./plex-apparmor-runtime.inc}"''
        ''"${./plex-apparmor-startup.inc}"''
        ''"${./plex-apparmor-python.inc}"''
      ]
      (builtins.readFile ./plex-apparmor.profile);
  reviewConfig = pkgs.writeText "ghostship-apparmor-review.json" (
    builtins.toJSON {
      containers = builtins.listToAttrs (
        map (app: {
          name = app.container;
          value = {
            profile = app.apparmorProfile;
            source = config.environment.etc."apparmor.d".source + "/${app.apparmorProfile}";
            mode = config.security.apparmor.policies.${app.apparmorProfile}.state;
            processModes = app.apparmorProcessModes;
            processProfiles = app.apparmorProcessProfiles;
            requiredProcessProfiles = app.apparmorRequiredProcessProfiles;
            heartbeat = app.apparmorHeartbeat;
          };
        }) profiled
      );
    }
  );
  review = pkgs.writeShellApplication {
    name = "ghostship-apparmor-review";
    runtimeInputs = [
      pkgs.python3
      config.virtualisation.podman.package
      pkgs.systemd
      pkgs.coreutils
      pkgs.audit
    ];
    text = ''
      exec python3 ${./apparmor-review.py} --config ${reviewConfig} \
        --state-dir /var/lib/ghostship-apparmor-review "$@"
    '';
  };
in
{
  # The Asahi host already runs IMA; keep it when Nix emits an explicit lsm= list.
  security.lsm = [ "ima" ];
  # Podman's AppArmor detection also requires the parser on its wrapper PATH.
  virtualisation.podman.extraPackages = [ pkgs.apparmor-parser ];
  # Drain audit netlink directly; printk fallback rate-limits learning bursts.
  security.auditd = {
    enable = true;
    settings = {
      log_group = "root";
      max_log_file = 64;
      num_logs = 8;
      max_log_file_action = "ROTATE";
    };
  };
  security.apparmor = {
    enable = true;
    # Podman tests /etc directly before including global variable definitions.
    # Without this, its default profile imports base with HOMEDIRS undefined.
    includes."tunables/global" = ''
      include "${pkgs.apparmor-profiles}/etc/apparmor.d/tunables/global"
    '';
    # Profiles learn in complain mode, except Plex's enforced Internet-facing
    # domains; explicit deny rules always apply.
    policies.ghostship-container-default = {
      state = "complain";
      profile = builtins.readFile ./container-default-apparmor.profile;
    };
    # Mixed: the profile's own flags keep startup and healthcheck in complain.
    policies.ghostship-plex = {
      state = "enforce";
      profile = profileText;
    };
    policies.ghostship-hooks = lib.mkIf config.ghostship.githubEngineering.enable {
      state = "complain";
      profile = builtins.replaceStrings [ "complain," ] [ "" ] (
        builtins.readFile ./hooks-apparmor.profile
      );
    };
    policies.ghostship-ntfy = {
      state = "complain";
      profile = builtins.replaceStrings [ "complain," ] [ "" ] (
        builtins.readFile ./ntfy-apparmor.profile
      );
    };
  };

  assertions = [
    {
      # T3 runs privileged and unconfined until its de-privileging lands (#102).
      assertion = lib.all (app: app.apparmorProfile != null || app.container == "t3code") apps;
      message = "Every Ghostship container must declare its own strict AppArmor profile.";
    }
    {
      assertion = profiled == [ ] || config.security.apparmor.enable;
      message = "Profiled public services require AppArmor to be enabled on the host.";
    }
    {
      assertion = lib.all (app: app.apparmorProfile != null) public;
      message = "Every Internet-facing Ghostship service must declare an AppArmor profile.";
    }
    {
      assertion = lib.all (
        app:
        app.apparmorProfile != "unconfined"
        && builtins.hasAttr app.apparmorProfile config.security.apparmor.policies
        && config.security.apparmor.policies.${app.apparmorProfile}.state != "disable"
      ) profiled;
      message = "Application AppArmor profiles must exist and be enabled.";
    }
    {
      assertion = lib.all (
        app:
        lib.filter (
          opt: lib.hasInfix "apparmor=" opt
        ) config.virtualisation.oci-containers.containers.${app.container}.extraOptions
        == [ "--security-opt=apparmor=${app.apparmorProfile}" ]
      ) profiled;
      message = "Containers must use their declared AppArmor profile.";
    }
  ];

  # Containers without their own profile get the declared default, which
  # survives AppArmor reloads (see container-default-apparmor.profile).
  virtualisation.containers.containersConf.settings.containers.apparmor_profile =
    "ghostship-container-default";

  virtualisation.oci-containers.containers = builtins.listToAttrs (
    map (app: {
      name = app.container;
      value.extraOptions = [ "--security-opt=apparmor=${app.apparmorProfile}" ];
    }) profiled
  );

  systemd.services = lib.mkMerge [
    (lib.mapAttrs' (
      name: _:
      lib.nameValuePair "podman-${name}" {
        wants = [ "apparmor.service" ];
        after = [ "apparmor.service" ];
      }
    ) (removeAttrs config.virtualisation.oci-containers.containers (map (app: app.container) profiled)))
    (builtins.listToAttrs (
      map (app: {
        name = "podman-${app.container}";
        value = {
          requires = [ "apparmor.service" ];
          after = [ "apparmor.service" ];
          # Fail closed if an activation is attempted before the first AppArmor boot.
          preStart = lib.mkBefore ''
            ${pkgs.gnugrep}/bin/grep -q '^${app.apparmorProfile} (' \
              /sys/kernel/security/apparmor/profiles
          '';
        };
      }) profiled
    ))
    {
      # Complain-mode learning bursts (every strict profile at container start)
      # overflow the kernel's 1024-record backlog; lost records reset every window.
      # A container restart burst overflowed 32768 as well, so this unit carries
      # security.audit.backlogLimit (131072): it runs after the audit rules were
      # loaded and sets the value the kernel ends up with.
      ghostship-audit-backlog = {
        description = "Raise the kernel audit backlog for AppArmor learning";
        after = [ "auditd.service" ];
        wantedBy = [ "multi-user.target" ];
        before = [ "apparmor.service" ];
        serviceConfig = {
          Type = "oneshot";
          RemainAfterExit = true;
          ExecStart = "${pkgs.audit}/bin/auditctl -b ${toString config.security.audit.backlogLimit}";
        };
      };
      ghostship-apparmor-review = {
        description = "Collect verified AppArmor learning evidence for public services";
        after = [ "apparmor.service" ] ++ map (app: "podman-${app.container}.service") profiled;
        serviceConfig = {
          Type = "oneshot";
          ExecStart = lib.getExe review;
          StateDirectory = "ghostship-apparmor-review";
          StateDirectoryMode = "0700";
          UMask = "0077";
          # One bounded journal read per profiled container.
          TimeoutStartSec = "15min";
        };
      };
    }
  ];
  systemd.timers.ghostship-apparmor-review = {
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnCalendar = "*-*-* 08:30:00 UTC";
      Persistent = true;
    };
  };
  # Audit delivery must survive ordinary Plex restarts and daily review windows.
  services.journald.settings.Journal = {
    Storage = "persistent";
    MaxRetentionSec = "30day";
  };
  environment.systemPackages = [ review ];
}
