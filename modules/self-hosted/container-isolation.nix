# Per-container network containment (#102).
#
# A containment policy states one container's network identity (network,
# subnet, address, MAC) and the directed edges it may use. The generator turns
# the policy into an nftables ruleset with the same shape as the FlareSolverr
# egress rules: one inet table and one bridge table per container, replaced in
# a single nft transaction.
#
# The policy is opt-in twice: the master switch below and the per-container
# switch. Nothing is generated, loaded or required while both are off, so the
# default host keeps exactly the rules it has today.
#
# Admission is fail-closed. A policy is refused when the container could
# change its own identity or leave the namespace it is contained in
# (privileged, or a capability outside the allowed set), when it shares a
# host namespace or runs in a pod, when it joins another network than the
# one the policy names, when its identity flags are ambiguous, or when its
# address does not belong to the network's subnet.
# The admission reads the argv the oci-containers module actually builds,
# native fields and extraOptions alike, with Podman's flag spellings.
#
# Boundaries:
# - Containment limits what a contained container may reach. It is not a
#   substitute for the perimeter: Internet exposure stays behind Cloudflare
#   Access and the host firewall.
# - Observations are evidence. A flow seen in the flow collector never becomes
#   an allow rule; it is reported as an unresolved dependency for review.
# - The repository is public. Policies name structural service names and
#   synthetic categories; coordinates and payloads stay out of the rules.
{ config, lib, pkgs, ... }:
let
  cfg = config.ghostship.containerIsolation;
  containers = config.virtualisation.oci-containers.containers;
  # Both switches must be on before a policy does anything.
  enabled = lib.filterAttrs (_: policy: cfg.enable && policy.enable) cfg.policies;

  # The arguments `podman run` will actually receive. The oci-containers module
  # emits its native fields (privileged, capabilities, networks) as their own
  # flags, then appends extraOptions; Podman's pflag accepts "--flag=value" and
  # "--flag value", and --net is an alias of --network. Admission reads this
  # argv, so a flag cannot hide in another field or another spelling.
  generatedArgv = name:
    let container = containers.${name}; in
    lib.optionals (container.privileged or false) [ "--privileged" ]
    ++ lib.mapAttrsToList (capability: _: "--cap-add=${capability}") (
      lib.filterAttrs (_: value: value == true) (container.capabilities or { })
    )
    ++ lib.mapAttrsToList (capability: _: "--cap-drop=${capability}") (
      lib.filterAttrs (_: value: value == false) (container.capabilities or { })
    )
    ++ map (network: "--network=${network}") (lib.unique (container.networks or [ ]))
    ++ (container.preRunExtraOptions or [ ])
    ++ (container.extraOptions or [ ]);

  # Values of pflag-style flags: "--flag=value" is one element, "--flag value"
  # is two. A bare flag at the end of the argv has no value and is reported as
  # an empty one, so it can never look like the expected value.
  flagValues = argv: names:
    let
      step = state: element:
        let matched = lib.findFirst (name: element == name || lib.hasPrefix "${name}=" element) null names;
        in
        if state.pending != null then
          { values = state.values ++ [ element ]; pending = null; }
        else if matched == null then
          state
        else if element == matched then
          { inherit (state) values; pending = matched; }
        else
          { values = state.values ++ [ (lib.removePrefix "${matched}=" element) ]; pending = null; };
      result = lib.foldl' step { values = [ ]; pending = null; } argv;
    in
    result.values ++ lib.optional (result.pending != null) "";

  # Constrain extraOptions instead of partially emulating Podman's global and
  # run parsers. Every accepted token carries its own value, so a label/env
  # value cannot consume the following security option. Unknown flags are
  # refused, including persistent runtime/context flags accepted after run.
  # Native OCI options are emitted by the pinned module and shell-escaped.
  allowedExtraFlags = (builtins.fromJSON (
    builtins.readFile ./container-isolation/allowed-extra-options.json
  )).allowedExtraFlags;
  canonicalExtraOptions = name:
    lib.all (element:
      let parsed = builtins.match "--([a-z][a-z0-9-]*)=(.*)" element;
      in parsed != null && lib.elem (builtins.head parsed) allowedExtraFlags
    ) (containers.${name}.extraOptions or [ ]);
  containerServiceName = name: containers.${name}.serviceName;

  # Podman normalises capability names: case is ignored and the CAP_ prefix is
  # optional. "net_raw", "CAP_NET_RAW" and "cap_net_admin" are the same caps.
  normalizeCapability = value:
    let upper = lib.toUpper value;
    in if lib.hasPrefix "CAP_" upper then lib.removePrefix "CAP_" upper else upper;
  splitCapabilities = values:
    lib.concatMap (value: map normalizeCapability (lib.splitString "," value)) values;

  # The capability baseline is explicit, never the runtime default. Podman
  # takes its default set from /etc/containers/containers.conf, which NixOS
  # writes from virtualisation.containers.containersConf and which may name
  # NET_RAW or NET_ADMIN. A contained container therefore has to drop ALL and
  # add back only what it needs, so a mutable global default cannot reach it.
  capabilityFlags = name:
    let
      added = splitCapabilities (flagValues (generatedArgv name) [ "--cap-add" ]);
      dropped = splitCapabilities (flagValues (generatedArgv name) [ "--cap-drop" ]);
      additions = added;
      removals = lib.filter (capability: capability != "ALL") dropped;
    in
    {
      dropsAll = lib.elem "ALL" dropped;
      ambiguous = lib.intersectLists additions removals;
      effective = lib.filter (capability: !(lib.elem capability removals)) additions;
    };

  # The capabilities a contained container may hold are an allowlist, not a
  # denylist: everything outside it is refused, and the refusal names the
  # capability. The list lives in one JSON file next to the policy model,
  # which the model reads too, so the two sets cannot drift apart.
  allowedCapabilities = (builtins.fromJSON (
    builtins.readFile ./container-isolation/allowed-capabilities.json
  )).allowedCapabilities;
  disallowedCapabilities = name:
    lib.filter (capability: !(lib.elem capability allowedCapabilities))
      (capabilityFlags name).effective;

  # The podman context. `podman.user` turns the unit into a rootless user
  # unit: the container then runs in that user's network namespace, which the
  # host's rules and the metadata helper do not see. `preRunExtraOptions` are
  # global flags before `run` and can select a remote or differently rooted
  # podman for the same reason. Both are refused rather than parsed.
  preRunOptions = name: (containers.${name}.preRunExtraOptions or [ ]);
  podmanUser = name: (containers.${name}.podman.user or "root");

  # Network attachments and identity, from the same argv.
  networkModes = name: flagValues (generatedArgv name) [ "--network" "--net" ];
  containerAddresses = name: flagValues (generatedArgv name) [ "--ip" ];
  containerMacs = name: map lib.toLower (flagValues (generatedArgv name) [ "--mac-address" ]);

  # Host namespaces are outside the rules. A container in the host's pid
  # namespace sees the host's processes, and one in the host's user
  # namespace acts as the host's root. The values are read with the same
  # flagValues helper as the network, so "--pid=host" and "--pid host" are
  # the same flag, and the container:/ns: forms, which name another
  # container's or a host namespace, are refused as well.
  namespaceFlags = [ "pid" "userns" "ipc" "uts" "cgroupns" ];
  isHostNamespace = value:
    let lowered = lib.toLower value;
    in
    lowered == "host" || lib.hasPrefix "container:" lowered || lib.hasPrefix "ns:" lowered;
  namespaceValues = name: flag: flagValues (generatedArgv name) [ "--${flag}" ];
  hostNamespaces = name:
    lib.concatMap
      (flag: map (value: "${flag}=${lib.toLower value}")
        (lib.filter isHostNamespace (namespaceValues name flag)))
      namespaceFlags;
  # A pod shares its namespaces between its containers, so a contained
  # container in a pod is outside the rules. Every spelling is refused.
  podNamespaces = name: flagValues (generatedArgv name) [ "--pod" ];
  isPrivileged = name:
    let
      values = lib.filter (element: element == "--privileged" || lib.hasPrefix "--privileged=" element) (generatedArgv name);
      enabled = value: value == "--privileged" || !(lib.elem (lib.removePrefix "--privileged=" value) [ "false" "0" ]);
    in
    lib.any enabled values;

  ipv4ToInt = address:
    lib.foldl' (acc: part: acc * 256 + lib.toInt part) 0 (lib.splitString "." address);
  inSubnet = address: subnet:
    let
      parts = lib.splitString "/" subnet;
      prefix = lib.head parts;
      bits = lib.toInt (lib.last parts);
      base = ipv4ToInt prefix;
      value = ipv4ToInt address;
      size = lib.foldl' (acc: _: acc * 2) 1 (lib.range 0 (32 - bits - 1));
    in value >= base && value < base + size;

  spec = pkgs.writeText "container-isolation-policy.json" (builtins.toJSON {
    version = 2;
    containers = lib.mapAttrs (
      name: policy: {
        inherit (policy) container network subnet address mac;
        dnsServer = policy.dnsServer;
        dns = policy.dns;
        ipv6 = policy.ipv6;
        publicEgress = {
          enabled = policy.publicEgress.enable;
          protocols = policy.publicEgress.protocols;
          ports = policy.publicEgress.ports;
        };
        edges = map (edge: {
          inherit (edge) peer address protocol port;
          purpose = edge.purpose;
        }) policy.edges;
        observed = map (item: {
          inherit (item) peer protocol port;
          address = item.address or "";
          category = item.category;
        }) policy.observed;
        ingress = {
          enabled = policy.ingress.enable;
          ports = map (entry: {
            inherit (entry) protocol port;
          }) policy.ingress.ports;
        };
        capabilities = (capabilityFlags policy.container).effective;
        capabilityDropsAll = (capabilityFlags policy.container).dropsAll;
        privileged = isPrivileged policy.container;
        # The namespace flags, as the argv spells them. The policy model
        # refuses a host namespace and a pod with the same rules.
        namespaces = {
          pid = namespaceValues policy.container "pid";
          userns = namespaceValues policy.container "userns";
          ipc = namespaceValues policy.container "ipc";
          uts = namespaceValues policy.container "uts";
          cgroupns = namespaceValues policy.container "cgroupns";
          pod = podNamespaces policy.container;
        };
        podman = {
          user = podmanUser policy.container;
          preRun = preRunOptions policy.container;
          extraOptions = containers.${policy.container}.extraOptions;
        };
      }
    ) enabled;
  });

  # The generator refuses a policy it cannot hold, so a broken policy fails
  # the build instead of producing rules that match nothing.
  ruleset = pkgs.runCommand "container-isolation-ruleset" { nativeBuildInputs = [ pkgs.python3 ]; } ''
    cp -r ${./container-isolation} source
    chmod -R u+w source
    cd source
    ${pkgs.python3}/bin/python3 generate-policy.py --policy ${spec} --out $out
  '';

  # The network has to carry the subnet the policy names. The check reads the
  # network's metadata, not a bridge device: netavark creates the bridge when
  # the first container attaches, so waiting for it would deadlock the first
  # boot. The policy unit fails before loading a rule when the metadata does
  # not match, and the container does not start.
  checkNetwork = pkgs.writeShellApplication {
    name = "ghostship-container-isolation-check-network";
    runtimeInputs = [ pkgs.python3 ];
    text = ''
      exec ${pkgs.python3}/bin/python3 ${./container-isolation/check-network.py} \
        --podman ${config.virtualisation.podman.package}/bin/podman "$@"
    '';
  };

  policyChecks = lib.concatLists (
    lib.mapAttrsToList (
      name: policy:
      let
        modes = networkModes policy.container;
        addresses = containerAddresses policy.container;
        macs = containerMacs policy.container;
        capabilities = capabilityFlags policy.container;
        disallowedCaps = disallowedCapabilities policy.container;
        hostNames = hostNamespaces policy.container;
        podNames = podNamespaces policy.container;
      in
      [
        {
          assertion = builtins.hasAttr policy.container containers;
          message = "Container isolation policy ${name} names the container ${policy.container}, which does not exist.";
        }
        {
          # One network, named exactly. Host, none, container: and alternate
          # attachments (":ip=", ":mac=") are refused: the policy can only
          # bind an identity on the network it names. The native networks list
          # and every extraOptions spelling are read the same way.
          assertion = builtins.length modes == 1 && lib.head modes == policy.network;
          message = "Container isolation policy ${name} needs ${policy.container} to join exactly one network, ${policy.network}, and no other attachment.";
        }
        {
          assertion = !isPrivileged policy.container;
          message = "Container isolation policy ${name} cannot contain ${policy.container}: it runs privileged.";
        }
        {
          assertion = podmanUser policy.container == "root";
          message = "Container isolation policy ${name} cannot contain ${policy.container}: it is a rootless unit for user ${podmanUser policy.container}, and the rules live in the rootful host network namespace.";
        }
        {
          assertion = canonicalExtraOptions policy.container;
          message = "Container isolation policy ${name} needs canonical allowed --flag=value extraOptions; split, unknown and runtime-context options are refused.";
        }
        {
          assertion = preRunOptions policy.container == [ ];
          message = "Container isolation policy ${name} cannot contain ${policy.container}: it passes pre-run podman flags, which can select a remote or differently rooted podman.";
        }
        {
          assertion = capabilities.dropsAll;
          message = "Container isolation policy ${name} needs ${policy.container} to drop ALL capabilities explicitly (--cap-drop=ALL or capabilities.ALL = false): the runtime default set comes from a mutable configuration file and could grant NET_RAW or NET_ADMIN.";
        }
        {
          assertion = capabilities.ambiguous == [ ];
          message = "Container isolation policy ${name} cannot contain ${policy.container}: it both adds and drops ${lib.concatStringsSep ", " capabilities.ambiguous}, so the effective set would depend on podman's ordering.";
        }
        {
          # The capability set is an allowlist: a contained container may
          # hold only the capabilities in the allowed set, and the refusal
          # names the one that is not in it. SYS_MODULE loads kernel code,
          # DAC_READ_SEARCH opens host files through open_by_handle_at,
          # SYS_PTRACE injects into a process outside the namespace, and
          # SYS_ADMIN can setns into a namespace the rules do not govern.
          assertion = disallowedCaps == [ ];
          message = "Container isolation policy ${name} cannot contain ${policy.container}: it adds ${lib.concatStringsSep ", " disallowedCaps}, which is not in the allowed capability set (${lib.concatStringsSep ", " allowedCapabilities}).";
        }
        {
          # A host namespace is outside the rules: the container would see
          # the host's processes or act as the host's root.
          assertion = hostNames == [ ];
          message = "Container isolation policy ${name} cannot contain ${policy.container}: it joins a host namespace (${lib.concatStringsSep ", " hostNames}), which is outside the rules.";
        }
        {
          # A pod shares its namespaces between its containers, so a
          # contained container in a pod is outside the rules.
          assertion = podNames == [ ];
          message = "Container isolation policy ${name} cannot contain ${policy.container}: it runs in a pod, which shares another container's namespaces and is outside the rules.";
        }
        {
          # One address, one MAC: an identity that is declared twice can be
          # overridden by the second flag.
          assertion = builtins.length addresses == 1 && lib.head addresses == policy.address;
          message = "Container isolation policy ${name} needs ${policy.container} to start with exactly one --ip=${policy.address} so the policy matches the container.";
        }
        {
          assertion = builtins.length macs == 1 && lib.head macs == lib.toLower policy.mac;
          message = "Container isolation policy ${name} needs ${policy.container} to start with exactly one --mac-address=${policy.mac} so the policy matches the container.";
        }
        {
          assertion = inSubnet policy.address policy.subnet;
          message = "Container isolation policy ${name} needs an address inside ${policy.subnet}, the subnet of ${policy.network}.";
        }
        {
          assertion = inSubnet policy.dnsServer policy.subnet;
          message = "Container isolation policy ${name} needs a resolver inside ${policy.subnet}, the subnet of ${policy.network}.";
        }
      ]
    )
    enabled
  );

  policyServices = lib.mapAttrs' (
    name: policy:
    lib.nameValuePair "ghostship-container-isolation-${name}" {
      description = "Network containment policy for ${policy.container}";
      wantedBy = [ "multi-user.target" ];
      # The network definition exists at boot; the bridge does not.
      wants = [ "init-ghostship-net.service" ];
      after = [ "network-pre.target" "init-ghostship-net.service" ];
      # Start order: the policy is loaded before the container starts. Stop
      # order follows from the container's bindsTo and after below: the
      # container is stopped before the filter is removed.
      before = [ "${containerServiceName policy.container}.service" ];
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
        ExecStartPre = "${checkNetwork}/bin/ghostship-container-isolation-check-network --network ${policy.network} --subnet ${policy.subnet}";
        ExecStart = "${pkgs.nftables}/bin/nft -f ${ruleset}/${name}.nft";
        ExecStop = "${pkgs.nftables}/bin/nft -f ${ruleset}/${name}-unload.nft";
      };
    }
  ) enabled;

  # The container may not start without its policy: a failed or missing
  # policy unit keeps the workload down instead of running uncontained.
  containerServices = lib.mapAttrs' (
    name: policy:
    lib.nameValuePair (containerServiceName policy.container) {
      requires = [ "ghostship-container-isolation-${name}.service" ];
      after = [ "ghostship-container-isolation-${name}.service" ];
      bindsTo = [ "ghostship-container-isolation-${name}.service" ];
    }
  ) enabled;
