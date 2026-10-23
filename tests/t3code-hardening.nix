let
  flake = builtins.getFlake (toString ../.);
  base = flake.nixosConfigurations.chill-penguin;
  inherit (base.pkgs) lib;
  candidate =
    (base.extendModules {
      modules = [ { ghostship.t3code.hardening.enable = true; } ];
    }).config;
  legacy = base.config;
  runtime = candidate.virtualisation.oci-containers.containers.t3code;
  has = value: builtins.elem value runtime.extraOptions;
  service = candidate.systemd.services.podman-t3code;
  engineUid = toString candidate.ghostship.t3codeDocker.uid;
  engineSlice = "user-${engineUid}.slice";
  engineManager = "user@${engineUid}";
  engineService = candidate.systemd.services.${engineManager};
  aggregateSlice = candidate.systemd.slices."user-${engineUid}".sliceConfig;
  containerPidsLimit = candidate.ghostship.t3code.hardening.containerPidsLimit;
  legacyRuntime = legacy.virtualisation.oci-containers.containers.t3code;
  legacyHas = value: builtins.elem value legacyRuntime.extraOptions;
  # Every module assertion must hold, including the aggregate containment ones.
  failingAssertions = map (a: a.message) (builtins.filter (a: !a.assertion) candidate.assertions);
  # Focused checks: each broken candidate must be rejected by the module.
  failures =
    extra:
    map (a: a.message) (
      builtins.filter (a: !a.assertion)
        (base.extendModules {
          modules = [
            { ghostship.t3code.hardening.enable = true; }
            extra
          ];
        }).config.assertions
    );
  rejects = needle: messages: builtins.any (message: lib.hasInfix needle message) messages;
  # Every spelling that could move the container or change its task bound has
  # to be rejected: the inline form, the split form, the bare token, a
  # repeated flag, and the cgroup mode, namespace, and raw setting flags.
  withOptions = options: {
    virtualisation.oci-containers.containers.t3code.extraOptions = lib.mkForce (
      runtime.extraOptions ++ options
    );
  };
  hiddenOption = prefix: failures {
    virtualisation.oci-containers.containers.t3code.extraOptions = lib.mkForce (
      lib.concatMap (option: lib.optional (lib.hasPrefix prefix option) "--label" ++ [ option ]) runtime.extraOptions
    );
  };
  conflictingParent = failures (withOptions [ "--cgroup-parent=other.slice" ]);
  conflictingPidsLimit = failures (withOptions [ "--pids-limit=-1" ]);
  splitParent = failures (withOptions [
    "--cgroup-parent"
    "other.slice"
  ]);
  splitPidsLimit = failures (withOptions [
    "--pids-limit"
    "-1"
  ]);
  splitPidsLimitBounded = failures (withOptions [
    "--pids-limit"
    "1"
  ]);
  bareParent = failures (withOptions [ "--cgroup-parent" ]);
  barePidsLimit = failures (withOptions [ "--pids-limit" ]);
  cgroupMode = failures (withOptions [ "--cgroups=disabled" ]);
  cgroupNamespace = failures (withOptions [ "--cgroupns=host" ]);
  rawCgroupSetting = failures (withOptions [ "--cgroup-conf=pids.max=1" ]);
  # The runtime has no alias for these flags, so this spelling is only a
  # near miss; the module must not rely on the runtime rejecting it.
  aliasShaped = failures (withOptions [ "--cgroup-par=other.slice" ]);
  # An aggregate ceiling without the supervisory reserve leaves the slice with
  # no headroom for the processes that supervise both children.
  noSupervisoryHeadroom = failures {
    ghostship.t3code.hardening.aggregateTasksMax =
      engineService.serviceConfig.TasksMax + containerPidsLimit;
  };
in
assert rejects "canonical --flag=value" (hiddenOption "--cgroup-parent=");
assert rejects "canonical --flag=value" (hiddenOption "--pids-limit=");
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
# The engine manager stays in the slice Moby hardcodes; the shared slice is the
# only parent that can hold the engine and the outer T3 container together.
assert !(engineService.serviceConfig ? Slice);
assert service.serviceConfig.Slice == engineSlice;
assert aggregateSlice.MemoryMax == "48G";
assert aggregateSlice.MemoryHigh == "40G";
# The aggregate task ceiling covers both children plus their supervisors.
assert aggregateSlice.TasksMax == 12544;
assert aggregateSlice.TasksMax >= engineService.serviceConfig.TasksMax + containerPidsLimit + 256;
# The container itself, not only conmon, must be bounded by the shared slice.
assert has "--cgroup-parent=${engineSlice}";
assert has "--pids-limit=8192";
assert !(has "--pids-limit=-1");
# The container is a sibling of the engine's delegated subtree, never a child.
assert lib.all (option: !(lib.hasPrefix "--cgroup-parent=user@" option)) runtime.extraOptions;
# The engine keeps its own bounds; the aggregate limit only adds a shared cap.
assert engineService.serviceConfig.MemoryMax == candidate.ghostship.t3codeDocker.memoryMax;
assert engineService.serviceConfig.CPUQuota == candidate.ghostship.t3codeDocker.cpuQuota;
assert engineService.serviceConfig.TasksMax == candidate.ghostship.t3codeDocker.tasksMax;
# The module assertions must all hold for this candidate.
assert failingAssertions == [ ];
# A conflicting parent, a conflicting task bound, and an aggregate ceiling
# without supervisory headroom must each be rejected, in every spelling.
assert rejects "exactly one canonical --cgroup-parent" conflictingParent;
assert rejects "exactly one canonical --cgroup-parent" splitParent;
assert rejects "exactly one canonical --cgroup-parent" bareParent;
assert rejects "exactly one canonical --cgroup-parent" cgroupMode;
assert rejects "exactly one canonical --cgroup-parent" cgroupNamespace;
assert rejects "exactly one canonical --cgroup-parent" rawCgroupSetting;
assert rejects "exactly one canonical --cgroup-parent" aliasShaped;
assert rejects "exactly one canonical --pids-limit" conflictingPidsLimit;
assert rejects "exactly one canonical --pids-limit" splitPidsLimit;
assert rejects "exactly one canonical --pids-limit" splitPidsLimitBounded;
assert rejects "exactly one canonical --pids-limit" barePidsLimit;
assert rejects "reserved supervisory tasks" noSupervisoryHeadroom;
# The legacy platform keeps its unbounded container and no shared slice.
assert !(legacy.systemd.slices ? "user-${engineUid}");
assert !(legacy.systemd.services ? engineManager);
assert (legacy.systemd.services.podman-t3code.serviceConfig.Slice or null) == null;
assert legacyHas "--pids-limit=-1";
assert !(legacyHas "--cgroup-parent=${engineSlice}");
true
