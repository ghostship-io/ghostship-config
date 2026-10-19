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
        "complain,"
        "<plex-apparmor-runtime.inc>"
        "<plex-apparmor-startup.inc>"
        "<plex-apparmor-python.inc>"
      ]
      [
        ""
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
            processProfiles = [
              app.apparmorProfile
            ]
            ++ lib.optionals (app.apparmorProfile == "ghostship-plex") [
              "ghostship-plex//server"
              "ghostship-plex//python"
            ]
            ++ lib.optional (app.apparmorProfile == "ghostship-ntfy") "ghostship-ntfy//tools";
            requiredProcessProfiles = [
              app.apparmorProfile
            ]
            ++ lib.optionals (app.apparmorProfile == "ghostship-plex") [
              "ghostship-plex//server"
              "ghostship-plex//python"
            ];
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
    policies.ghostship-plex = {
      state = "complain";
      profile = profileText;
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

  virtualisation.oci-containers.containers = builtins.listToAttrs (
    map (app: {
      name = app.container;
      value.extraOptions = [ "--security-opt=apparmor=${app.apparmorProfile}" ];
    }) profiled
  );

  systemd.services = lib.mkMerge [
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
      ghostship-apparmor-review = {
        description = "Collect verified AppArmor learning evidence for public services";
        after = [ "apparmor.service" ] ++ map (app: "podman-${app.container}.service") profiled;
        onFailure = [ "ghostship-failure@%n.service" ];
        serviceConfig = {
          Type = "oneshot";
          ExecStart = lib.getExe review;
          StateDirectory = "ghostship-apparmor-review";
          StateDirectoryMode = "0700";
          UMask = "0077";
          TimeoutStartSec = "5min";
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
