let
  flake = builtins.getFlake (toString ../.);
  base = flake.nixosConfigurations.chill-penguin;
  inherit (base.pkgs) lib;

  # Synthetic identity, container and peer. The test never touches a live
  # container: the candidate is a scratch image declared here.
  address = "10.89.0.42";
  mac = "02:00:00:00:00:42";
  subnet = "10.89.0.0/24";
  identity = [ "--ip=${address}" "--mac-address=${mac}" "--cap-drop=ALL" ];
  appPolicy = {
    enable = true;
    container = "candidate-app";
    network = "ghostship_net";
    inherit address mac subnet;
    dnsServer = "10.89.0.1";
    edges = [
      {
        peer = "peer-service";
        address = "10.89.0.43";
        protocol = "tcp";
        port = 8443;
        purpose = "service api";
      }
    ];
  };
  extend = modules: base.extendModules { inherit modules; };
  policyModule = { ghostship.containerIsolation.policies.candidate = appPolicy; };
  switch = { ghostship.containerIsolation.enable = true; };
  # A container that is only declared here, so nothing in another module can
  # mask which field the admission read.
  appEntry = [
    {
      ghostship.apps.candidate-app = {
        name = "Candidate";
        group = "Utilities";
        description = "Containment test container";
        icon = "sh-plex";
        order = 999;
        apparmorProfile = "ghostship-candidate-app";
      };
    }
    {
      security.apparmor.policies.ghostship-candidate-app = {
        state = "complain";
        profile = "profile ghostship-candidate-app { }";
      };
    }
  ];
  # Native oci-containers fields: networks, privileged, capabilities.
  nativeApp = fields: {
    virtualisation.oci-containers.containers.candidate-app = {
      image = "scratch";
      extraOptions = identity;
    } // fields;
  };
  # The same container described through extraOptions only.
  cliApp = options: {
    virtualisation.oci-containers.containers.candidate-app = {
      image = "scratch";
      extraOptions = options;
    };
  };
  withNative = fields: appEntry ++ [ (nativeApp fields) switch policyModule ];
  withCli = options: appEntry ++ [ (cliApp options) switch policyModule ];
  candidate = extend (withNative { networks = [ "ghostship_net" ]; });
  failures = modules: map (a: a.message) (
    builtins.filter (a: !a.assertion) (extend modules).config.assertions
  );
  fails = modules: message: builtins.elem message (failures modules);
  accepted = modules: failures modules == [ ];

  privileged = "Container isolation policy candidate cannot contain candidate-app: it runs privileged.";
  # The allowed capability set is one list. The refusal message names the
  # capability that is not in it, so the message is part of the contract: the
  # list below is checked against the one the module reads.
  allowedCapabilities = [ "CHOWN" "DAC_OVERRIDE" "FOWNER" "FSETID" "KILL" "NET_BIND_SERVICE" "SETFCAP" "SETGID" "SETPCAP" "SETUID" "SYS_CHROOT" ];
  caps = names: "Container isolation policy candidate cannot contain candidate-app: it adds ${lib.concatStringsSep ", " names}, which is not in the allowed capability set (${lib.concatStringsSep ", " allowedCapabilities}).";
  hostNamespace = flags: "Container isolation policy candidate cannot contain candidate-app: it joins a host namespace (${lib.concatStringsSep ", " flags}), which is outside the rules.";
  podNamespace = "Container isolation policy candidate cannot contain candidate-app: it runs in a pod, which shares another container's namespaces and is outside the rules.";
  network = "Container isolation policy candidate needs candidate-app to join exactly one network, ghostship_net, and no other attachment.";
  ip = "Container isolation policy candidate needs candidate-app to start with exactly one --ip=${address} so the policy matches the container.";
  rootless = "Container isolation policy candidate cannot contain candidate-app: it is a rootless unit for user nobody, and the rules live in the rootful host network namespace.";
  prerun = "Container isolation policy candidate cannot contain candidate-app: it passes pre-run podman flags, which can select a remote or differently rooted podman.";
  macMessage = "Container isolation policy candidate needs candidate-app to start with exactly one --mac-address=${mac} so the policy matches the container.";
  dropAll = "Container isolation policy candidate needs candidate-app to drop ALL capabilities explicitly (--cap-drop=ALL or capabilities.ALL = false): the runtime default set comes from a mutable configuration file and could grant NET_RAW or NET_ADMIN.";
  ambiguous = "Container isolation policy candidate cannot contain candidate-app: it both adds and drops NET_RAW, so the effective set would depend on podman's ordering.";
  defaultCaps = capabilities: {
    virtualisation.containers.containersConf.settings.containers.default_capabilities = capabilities;
  };
  bareIdentity = [ "--network=ghostship_net" "--ip=${address}" "--mac-address=${mac}" ];