in
{
  options.ghostship.containerIsolation = {
    enable = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Master switch for per-container network containment. Off by default: no rules are generated, loaded or required.";
    };

    policies = lib.mkOption {
      type = lib.types.attrsOf (lib.types.submodule ({ name, ... }: {
        options = {
          enable = lib.mkOption {
            type = lib.types.bool;
            default = false;
            description = "Enable this container's containment policy. Requires ghostship.containerIsolation.enable.";
          };
          container = lib.mkOption {
            type = lib.types.str;
            description = "Name of the OCI container this policy contains.";
          };
          network = lib.mkOption {
            type = lib.types.str;
            default = "ghostship_net";
            description = "Podman network the container joins, and the only one it may join.";
          };
          subnet = lib.mkOption {
            type = lib.types.str;
            description = "IPv4 subnet of that network, in CIDR form. The container address and the resolver have to be inside it.";
          };
          address = lib.mkOption {
            type = lib.types.str;
            description = "IPv4 address of the container on that network. The container must start with exactly this --ip.";
          };
          mac = lib.mkOption {
            type = lib.types.str;
            description = "MAC address of the container. The container must start with exactly this --mac-address.";
          };
          dnsServer = lib.mkOption {
            type = lib.types.str;
            description = "Resolver the container may query over UDP and TCP.";
          };
          dns = lib.mkOption {
            type = lib.types.bool;
            default = true;
            description = "Allow DNS to the declared resolver.";
          };
          ipv6 = lib.mkOption {
            type = lib.types.enum [ "deny" "allow" ];
            default = "deny";
            description = "Whether the container may use IPv6 at all.";
          };
          publicEgress = {
            enable = lib.mkOption {
              type = lib.types.bool;
              default = false;
              description = "Allow the container to reach public addresses. Off by default: public egress is a decision, not a default.";
            };
            protocols = lib.mkOption {
              type = lib.types.listOf (lib.types.enum [ "tcp" "udp" ]);
              default = [ ];
              description = "Protocols the public egress may use.";
            };
            ports = lib.mkOption {
              type = lib.types.listOf lib.types.port;
              default = [ ];
              description = "Ports the public egress may use.";
            };
          };
          edges = lib.mkOption {
            type = lib.types.listOf (lib.types.submodule ({ name, ... }: {
              options = {
                peer = lib.mkOption {
                  type = lib.types.str;
                  description = "Structural name of the peer service.";
                };
                address = lib.mkOption {
                  type = lib.types.str;
                  description = "IPv4 address of the peer on the container's network.";
                };
                protocol = lib.mkOption {
                  type = lib.types.enum [ "tcp" "udp" ];
                  default = "tcp";
                };
                port = lib.mkOption {
                  type = lib.types.port;
                };
                purpose = lib.mkOption {
                  type = lib.types.str;
                  default = "";
                  description = "Why this edge exists. Categories only: no URLs and no addresses in a public repository.";
                };
              };
            }));
            default = [ ];
            description = "Directed edges the container may use. Everything else it sends is denied.";
          };
          observed = lib.mkOption {
            type = lib.types.listOf (lib.types.submodule ({ name, ... }: {
              options = {
                peer = lib.mkOption {
                  type = lib.types.str;
                  description = "Structural name of the observed peer.";
                };
                address = lib.mkOption {
                  type = lib.types.str;
                  default = "";
                  description = "Address of the observed peer, when it is known.";
                };
                protocol = lib.mkOption {
                  type = lib.types.enum [ "tcp" "udp" ];
                  default = "tcp";
                };
                port = lib.mkOption {
                  type = lib.types.port;
                };
                category = lib.mkOption {
                  type = lib.types.str;
                  default = "";
                  description = "Category of the observation. Evidence only: it never becomes an allow rule.";
                };
              };
            }));
            default = [ ];
            description = "Observed edges kept as evidence. They are reported as unresolved dependencies and never become rules.";
          };
          ingress = {
            enable = lib.mkOption {
              type = lib.types.bool;
              default = false;
              description = "Also restrict what may reach the container. Off by default: it needs connection tracking in the bridge family.";
            };
            ports = lib.mkOption {
              type = lib.types.listOf (lib.types.submodule ({ name, ... }: {
                options = {
                  protocol = lib.mkOption {
                    type = lib.types.enum [ "tcp" "udp" ];
                    default = "tcp";
                  };
                  port = lib.mkOption {
                    type = lib.types.port;
                  };
                };
              }));
              default = [ ];
              description = "Ports on the container that stay reachable while the ingress is restricted.";
            };
          };
        };
      }));
      default = { };
      description = "Containment policies by policy name. Every policy is off until it is enabled here and the master switch is on.";
    };
  };

  config = {
    assertions = [
      {
        assertion = builtins.all (policy: cfg.enable || !policy.enable) (lib.attrValues cfg.policies);
        message = "ghostship.containerIsolation.enable must be true before any container policy is enabled.";
      }
      {
        assertion = enabled == { } || config.virtualisation.oci-containers.backend == "podman";
        message = "Container isolation policies only work with the podman backend: the admission parses podman's flags.";
      }
    ] ++ policyChecks;

    systemd.services = policyServices // containerServices;
  };
}
