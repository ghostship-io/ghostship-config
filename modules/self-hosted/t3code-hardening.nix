{ config, lib, ... }:
let
  cfg = config.ghostship.t3code.hardening;
  engineUid = toString config.ghostship.t3codeDocker.uid;
  # Moby's rootless daemon resolves its delegated cgroup controllers through
  # /sys/fs/cgroup/user.slice/user-<UID>.slice (dockerd createSpec.withRootless),
  # so the engine manager must stay inside that slice. The slice is therefore
  # the only parent that can hold the engine and the outer T3 container under
  # one aggregate limit without relocating the manager.
  engineSlice = "user-${engineUid}.slice";
  engineSliceKey = "user-${engineUid}";
  engineManager = "user@${engineUid}";
  containerOptions = config.virtualisation.oci-containers.containers.t3code.extraOptions;
  engineServiceConfig = config.systemd.services.${engineManager}.serviceConfig or { };
  aggregateSliceConfig = config.systemd.slices.${engineSliceKey}.sliceConfig or { };
  # The container runtime matches flag names exactly, after normalizing the
  # documented aliases, and it accepts a value either inline ("--flag=value")
  # or as the following argument ("--flag value"). A bare flag token therefore
  # carries its value in the next argument, so the option list has to be
  # checked by flag name: a filter on the prefixed value alone would miss
  # every split form and let a later flag override the placement or the bound.
  # The alias table covers the network, health, storage, and architecture
  # flags only, so no alias spells a cgroup or task flag.
  flagName = element: lib.removePrefix "--" (builtins.head (lib.splitString "=" element));
  # Every flag that can place the container or change its task bound: the
  # parent cgroup, the cgroup mode, the cgroup namespace, and the raw cgroup
  # settings that can carry a task limit of their own.
  cgroupFlagOptions = lib.filter (
    element: lib.hasPrefix "--" element && lib.hasPrefix "cgroup" (flagName element)
  ) containerOptions;
  pidsLimitOptions = lib.filter (
    element: lib.hasPrefix "--" element && (flagName element) == "pids-limit"
  ) containerOptions;
  delegatedControllers = lib.filter (word: word != "") (
    lib.splitString " " (engineServiceConfig.Delegate or "")
  );
  # systemd accepts byte sizes with an optional binary suffix.
  memoryBytes =
    value:
    let
      parsed = builtins.match "([0-9]+)([KMGTP]?)" value;
      multipliers = {
        "" = 1;
        K = 1024;
        M = 1048576;
        G = 1073741824;
        T = 1099511627776;
        P = 1125899906842624;
      };
    in
    if parsed == null then
      null
    else
      let
        multiplier = multipliers.${builtins.elemAt parsed 1};
        amount = lib.toInt (builtins.elemAt parsed 0);
      in
      if amount <= 0 || multiplier == null then null else amount * multiplier;
  aggregateMemoryMaxBytes = memoryBytes (aggregateSliceConfig.MemoryMax or "");
  aggregateMemoryHighBytes = memoryBytes (aggregateSliceConfig.MemoryHigh or "");
  engineMemoryMaxBytes = memoryBytes (engineServiceConfig.MemoryMax or "");
  engineTasksMax = engineServiceConfig.TasksMax or 0;
  # The shared slice also holds the supervisor of both children: the container
  # runtime, its monitor, and the unit helpers that start and stop them. Those
  # tasks are not part of either child's own ceiling, so the aggregate keeps a
  # reserve for them instead of leaving the slice with no headroom.
  supervisoryTaskReserve = 256;