in
# Containment is off by default: no policy unit, no rules, no requirement.
assert base.config.ghostship.containerIsolation.enable == false;
assert base.config.ghostship.containerIsolation.policies == { };
assert !(base.config.systemd.services ? ghostship-container-isolation-candidate);
# A policy that is enabled without the master switch is refused.
assert fails (withNative { networks = [ "ghostship_net" ]; } ++ [ { ghostship.containerIsolation.enable = lib.mkForce false; } ])
  "ghostship.containerIsolation.enable must be true before any container policy is enabled.";
# The enabled candidate evaluates without a failing assertion.
assert accepted (withNative { networks = [ "ghostship_net" ]; });
# The policy unit exists and the container may not start without it.
assert candidate.config.systemd.services ? ghostship-container-isolation-candidate;
assert builtins.elem "ghostship-container-isolation-candidate.service"
  candidate.config.systemd.services.podman-candidate-app.requires;
assert builtins.elem "ghostship-container-isolation-candidate.service"
  candidate.config.systemd.services.podman-candidate-app.after;
assert builtins.elem "ghostship-container-isolation-candidate.service"
  candidate.config.systemd.services.podman-candidate-app.bindsTo;
assert lib.hasInfix "nft"
  candidate.config.systemd.services.ghostship-container-isolation-candidate.serviceConfig.ExecStart;
# The policy is loaded before the container starts and the container is stopped
# before the filter is removed: the policy unit never waits behind the
# container it contains.
assert builtins.elem "podman-candidate-app.service"
  candidate.config.systemd.services.ghostship-container-isolation-candidate.before;
assert !(builtins.elem "podman-candidate-app.service"
  candidate.config.systemd.services.ghostship-container-isolation-candidate.after);
# The load-time gate reads the network metadata, not a bridge device, so the
# first boot cannot deadlock waiting for a bridge netavark creates later.
assert lib.hasInfix "check-network"
  candidate.config.systemd.services.ghostship-container-isolation-candidate.serviceConfig.ExecStartPre;
assert lib.hasInfix "--network ghostship_net"
  candidate.config.systemd.services.ghostship-container-isolation-candidate.serviceConfig.ExecStartPre;

# --- native oci-containers fields -------------------------------------------
# These reach the argv outside extraOptions; an admission that only read
# extraOptions would accept every one of them.
assert fails (withNative { networks = [ "ghostship_net" ]; privileged = true; }) privileged;
assert fails (withNative { networks = [ "ghostship_net" ]; capabilities.NET_ADMIN = true; }) (caps [ "NET_ADMIN" ]);
assert fails (withNative { networks = [ "ghostship_net" ]; capabilities.NET_RAW = true; }) (caps [ "NET_RAW" ]);
assert fails (withNative { networks = [ "ghostship_net" ]; capabilities.ALL = true; }) (caps [ "ALL" ]);
assert fails (withNative { networks = [ "host" ]; }) network;
assert fails (withNative { networks = [ "ghostship_net" "host" ]; }) network;
assert fails (withNative { networks = [ "other_net" ]; }) network;
assert fails (withNative { networks = [ "ghostship_net:ip=${address}" ]; }) network;
assert fails (withNative { networks = [ ]; }) network;
# The native fields are understood, not merely rejected.
assert accepted (withNative { networks = [ "ghostship_net" ]; capabilities.NET_RAW = false; });

# --- the podman context -----------------------------------------------------
# A rootless user unit or a pre-run global flag runs the container somewhere
# the host's rules and the metadata helper do not see.
assert fails (withNative { networks = [ "ghostship_net" ]; podman.user = "nobody"; } ++ [ { users.users.nobody.linger = false; } ]) rootless;
assert fails (withNative { networks = [ "ghostship_net" ]; preRunExtraOptions = [ "--remote" "--url=unix:///run/example-podman.sock" ]; }) prerun;
assert fails (withNative { networks = [ "ghostship_net" ]; preRunExtraOptions = [ "--root" "/run/example" ]; }) prerun;
# The canonical rootful context stays accepted.
assert accepted (withNative { networks = [ "ghostship_net" ]; podman.user = "root"; });
assert accepted (withNative { networks = [ "ghostship_net" ]; preRunExtraOptions = [ ]; });

