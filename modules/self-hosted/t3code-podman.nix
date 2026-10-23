{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.ghostship.t3codePodman;
  user = "t3code-podman";
  uid = toString cfg.uid;
  state = "/var/lib/t3code-podman";
  root = "/run/t3code-podman-rootfs";
  runtime = "/run/user/${uid}";
  workspace = config.ghostship.agentHost.workspacePath;
  worktrees = "/srv/apps/t3code/home/.t3/worktrees";
  graphRoot = "${state}/${if cfg.candidate then "candidate" else "storage"}";
  containersConfig = (pkgs.formats.toml { }).generate "t3code-podman.conf" {
    containers = {
      dns_servers = cfg.dns;
      log_driver = "k8s-file";
      log_size_max = 10485760;
    };
    engine = {
      cgroup_manager = "systemd";
      conmon_path = [ "${pkgs.conmon}/bin/conmon" ];
      events_logger = "file";
      runtime = "crun";
      runtimes.crun = [ "${pkgs.crun}/bin/crun" ];
      helper_binaries_dir = [
        "${pkgs.podman}/libexec/podman"
        "${pkgs.podman.passthru.helpersBin}/bin"
      ];
    };
    network = {
      network_backend = "netavark";
      default_rootless_network_cmd = "slirp4netns";
      default_subnet = "172.28.0.0/16";
    };
  };
  storageConfig = (pkgs.formats.toml { }).generate "t3code-podman-storage.conf" {
    storage = {
      driver = "overlay";
      runroot = "${runtime}/containers";
      graphroot = graphRoot;
      rootless_storage_path = graphRoot;
      options.overlay.mount_program = "${pkgs.fuse-overlayfs}/bin/fuse-overlayfs";
    };
  };
  registriesConfig = pkgs.writeText "t3code-podman-registries.conf" ''
    unqualified-search-registries = ["docker.io"]
    short-name-mode = "enforcing"
  '';
  busConfig = pkgs.writeText "t3code-podman-bus.conf" ''
    <busconfig>
      <type>session</type>
      <listen>unix:path=${runtime}/bus</listen>
      <auth>EXTERNAL</auth>
      <policy context="default">
        <allow user="${user}"/>
        <allow own="*"/>
        <allow send_destination="*" eavesdrop="true"/>
        <allow eavesdrop="true"/>
      </policy>
    </busconfig>
  '';
  # A separate unit path prevents this manager from starting ordinary host user
  # services. It has a real session bus for Podman's systemd cgroup driver.
  units = pkgs.runCommand "t3code-podman-user-units" { } ''
    mkdir -p $out
    cp ${pkgs.systemd}/example/systemd/user/{basic.target,sockets.target,paths.target,timers.target,shutdown.target,exit.target,systemd-exit.service,app.slice,session.slice,background.slice} $out/
    cat > $out/default.target <<'EOF'
    [Unit]
    Description=Dedicated T3 Podman manager
    Requires=basic.target
    Wants=dbus.socket podman.service
    After=basic.target
    EOF
    cat > $out/dbus.socket <<'EOF'
    [Socket]
    ListenStream=%t/bus
    SocketMode=0600
    EOF
    cat > $out/dbus.service <<'EOF'
    [Unit]
    Requires=dbus.socket
    After=dbus.socket
    [Service]
    StandardOutput=inherit
    StandardError=inherit
    ExecStart=${pkgs.dbus}/bin/dbus-daemon --nofork --nopidfile --systemd-activation --address=systemd: --config-file=${busConfig}
    EOF
    cat > $out/podman.service <<'EOF'
    [Unit]
    Requires=dbus.socket
    After=dbus.socket
    [Service]
    Type=exec
    ExecStartPre=${pkgs.python3}/bin/python ${../../packages/t3code/dev-engine/check-helpers.py} ${containersConfig}
    ExecStartPre=${pkgs.coreutils}/bin/mkdir -p ${runtime}/podman
    StandardOutput=inherit
    StandardError=inherit
    Environment=PATH=/run/wrappers/bin:${
      lib.makeBinPath [
        pkgs.bash
        # Dedicated manager and runtime share the private session bus.
        pkgs.systemd
        pkgs.podman
        pkgs.crun
        pkgs.conmon
        pkgs.netavark
        pkgs.aardvark-dns
        pkgs.slirp4netns
        pkgs.fuse-overlayfs
        pkgs.iproute2
        pkgs.iptables
        pkgs.coreutils
        pkgs.util-linux
        pkgs.gnugrep
        pkgs.gnused
        pkgs.getent
      ]
    }
    Environment=HOME=${state}/home
    Environment=CONTAINERS_CONF=${containersConfig}
    Environment=CONTAINERS_STORAGE_CONF=${storageConfig}
    Environment=CONTAINERS_REGISTRIES_CONF=${registriesConfig}
    ExecStart=${pkgs.podman}/bin/podman system service --time=0 unix://${runtime}/podman/podman.sock
    Delegate=yes
    NotifyAccess=all
    KillMode=mixed
    Restart=on-failure
    RestartSec=5
    LimitNOFILE=1048576
    TasksMax=infinity
    EOF
  '';
  # The engine API socket path is writable by the untrusted container, so the
  # relay authorizes the upstream peer with SO_PEERCRED before it forwards a
  # single byte. Both scripts share one private libexec directory because the
  # relay reuses the shared forwarding helpers.
  apiRelay =
    pkgs.runCommand "t3code-podman-api-relay" { nativeBuildInputs = [ pkgs.makeWrapper ]; }
      ''
        mkdir -p $out/libexec $out/bin
        install -m 0555 ${../../packages/t3code/dev-engine/api-relay.py} $out/libexec/api-relay.py
        install -m 0555 ${../../packages/t3code/dev-engine/ports.py} $out/libexec/ports.py
        makeWrapper ${pkgs.python3}/bin/python $out/bin/t3code-podman-api-relay \
          --add-flags "$out/libexec/api-relay.py"
      '';
  runtimePaths = [
    pkgs.podman
    pkgs.systemd
    pkgs.dbus
    pkgs.shadow
    pkgs.bash
    pkgs.coreutils
    pkgs.util-linux
    pkgs.getent
    pkgs.gnugrep
    pkgs.gnused
    pkgs.iproute2
    pkgs.iptables
    pkgs.crun
    pkgs.conmon
    pkgs.netavark
    pkgs.aardvark-dns
    pkgs.slirp4netns
    pkgs.fuse-overlayfs
    units
    containersConfig
    storageConfig
    registriesConfig
    pkgs.cacert
  ];
  closure = pkgs.closureInfo { rootPaths = runtimePaths; };
  mount = source: target: readOnly: { inherit source target readOnly; };
  # Preserve subordinate IDs for explicitly granted project ACLs as well as
  # mapping container-root writes back to the T3 workspace owner.
  sharedIdmap = "b:0:0:1 b:3000:${uid}:1 b:${toString cfg.subIdStart}:${toString cfg.subIdStart}:65536";
  spec = pkgs.writeText "t3code-podman-rootfs.json" (
    builtins.toJSON {
      closure = "${closure}/store-paths";
      mounts = [
        (mount "/srv/apps/t3code/nix-root/nix" "/nix" true)
        (mount "${pkgs.bash}/bin/bash" "/bin/sh" true)
        # util-linux's map is filesystem ID -> mount-visible ID. On Btrfs,
        # container root (host cfg.uid) writes apps-owned files without chowning
        # or granting the engine membership of the production apps group.
        ((mount workspace "/workspace" false) // { idmap = sharedIdmap; })
        ((mount worktrees "/home/t3code/.t3/worktrees" false) // { idmap = sharedIdmap; })
        ((mount "/srv/apps/t3code/tmp" "/tmp" false) // { idmap = sharedIdmap; })
        (mount state state false)
        (mount runtime runtime false)
        (mount "/sys/fs/cgroup" "/sys/fs/cgroup" false)
        (mount "/proc" "/proc" false)
        (mount "/dev/pts" "/dev/pts" false)
        (mount "/dev/pts/ptmx" "/dev/ptmx" false)
        (mount "/run/wrappers/bin/newuidmap" "/run/wrappers/bin/newuidmap" true)
        (mount "/run/wrappers/bin/newgidmap" "/run/wrappers/bin/newgidmap" true)
        (mount "/run/systemd/notify" "/run/systemd/notify" false)
      ]
      ++ map (path: mount path path false) [
        "/dev/null"
        "/dev/zero"
        "/dev/random"
        "/dev/urandom"
        "/dev/fuse"
        "/dev/net/tun"
      ];
      files = {
        "/etc/containers/policy.json" = builtins.toJSON {
          default = [ { type = "insecureAcceptAnything"; } ];
        };
        "/etc/passwd" =
          "root:x:0:0:root:/root:/bin/false\n${user}:x:${uid}:${uid}:Podman:${state}/home:/bin/sh\n";
        "/etc/group" = "root:x:0:\n${user}:x:${uid}:\n";
        "/etc/subuid" = "${user}:${toString cfg.subIdStart}:65536\n";
        "/etc/subgid" = "${user}:${toString cfg.subIdStart}:65536\n";
        "/etc/nsswitch.conf" = "passwd: files\ngroup: files\nhosts: files dns\n";
        "/etc/hosts" = "127.0.0.1 localhost\n";
        "/etc/resolv.conf" = lib.concatMapStrings (ip: "nameserver ${ip}\n") cfg.dns;
        "/etc/machine-id" = "c2bfbc68932f4e7f9b11fd7087ccbb5f\n";
        "/etc/os-release" = "ID=nixos\n";
      };
      # NixOS compiles this alias into systemd's re-exec path. It points only
      # at the seeded private closure, never the host's current-system tree.
      symlinks."/run/current-system/systemd" = toString pkgs.systemd;
      directories = [
        "/tmp"
        "/var/tmp"
        "/dev/pts"
        "/etc/ssl/certs"
        "/root"
        "/run/systemd/system"
      ];
    }
  );
  rootfs = pkgs.writeShellScript "t3code-podman-rootfs" ''
    export PATH=${
      lib.makeBinPath [
        pkgs.util-linux
        pkgs.coreutils
      ]
    }
    if [ "$1" = start ]; then
      ${pkgs.nix}/bin/nix copy --no-check-sigs --to 'local?root=/srv/apps/t3code/nix-root' ${cfg.runtimePackage}
      ${pkgs.nix}/bin/nix-store --store 'local?root=/srv/apps/t3code/nix-root' \
        --add-root /srv/apps/t3code/nix-root/nix/var/nix/gcroots/t3code-podman-runtime-${
          if cfg.candidate then "candidate" else "production"
        } \
        --realise ${cfg.runtimePackage} >/dev/null
    fi
    exec ${pkgs.python3}/bin/python ${../../packages/t3code/dev-engine/rootfs.py} "$1" ${root} ${spec}
  '';
  # Host-owned namespace + host-side filter: neither a privileged container nor
  # a different slirp/pasta driver can remove this boundary. IPv6 is disabled,
  # avoiding IPv4-mapped/NAT64/private IPv6 bypasses in this IPv4-only candidate.
  networkRules = pkgs.writeText "t3code-podman-network.nft" ''
    table inet t3code_podman {
      chain input {
        type filter hook input priority -150; policy accept;
        iifname "t3p-host" drop
      }
      chain forward {
        type filter hook forward priority -150; policy accept;
        iifname "t3p-host" meta nfproto ipv6 drop
        iifname "t3p-host" fib daddr type local drop
        iifname "t3p-host" ip daddr { 0.0.0.0/8, 10.0.0.0/8, 100.64.0.0/10, 127.0.0.0/8, 169.254.0.0/16, 172.16.0.0/12, 192.0.0.0/24, 192.0.2.0/24, 192.168.0.0/16, 198.18.0.0/15, 198.51.100.0/24, 203.0.113.0/24, 224.0.0.0/3 } drop
        iifname "t3p-host" oifname != "${cfg.egressInterface}" drop
        oifname "t3p-host" ct state established,related accept
        oifname "t3p-host" drop
      }
      chain nat {
        type nat hook postrouting priority srcnat; policy accept;
        ip saddr 192.0.2.2 oifname "${cfg.egressInterface}" masquerade
      }
    }
  '';
  networkStart = pkgs.writeShellScript "t3code-podman-network-start" ''
    set -eu
    export PATH=${
      lib.makeBinPath [
        pkgs.iproute2
        pkgs.nftables
      ]
    }
    # Never adopt or delete an unexpected preexisting namespace/interface/table.
    if ip netns list | ${pkgs.gnugrep}/bin/grep -q '^t3code-podman\b'; then
      echo 'Refusing to adopt an existing t3code-podman namespace' >&2; exit 1
    fi
    if ip link show t3p-host >/dev/null 2>&1; then
      echo 'Refusing to adopt an existing t3p-host interface' >&2; exit 1
    fi
    if nft list table inet t3code_podman >/dev/null 2>&1; then
      echo 'Refusing to adopt an existing t3code_podman table' >&2; exit 1
    fi
    # From this point failures clean up only resources created by this unit.
    trap '${networkStop}' EXIT
    nft -f ${networkRules}
    ip netns add t3code-podman
    ip link add t3p-host type veth peer name t3p-peer
    ip link set t3p-peer netns t3code-podman
    ip addr add 192.0.2.1/30 dev t3p-host
    ip link set t3p-host up
    ip -n t3code-podman addr add 192.0.2.2/30 dev t3p-peer
    ip -n t3code-podman link set t3p-peer up
    ip -n t3code-podman link set lo up
    ip -n t3code-podman route add default via 192.0.2.1
    ip netns exec t3code-podman ${pkgs.procps}/bin/sysctl -qw net.ipv6.conf.all.disable_ipv6=1 net.ipv6.conf.default.disable_ipv6=1
    trap - EXIT
  '';
  networkStop = pkgs.writeShellScript "t3code-podman-network-stop" ''
    export PATH=${
      lib.makeBinPath [
        pkgs.iproute2
        pkgs.nftables
      ]
    }
    ip link del t3p-host 2>/dev/null || true
    ip netns del t3code-podman 2>/dev/null || true
    nft delete table inet t3code_podman 2>/dev/null || true
  '';
in
{
  options.ghostship.t3codePodman = {
    enable = lib.mkEnableOption "dedicated host rootless T3 Podman development engine";
    uid = lib.mkOption {
      type = lib.types.ints.between 1001 65534;
      default = 62040;
      description = "Dedicated host UID/GID; never the apps UID 3000.";
    };
    subIdStart = lib.mkOption {
      type = lib.types.ints.between 65536 4294901760;
      default = 2000000;
      description = "Start of a dedicated 65536-ID subordinate range.";
    };
    egressInterface = lib.mkOption {
      type = lib.types.strMatching "[a-zA-Z0-9_.:-]*";
      default = "";
      description = "Explicit public Internet egress interface, required on opt-in.";
    };
    dns = lib.mkOption {
      type = lib.types.listOf (lib.types.strMatching "[0-9.]+");
      default = [
        "1.1.1.1"
        "9.9.9.9"
      ];
      description = "Public IPv4 DNS resolvers; private resolvers remain blocked.";
    };
    memoryMax = lib.mkOption {
      type = lib.types.str;
      default = "16G";
      description = "Aggregate engine and container memory limit.";
    };
    cpuQuota = lib.mkOption {
      type = lib.types.str;
      default = "400%";
      description = "Aggregate engine and container CPU quota.";
    };
    tasksMax = lib.mkOption {
      type = lib.types.ints.positive;
      default = 4096;
    };
    bridgePackage = lib.mkOption {
      type = lib.types.package;
      readOnly = true;
      default = pkgs.writeShellScriptBin "t3code-podman-bridge" ''
        exec ${pkgs.python3}/bin/python ${../../packages/t3code/dev-engine/ports.py} "$@"
      '';
      description = "Run t3code-podman-bridge bridge inside T3; bind /run/t3code-podman/ports.sock there as /var/run/t3code-podman-ports.sock. Discovers high TCP published ports and listens only on T3 localhost.";
    };
    candidate = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Disposable candidate storage, never production storage; required by the acceptance harness.";
    };
    runtimePackage = lib.mkOption {
      type = lib.types.package;
      readOnly = true;
      default = pkgs.linkFarm "t3code-podman-runtime" (
        lib.imap0 (i: path: {
          name = toString i;
          inherit path;
        }) runtimePaths
      );
      description = "Finite engine closure seeded before the manager starts, never a host store mount.";
    };
  };

  config = lib.mkIf cfg.enable (
    lib.mkMerge [
      {
        system.build.t3codePodmanCandidate = pkgs.writeText "t3code-podman-candidate.json" (
          builtins.toJSON {
            inherit user state runtime;
            candidate = cfg.candidate;
            inherit graphRoot;
            uid = cfg.uid;
            subIdStart = cfg.subIdStart;
            runtimePackage = toString cfg.runtimePackage;
            units = lib.genAttrs [
              "t3code-podman-network.service"
              "t3code-podman-rootfs.service"
              "t3code-podman.socket"
              "t3code-podman.service"
              "t3code-podman-ports.socket"
              "t3code-podman-ports.service"
            ] (name: config.systemd.units.${name}.text);
            manager = config.systemd.units."user@${uid}.service".text;
          }
        );
        assertions = [
          {
            assertion = cfg.uid != 3000;
            message = "T3 Podman must not reuse the apps UID/GID.";
          }
          {
            assertion = cfg.egressInterface != "";
            message = "T3 Podman needs an explicit public egressInterface.";
          }
          {
            assertion =
              config.boot.kernelParams
              == builtins.filter (p: p != "systemd.unified_cgroup_hierarchy=0") config.boot.kernelParams;
            message = "T3 Podman requires cgroup v2.";
          }
          {
            assertion = !(config.networking.firewall.filterForward or false);
            message = "T3 Podman candidate requires integration with the host forward firewall before filterForward can be enabled.";
          }
          {
            assertion = lib.all (u: u.name == user || u.uid != cfg.uid) (
              builtins.attrValues config.users.users
            );
            message = "T3 Podman UID collides with an existing account.";
          }
          {
            assertion = lib.all (g: g.name == user || g.gid != cfg.uid) (
              builtins.attrValues config.users.groups
            );
            message = "T3 Podman GID collides with an existing group.";
          }
          {
            assertion = lib.all (
              u:
              u.name == user
              || lib.all (
                r: r.startUid + r.count <= cfg.subIdStart || r.startUid >= cfg.subIdStart + 65536
              ) u.subUidRanges
            ) (builtins.attrValues config.users.users);
            message = "T3 Podman subordinate UID range overlaps another account.";
          }
          {
            assertion = lib.all (
              u:
              u.name == user
              || lib.all (
                r: r.startGid + r.count <= cfg.subIdStart || r.startGid >= cfg.subIdStart + 65536
              ) u.subGidRanges
            ) (builtins.attrValues config.users.users);
            message = "T3 Podman subordinate GID range overlaps another account.";
          }
        ];
        ghostship.security.socket_mount_allow = [ "/run/t3code-podman/podman.sock" ];
        system.activationScripts.t3code-podman-identity = {
          deps = [ "users" ];
          text = ''
            ${pkgs.python3}/bin/python ${../../packages/t3code/dev-engine/reconcile-account.py} \
              --name ${user} --uid ${uid} --home ${state}/home \
              --userdel ${pkgs.shadow}/bin/userdel --groupdel ${pkgs.shadow}/bin/groupdel
          '';
        };
        users.groups.${user}.gid = cfg.uid;
        users.users.${user} = {
          isSystemUser = true;
          uid = cfg.uid;
          group = user;
          home = "${state}/home";
          createHome = false;
          linger = true;
          autoSubUidGidRange = false;
          subUidRanges = [
            {
              startUid = cfg.subIdStart;
              count = 65536;
            }
          ];
          subGidRanges = [
            {
              startGid = cfg.subIdStart;
              count = 65536;
            }
          ];
        };
        # NixOS shadow already supplies capability-limited newuidmap/newgidmap.
        boot.kernel.sysctl."net.ipv4.ip_forward" = 1;
        boot.kernelModules = [
          "tun"
          "fuse"
        ];
        systemd.tmpfiles.rules = [
          "d ${state} 0700 ${user} ${user} -"
          "d ${state}/home 0700 ${user} ${user} -"
          "d /run/t3code-podman 0750 root apps -"
        ];
        systemd.services.t3code-podman-network = {
          description = "Host-controlled T3 Podman network boundary";
          before = [ "user@${uid}.service" ];
          serviceConfig = {
            Type = "oneshot";
            RemainAfterExit = true;
            ExecStart = networkStart;
            ExecStop = networkStop;
          };
        };
        systemd.services.t3code-podman-rootfs = {
          description = "Minimal filesystem for the dedicated rootless Podman manager";
          requires = [ "user-runtime-dir@${uid}.service" ];
          after = [ "user-runtime-dir@${uid}.service" ];
          before = [ "user@${uid}.service" ];
          serviceConfig = {
            Type = "oneshot";
            RemainAfterExit = true;
            ExecStart = "${rootfs} start";
            ExecStop = "${rootfs} stop";
          };
        };
        # A genuine user manager (not unsupported system-wide rootful engine User=).
        systemd.services."user@${uid}" = {
          overrideStrategy = "asDropin";
          requires = [
            "t3code-podman-network.service"
            "t3code-podman-rootfs.service"
          ];
          after = [
            "t3code-podman-network.service"
            "t3code-podman-rootfs.service"
          ];
          bindsTo = [
            "t3code-podman-network.service"
            "t3code-podman-rootfs.service"
          ];
          environment = {
            SYSTEMD_UNIT_PATH = "${units}";
            HOME = "${state}/home";
            XDG_RUNTIME_DIR = runtime;
            DBUS_SESSION_BUS_ADDRESS = "unix:path=${runtime}/bus";
            SSL_CERT_FILE = "${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt";
          };
          serviceConfig = {
            RootDirectory = root;
            NetworkNamespacePath = "/run/netns/t3code-podman";
            # Keep proc visibility unchanged until crun/user-manager acceptance
            # proves a narrower setting; no host system bus is projected.
            ProtectProc = "default";
            Delegate = "cpu cpuset io memory pids";
            MemoryMax = cfg.memoryMax;
            CPUQuota = cfg.cpuQuota;
            TasksMax = cfg.tasksMax;
          };
        };
        # API relay grants only the apps group access, without making the dedicated
        # daemon a member of apps or exposing its private runtime directory.
        systemd.sockets.t3code-podman = {
          wantedBy = [ "sockets.target" ];
          socketConfig = {
            ListenStream = "/run/t3code-podman/podman.sock";
            SocketMode = "0660";
            SocketUser = "root";
            SocketGroup = "apps";
          };
        };
        systemd.services.t3code-podman = {
          requires = [ "user@${uid}.service" ];
          bindsTo = [ "user@${uid}.service" ];
          after = [ "user@${uid}.service" ];
          serviceConfig = {
            # The relay owns no listener: systemd hands over the socket on
            # fd 3 and the relay forwards to the engine only after the
            # upstream peer proved to be the engine UID. A redirected engine
            # path therefore fails closed instead of reaching a root-only
            # host socket with the relay's own privileges.
            ExecStart = "${apiRelay}/bin/t3code-podman-api-relay --upstream ${runtime}/podman/podman.sock --engine-uid ${uid}";
            # A different UID avoids exposing a host-rooted /proc/PID/root to the
            # engine through a relay process with the engine's own UID.
            User = "root";
            NoNewPrivileges = true;
            ProtectSystem = "strict";
            # ProtectHome=true also masks /run/user and would hide the target
            # engine socket. Hide actual home/service trees explicitly instead.
            InaccessiblePaths = [
              "/home"
              "/root"
              "/srv"
            ];
            PrivateTmp = true;
            RestrictAddressFamilies = [ "AF_UNIX" ];
            MemoryMax = "128M";
            TasksMax = 64;
            LimitNOFILE = 4096;
            Restart = "on-failure";
            RestartSec = 5;
          };
        };
        systemd.sockets.t3code-podman-ports = {
          wantedBy = [ "sockets.target" ];
          socketConfig = {
            ListenStream = "/run/t3code-podman/ports.sock";
            SocketMode = "0660";
            SocketUser = "root";
            SocketGroup = "apps";
          };
        };
        systemd.services.t3code-podman-ports = {
          requires = [ "user@${uid}.service" ];
          bindsTo = [ "user@${uid}.service" ];
          after = [ "user@${uid}.service" ];
          serviceConfig = {
            ExecStart = "${cfg.bridgePackage}/bin/t3code-podman-bridge gateway";
            DynamicUser = true;
            NetworkNamespacePath = "/run/netns/t3code-podman";
            NoNewPrivileges = true;
            ProtectSystem = "strict";
            ProtectHome = true;
            PrivateTmp = true;
            RestrictAddressFamilies = [
              "AF_UNIX"
              "AF_INET"
            ];
            MemoryMax = "128M";
            TasksMax = 64;
            LimitNOFILE = 4096;
            Restart = "on-failure";
          };
        };
      }
    ]
  );
}