in
{
  options.ghostship.t3code.hardening = {
    enable = lib.mkEnableOption "the verified T3 platform with a separate rootless development engine";
    sharedMounts = lib.mkOption {
      type = lib.types.attrsOf lib.types.bool;
      default = {
        "Library/ROMS" = true;
        "Projects/goship-roms" = false;
        "Downloads/PyLoad" = false;
      };
      description = "NAS directories needed by local ROM workflows; values select read-only access. Other host administration uses root SSH.";
    };
    aggregateMemoryMax = lib.mkOption {
      type = lib.types.str;
      default = "48G";
      description = ''
        Aggregate memory ceiling for the outer T3 container and the rootless
        engine under their shared slice. The ceiling is a deliberate cap on the
        pair: the children's own ceilings are not simultaneously guaranteed
        budgets, because this shared cap is what both may use together.
      '';
    };
    aggregateMemoryHigh = lib.mkOption {
      type = lib.types.str;
      default = "40G";
      description = "Aggregate memory threshold at which the shared slice starts reclaiming memory before the ceiling is reached.";
    };
    aggregateTasksMax = lib.mkOption {
      type = lib.types.ints.positive;
      default = 12544;
      description = ''
        Aggregate task ceiling for the outer T3 container and the rootless
        engine under their shared slice. It must cover the engine's ceiling, the
        container's ceiling, and a reserve for the supervisory tasks of both
        children, so the slice never runs out of tasks for the processes that
        supervise them.
      '';
    };
    containerPidsLimit = lib.mkOption {
      type = lib.types.ints.positive;
      default = 8192;
      description = "Task ceiling for the outer T3 container itself; the engine keeps its own separate ceiling.";
    };
  };

  config = {
    ghostship.t3codeDocker.enable = lib.mkDefault cfg.enable;
    assertions = [
      {
        assertion = !cfg.enable || config.ghostship.t3codeDocker.enable;
        message = "Unprivileged T3 requires the separate rootless development engine.";
      }
      {
        assertion = lib.all (path: builtins.match "[A-Za-z0-9_-]+(/[A-Za-z0-9_-]+)*" path != null) (
          builtins.attrNames cfg.sharedMounts
        );
        message = "T3 shared mounts must be explicit relative directory paths without traversal.";
      }
      # The engine manager stays where Moby expects it. Moving it out of
      # user-<UID>.slice breaks the rootless daemon's controller lookup.
      {
        assertion = !cfg.enable || !(engineServiceConfig ? Slice);
        message = "The rootless engine manager must stay in ${engineSlice}; Moby resolves its delegated controllers through /sys/fs/cgroup/user.slice/user-${engineUid}.slice.";
      }
      # One real common parent: the container service, the container itself, and
      # the engine manager all sit in the same slice.
      {
        assertion =
          !cfg.enable || (config.systemd.services.podman-t3code.serviceConfig.Slice or null) == engineSlice;
        message = "podman-t3code must join ${engineSlice} so the outer T3 container and the engine share one aggregate limit.";
      }
      {
        assertion = !cfg.enable || cgroupFlagOptions == [ "--cgroup-parent=${engineSlice}" ];
        message = "The outer T3 container must carry exactly one canonical --cgroup-parent=${engineSlice}; a bare, split, repeated, or cgroup-mode flag would change its placement.";
      }
      # The container is a sibling of the engine manager's delegated subtree,
      # never a child of it, so the engine cannot move or re-limit T3.
      {
        assertion =
          !cfg.enable || lib.all (option: !(lib.hasPrefix "--cgroup-parent=user@" option)) cgroupFlagOptions;
        message = "The outer T3 container must not be created inside the engine manager's delegated cgroup.";
      }
      {
        assertion =
          !cfg.enable
          || lib.all (
            word:
            lib.elem word [
              "cpu"
              "cpuset"
              "io"
              "memory"
              "pids"
            ]
          ) delegatedControllers;
        message = "The engine delegation must cover controllers only; it must never name the T3 unit or the shared slice.";
      }
      # Finite aggregate limits.
      {
        assertion = !cfg.enable || aggregateMemoryMaxBytes != null;
        message = "The shared slice needs a finite aggregate memory ceiling.";
      }
      {
        assertion = !cfg.enable || aggregateMemoryHighBytes != null;
        message = "The shared slice needs a finite aggregate memory threshold.";
      }
      {
        assertion =
          !cfg.enable
          || (
            aggregateMemoryHighBytes != null
            && aggregateMemoryMaxBytes != null
            && aggregateMemoryHighBytes <= aggregateMemoryMaxBytes
          );
        message = "The aggregate memory threshold must not exceed the aggregate memory ceiling.";
      }
      {
        assertion = !cfg.enable || (aggregateSliceConfig.TasksMax or 0) > 0;
        message = "The shared slice needs a finite aggregate task ceiling.";
      }
      {
        assertion =
          !cfg.enable
          ||
            (aggregateSliceConfig.TasksMax or 0)
            >= engineTasksMax + cfg.containerPidsLimit + supervisoryTaskReserve;
        message = "The aggregate task ceiling must cover the engine ceiling, the container ceiling, and the reserved supervisory tasks.";
      }
      {
        assertion =
          !cfg.enable
          || (
            engineMemoryMaxBytes != null
            && aggregateMemoryMaxBytes != null
            && aggregateMemoryMaxBytes >= engineMemoryMaxBytes
          );
        message = "The aggregate memory ceiling must not be tighter than the engine's own ceiling.";
      }
      # The engine keeps its own bounds; the aggregate only adds a shared cap.
      {
        assertion =
          !cfg.enable || (engineServiceConfig.MemoryMax or null) == config.ghostship.t3codeDocker.memoryMax;
        message = "The engine keeps its own memory ceiling; the aggregate limit must not replace it.";
      }
      {
        assertion = !cfg.enable || engineTasksMax == config.ghostship.t3codeDocker.tasksMax;
        message = "The engine keeps its own task ceiling; the aggregate limit must not replace it.";
      }
      {
        assertion =
          !cfg.enable || (engineServiceConfig.CPUQuota or null) == config.ghostship.t3codeDocker.cpuQuota;
        message = "The engine keeps its own CPU quota; the aggregate limit must not replace it.";
      }
      # The outer T3 container keeps a bounded task count of its own, and
      # exactly one canonical flag may carry it.
      {
        assertion =
          !cfg.enable || pidsLimitOptions == [ "--pids-limit=${toString cfg.containerPidsLimit}" ];
        message = "The outer T3 container must carry exactly one canonical --pids-limit=${toString cfg.containerPidsLimit}; a bare, split, or repeated flag would change its task bound.";
      }
    ];
    security.apparmor.policies.ghostship-t3code = {
      state = "complain";
      profile = builtins.readFile ./apparmor/t3code.profile;
    };
    ghostship.apps.t3code = lib.mkIf cfg.enable {
      apparmorProfile = "ghostship-t3code";
      apparmorHeartbeat = [
        "/bin/cat"
        "/proc/sys/kernel/random/boot_id"
      ];
    };
    ghostship.security = lib.mkIf cfg.enable {
      privileged_allow = lib.mkForce [ ];
      cap_add_allow.t3code = map (cap: "CAP_${cap}") (
        builtins.fromJSON (builtins.readFile ../../packages/t3code/runtime-caps.json)
      );
      socket_mount_allow = [ "/run/t3code-docker/docker.sock" ];
    };
    # One slice bounds the outer T3 container and the rootless engine together.
    # The engine manager keeps its own delegated subtree inside the same slice,
    # so the engine can never reach the T3 sibling cgroup. The legacy platform
    # keeps no shared slice at all.
    #
    # The slice ceiling is a cap on the pair, not a promise that each child
    # reaches its own ceiling: the children's maxima are not simultaneously
    # guaranteed budgets, and the aggregate task ceiling holds back a reserve
    # for the supervisory tasks of both children.
    systemd.slices = lib.mkIf cfg.enable {
      ${engineSliceKey}.sliceConfig = {
        MemoryMax = cfg.aggregateMemoryMax;
        MemoryHigh = cfg.aggregateMemoryHigh;
        TasksMax = cfg.aggregateTasksMax;
      };
    };
    systemd.services.podman-t3code.serviceConfig.Slice = lib.mkIf cfg.enable engineSlice;
  };
}