# --- every accepted CLI spelling --------------------------------------------
assert accepted (withCli (identity ++ [ "--network=ghostship_net" ]));
assert fails (withCli (identity ++ [ "--network=ghostship_net" "--net=host" ])) network;
assert fails (withCli (identity ++ [ "--network=ghostship_net" "--net" "host" ])) network;
assert fails (withCli (identity ++ [ "--network=ghostship_net" "--network" "host" ])) network;
assert fails (withCli (identity ++ [ "--network=ghostship_net" "--network=other_net" ])) network;
assert fails (withCli (identity ++ [ "--network=ghostship_net:ip=${address}" ])) network;
assert fails (withCli (identity ++ [ "--network=ghostship_net" "--privileged=true" ])) privileged;
assert accepted (withCli (identity ++ [ "--network=ghostship_net" "--privileged=false" ]));
# --- the capability baseline is explicit ------------------------------------
# Podman's default set comes from /etc/containers/containers.conf, which NixOS
# writes from the containersConf option and which may name NET_RAW. A policy
# is only accepted when the container drops ALL, so the configured default
# cannot reach it.
assert fails (withCli bareIdentity) dropAll;
assert fails (withCli bareIdentity ++ [ (defaultCaps [ "NET_RAW" ]) ]) dropAll;
assert accepted (withNative { networks = [ "ghostship_net" ]; } ++ [ (defaultCaps [ "NET_RAW" ]) ]);
assert accepted (withNative { networks = [ "ghostship_net" ]; } ++ [ (defaultCaps [ "NET_ADMIN" ]) ]);
assert accepted (withCli bareIdentity ++ [ { virtualisation.oci-containers.containers.candidate-app.capabilities.ALL = false; } ]);
# Capability names are normalised the way podman normalises them.
assert fails (withCli (identity ++ [ "--network=ghostship_net" "--cap-add=net_raw" ])) (caps [ "NET_RAW" ]);
assert fails (withCli (identity ++ [ "--network=ghostship_net" "--cap-add" "CAP_NET_ADMIN" ])) (caps [ "NET_ADMIN" ]);
assert fails (withCli (identity ++ [ "--network=ghostship_net" "--cap-add=cap_net_raw" ])) (caps [ "NET_RAW" ]);
assert fails (withCli (identity ++ [ "--network=ghostship_net" "--cap-add=NET_ADMIN,NET_RAW" ])) (caps [ "NET_ADMIN" "NET_RAW" ]);
assert fails (withCli (identity ++ [ "--network=ghostship_net" "--cap-add=ALL" ])) (caps [ "ALL" ]);
# CAP_SYS_ADMIN enters any network namespace whose handle the container is
# given, which is outside the rules: it is refused in every spelling.
assert fails (withCli (identity ++ [ "--network=ghostship_net" "--cap-add=SYS_ADMIN" ])) (caps [ "SYS_ADMIN" ]);
assert fails (withCli (identity ++ [ "--network=ghostship_net" "--cap-add" "SYS_ADMIN" ])) (caps [ "SYS_ADMIN" ]);
assert fails (withCli (identity ++ [ "--network=ghostship_net" "--cap-add=sys_admin" ])) (caps [ "SYS_ADMIN" ]);
assert fails (withCli (identity ++ [ "--network=ghostship_net" "--cap-add=CAP_SYS_ADMIN" ])) (caps [ "SYS_ADMIN" ]);
assert fails (withCli (identity ++ [ "--network=ghostship_net" "--cap-add=cap_sys_admin" ])) (caps [ "SYS_ADMIN" ]);
assert fails (withCli bareIdentity ++ [ { virtualisation.oci-containers.containers.candidate-app.capabilities.SYS_ADMIN = true; } ]) dropAll;
assert fails (withNative { networks = [ "ghostship_net" ]; capabilities.SYS_ADMIN = true; }) (caps [ "SYS_ADMIN" ]);
# The needed-capability positive stays: drop ALL, add back only what is used.
assert accepted (withCli (identity ++ [ "--network=ghostship_net" "--cap-add=NET_BIND_SERVICE" "--cap-add=CHOWN" ]));
assert accepted (withNative { networks = [ "ghostship_net" ]; capabilities = { NET_RAW = false; SYS_ADMIN = false; }; });
assert fails (withCli bareIdentity ++ [ { virtualisation.oci-containers.containers.candidate-app.capabilities.NET_RAW = true; } ]) dropAll;
assert fails (withCli (identity ++ [ "--network=ghostship_net" "--cap-add=NET_RAW" ])) (caps [ "NET_RAW" ]);
assert accepted (withCli (identity ++ [ "--network=ghostship_net" "--cap-add=net_bind_service" ]));
assert accepted (withCli (identity ++ [ "--network=ghostship_net" "--cap-drop=ALL" ]));
assert accepted (withNative { networks = [ "ghostship_net" ]; capabilities.NET_RAW = false; });
assert fails (withCli (identity ++ [ "--network=ghostship_net" "--cap-add=NET_RAW" "--cap-drop=NET_RAW" ])) ambiguous;
# --- the capability set is an allowlist --------------------------------------
# The contained container may hold only the capabilities in the allowed set.
# Everything else is refused and the message names it, so a refused policy
# says which capability has to go.
assert fails (withCli (identity ++ [ "--network=ghostship_net" "--cap-add=SYS_MODULE" ])) (caps [ "SYS_MODULE" ]);
assert fails (withCli (identity ++ [ "--network=ghostship_net" "--cap-add=sys_ptrace" ])) (caps [ "SYS_PTRACE" ]);
assert fails (withCli (identity ++ [ "--network=ghostship_net" "--cap-add=CAP_DAC_READ_SEARCH" ])) (caps [ "DAC_READ_SEARCH" ]);
assert fails (withCli (identity ++ [ "--network=ghostship_net" "--cap-add" "BPF" ])) (caps [ "BPF" ]);
assert fails (withNative { networks = [ "ghostship_net" ]; capabilities.SYS_RAWIO = true; }) (caps [ "SYS_RAWIO" ]);
assert fails (withCli (identity ++ [ "--network=ghostship_net" "--cap-add=NET_BIND_SERVICE,PERFMON" ])) (caps [ "PERFMON" ]);
# The capabilities inside the set are admitted, in podman's own spellings.
assert accepted (withCli (identity ++ [ "--network=ghostship_net" "--cap-add=NET_BIND_SERVICE" ]));
assert accepted (withCli (identity ++ [ "--network=ghostship_net" "--cap-add=cap_chown,setuid,SETGID" ]));
assert accepted (withCli (identity ++ [ "--network=ghostship_net" ]));
# --- host namespaces ---------------------------------------------------------
# A contained container may not share a host namespace. The values are read
# with the same helper as the network, so "--pid=host" and "--pid host" are
# the same flag, and the container:/ns: forms are refused as well.
assert fails (withCli (identity ++ [ "--network=ghostship_net" "--pid=host" ])) (hostNamespace [ "pid=host" ]);
assert fails (withCli (identity ++ [ "--network=ghostship_net" "--pid" "host" ])) (hostNamespace [ "pid=host" ]);
assert fails (withCli (identity ++ [ "--network=ghostship_net" "--userns=host" ])) (hostNamespace [ "userns=host" ]);
assert fails (withCli (identity ++ [ "--network=ghostship_net" "--ipc=container:other" ])) (hostNamespace [ "ipc=container:other" ]);
assert fails (withCli (identity ++ [ "--network=ghostship_net" "--uts=ns:/proc/1/ns/uts" ])) (hostNamespace [ "uts=ns:/proc/1/ns/uts" ]);
assert fails (withCli (identity ++ [ "--network=ghostship_net" "--cgroupns=host" ])) (hostNamespace [ "cgroupns=host" ]);
# A pod shares its namespaces between its containers, so a contained
# container in a pod is outside the rules: every spelling is refused.
assert fails (withCli (identity ++ [ "--network=ghostship_net" "--pod=mypod" ])) podNamespace;
assert fails (withCli (identity ++ [ "--network=ghostship_net" "--pod" "mypod" ])) podNamespace;
assert fails (withCli (identity ++ [ "--network=ghostship_net" "--pod" ])) podNamespace;
# The private and the automatic namespace stay admitted, and a container
# that names no namespace at all stays admitted.
assert accepted (withCli (identity ++ [ "--network=ghostship_net" "--userns=auto" ]));
assert accepted (withCli (identity ++ [ "--network=ghostship_net" "--pid=private" ]));
assert accepted (withCli (identity ++ [ "--network=ghostship_net" ]));
# Split identity flags are read like joined ones.
assert accepted (withCli [ "--network=ghostship_net" "--ip" address "--mac-address" mac "--cap-drop=ALL" ]);
assert fails (withCli [ "--network=ghostship_net" "--ip" address "--mac-address" mac "--ip" "10.89.0.44" ]) ip;
assert fails (withCli [ "--network=ghostship_net" "--ip" address "--mac-address" mac "--mac-address=02:00:00:00:00:44" ]) macMessage;
# The identity has to be the one the container starts with.
assert fails (withCli [ "--network=ghostship_net" "--mac-address=${mac}" ]) ip;
assert fails (withCli [ "--network=ghostship_net" "--ip=${address}" ]) macMessage;
# The address and the resolver belong to the network the policy names.
assert fails (withNative { networks = [ "ghostship_net" ]; } ++ [ { ghostship.containerIsolation.policies.candidate = lib.mkForce (appPolicy // { address = "10.89.7.42"; }); } ])
  "Container isolation policy candidate needs an address inside ${subnet}, the subnet of ghostship_net.";
assert fails (withNative { networks = [ "ghostship_net" ]; } ++ [ { ghostship.containerIsolation.policies.candidate = lib.mkForce (appPolicy // { dnsServer = "10.89.7.1"; }); } ])
  "Container isolation policy candidate needs a resolver inside ${subnet}, the subnet of ghostship_net.";
true
