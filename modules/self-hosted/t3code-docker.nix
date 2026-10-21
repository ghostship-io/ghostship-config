{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.ghostship.t3codeDocker;
  user = "t3code-docker";
  uid = toString cfg.uid;
  state = "/var/lib/t3code-docker";
  root = "/run/t3code-docker-rootfs";
  runtime = "/run/user/${uid}";
  workspace = config.ghostship.agentHost.workspacePath;
  worktrees = "/srv/apps/t3code/home/.t3/worktrees";
  dockerConfig = (pkgs.formats.json { }).generate "t3code-docker.json" {
    hosts = [ "unix://${runtime}/docker.sock" ];
    data-root = "${state}/data";
    exec-root = "${runtime}/exec";
    storage-driver = "fuse-overlayfs";
    exec-opts = [ "native.cgroupdriver=systemd" ];
    dns = cfg.dns;
    live-restore = false;
    labels = [ "ghostship.t3code-docker=candidate" ];
    pidfile = "${runtime}/docker.pid";
    log-driver = "local";
    log-opts = {
      max-size = "10m";
      max-file = "3";
    };
    default-address-pools = [
      {
        base = "172.28.0.0/16";
        size = 24;
      }
    ];
  };
  busConfig = pkgs.writeText "t3code-docker-bus.conf" ''
    <busconfig>
      <type>session</type>
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
  # services. It has a real session bus for Docker's systemd cgroup driver.
  units = pkgs.runCommand "t3code-docker-user-units" { } ''
    mkdir -p $out
    cp ${pkgs.systemd}/example/systemd/user/{basic.target,sockets.target,paths.target,timers.target,shutdown.target,exit.target,systemd-exit.service,app.slice,session.slice,background.slice} $out/
    cat > $out/default.target <<'EOF'
    [Unit]
    Description=Dedicated T3 Docker manager
    Requires=basic.target
    Wants=dbus.socket docker.service
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
    cat > $out/docker.service <<'EOF'
    [Unit]
    Requires=dbus.socket
    After=dbus.socket
    [Service]
    Type=notify
    StandardOutput=inherit
    StandardError=inherit
    Environment=PATH=/run/wrappers/bin:${
      lib.makeBinPath [
        pkgs.bash
        pkgs.docker
        pkgs.rootlesskit
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
    Environment=DOCKERD_ROOTLESS_ROOTLESSKIT_NET=slirp4netns
    Environment=DOCKERD_ROOTLESS_ROOTLESSKIT_PORT_DRIVER=builtin
    ExecStart=${pkgs.docker}/bin/dockerd-rootless --config-file=${dockerConfig}
    Delegate=yes
    NotifyAccess=all
    KillMode=mixed
    Restart=on-failure
    RestartSec=5
    LimitNOFILE=1048576
    TasksMax=infinity
    EOF
  '';
  runtimePaths = [
    pkgs.docker
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
    pkgs.rootlesskit
    pkgs.slirp4netns
    pkgs.fuse-overlayfs
    units
    dockerConfig
    pkgs.cacert
  ];
  closure = pkgs.closureInfo { rootPaths = runtimePaths; };
  mount = source: target: readOnly: { inherit source target readOnly; };
  # Preserve subordinate IDs for explicitly granted project ACLs as well as
  # mapping container-root writes back to the T3 workspace owner.
  sharedIdmap = "b:3000:${uid}:1 b:${toString cfg.subIdStart}:${toString cfg.subIdStart}:65536";
  spec = pkgs.writeText "t3code-docker-rootfs.json" (
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
        "/etc/passwd" =
          "root:x:0:0:root:/root:/bin/false\n${user}:x:${uid}:${uid}:Docker:${state}/home:/bin/sh\n";
        "/etc/group" = "root:x:0:\n${user}:x:${uid}:\n";
        "/etc/subuid" = "${user}:${toString cfg.subIdStart}:65536\n";
        "/etc/subgid" = "${user}:${toString cfg.subIdStart}:65536\n";
        "/etc/nsswitch.conf" = "passwd: files\ngroup: files\nhosts: files dns\n";
        "/etc/hosts" = "127.0.0.1 localhost\n";
        "/etc/resolv.conf" = lib.concatMapStrings (ip: "nameserver ${ip}\n") cfg.dns;
        "/etc/machine-id" = "c2bfbc68932f4e7f9b11fd7087ccbb5f\n";
        "/etc/os-release" = "ID=nixos\n";
      };
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
  rootfs = pkgs.writeShellScript "t3code-docker-rootfs" ''
    export PATH=${
      lib.makeBinPath [
        pkgs.util-linux
        pkgs.coreutils
      ]
    }
    exec ${pkgs.python3}/bin/python ${../../packages/t3code/docker-sandbox/rootfs.py} "$1" ${root} ${spec}
  '';
  # Host-owned namespace + host-side filter: neither a privileged container nor
  # a different slirp/pasta driver can remove this boundary. IPv6 is disabled,
  # avoiding IPv4-mapped/NAT64/private IPv6 bypasses in this IPv4-only candidate.
  networkRules = pkgs.writeText "t3code-docker-network.nft" ''
    table inet t3code_docker {
      chain input {
        type filter hook input priority -150; policy accept;
        iifname "t3d-host" drop
      }
      chain forward {
        type filter hook forward priority -150; policy accept;
        iifname "t3d-host" meta nfproto ipv6 drop
        iifname "t3d-host" fib daddr type local drop
        iifname "t3d-host" ip daddr { 0.0.0.0/8, 10.0.0.0/8, 100.64.0.0/10, 127.0.0.0/8, 169.254.0.0/16, 172.16.0.0/12, 192.0.0.0/24, 192.0.2.0/24, 192.168.0.0/16, 198.18.0.0/15, 198.51.100.0/24, 203.0.113.0/24, 224.0.0.0/3 } drop
        iifname "t3d-host" oifname != "${cfg.egressInterface}" drop
        oifname "t3d-host" ct state established,related accept
        oifname "t3d-host" drop
      }
      chain nat {
        type nat hook postrouting priority srcnat; policy accept;
        ip saddr 192.0.2.2 oifname "${cfg.egressInterface}" masquerade
      }
    }
  '';
  networkStart = pkgs.writeShellScript "t3code-docker-network-start" ''
    set -eu
    export PATH=${
      lib.makeBinPath [
        pkgs.iproute2
        pkgs.nftables
      ]
    }
    # Never adopt or delete an unexpected preexisting namespace/interface/table.
    if ip netns list | ${pkgs.gnugrep}/bin/grep -q '^t3code-docker\b'; then
      echo 'Refusing to adopt an existing t3code-docker namespace' >&2; exit 1
    fi
    if ip link show t3d-host >/dev/null 2>&1; then
      echo 'Refusing to adopt an existing t3d-host interface' >&2; exit 1
    fi
    if nft list table inet t3code_docker >/dev/null 2>&1; then
      echo 'Refusing to adopt an existing t3code_docker table' >&2; exit 1
    fi
    # From this point failures clean up only resources created by this unit.
    trap '${networkStop}' EXIT
    nft -f ${networkRules}
    ip netns add t3code-docker
    ip link add t3d-host type veth peer name t3d-peer
    ip link set t3d-peer netns t3code-docker
    ip addr add 192.0.2.1/30 dev t3d-host
    ip link set t3d-host up
    ip -n t3code-docker addr add 192.0.2.2/30 dev t3d-peer
    ip -n t3code-docker link set t3d-peer up
    ip -n t3code-docker link set lo up
    ip -n t3code-docker route add default via 192.0.2.1
    ip netns exec t3code-docker ${pkgs.procps}/bin/sysctl -qw net.ipv6.conf.all.disable_ipv6=1 net.ipv6.conf.default.disable_ipv6=1
    trap - EXIT
  '';
  networkStop = pkgs.writeShellScript "t3code-docker-network-stop" ''
    export PATH=${
      lib.makeBinPath [
        pkgs.iproute2
        pkgs.nftables
      ]
    }
    ip link del t3d-host 2>/dev/null || true
    ip netns del t3code-docker 2>/dev/null || true
    nft delete table inet t3code_docker 2>/dev/null || true
  '';
in
{
  options.ghostship.t3codeDocker = {
    enable = lib.mkEnableOption "staged host rootless T3 Docker (requires candidate acceptance before enabling)";
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
      default = pkgs.writeShellScriptBin "t3code-docker-bridge" ''
        exec ${pkgs.python3}/bin/python ${../../packages/t3code/docker-sandbox/ports.py} "$@"
      '';
      description = "Run t3code-docker-bridge bridge inside T3; bind /run/t3code-docker/ports.sock there as /var/run/t3code-docker-ports.sock. Discovers high TCP published ports and listens only on T3 localhost.";
    };
    runtimePackage = lib.mkOption {
      type = lib.types.package;
      readOnly = true;
      default = pkgs.linkFarm "t3code-docker-runtime" (
        lib.imap0 (i: path: {
          name = toString i;
          inherit path;
        }) runtimePaths
      );
      description = "Include in T3 image closure before enabling: seeds engine dependencies into the private inner Nix store, never the entire host store.";
    };
  };

  config = lib.mkIf cfg.enable (
    lib.mkMerge [
      {
        system.build.t3codeDockerCandidate = pkgs.writeText "t3code-docker-candidate.json" (
          builtins.toJSON {
            inherit user state runtime;
            uid = cfg.uid;
            subIdStart = cfg.subIdStart;
            runtimePackage = toString cfg.runtimePackage;
            units = lib.genAttrs [
              "t3code-docker-network.service"
              "t3code-docker-rootfs.service"
              "t3code-docker.socket"
              "t3code-docker.service"
              "t3code-docker-ports.socket"
              "t3code-docker-ports.service"
            ] (name: config.systemd.units.${name}.text);
            manager = config.systemd.units."user@${uid}.service".text;
          }
        );
        assertions = [
          {
            assertion = cfg.uid != 3000;
            message = "T3 Docker must not reuse the apps UID/GID.";
          }
          {
            assertion = cfg.egressInterface != "";
            message = "T3 Docker needs an explicit public egressInterface.";
          }
          {
            assertion =
              config.boot.kernelParams
              == builtins.filter (p: p != "systemd.unified_cgroup_hierarchy=0") config.boot.kernelParams;
            message = "T3 Docker requires cgroup v2.";
          }
          {
            assertion = !(config.networking.firewall.filterForward or false);
            message = "T3 Docker candidate requires integration with the host forward firewall before filterForward can be enabled.";
          }
          {
            assertion = lib.all (u: u.name == user || u.uid != cfg.uid) (
              builtins.attrValues config.users.users
            );
            message = "T3 Docker UID collides with an existing account.";
          }
          {
            assertion = lib.all (g: g.name == user || g.gid != cfg.uid) (
              builtins.attrValues config.users.groups
            );
            message = "T3 Docker GID collides with an existing group.";
          }
          {
            assertion = lib.all (
              u:
              u.name == user
              || lib.all (
                r: r.startUid + r.count <= cfg.subIdStart || r.startUid >= cfg.subIdStart + 65536
              ) u.subUidRanges
            ) (builtins.attrValues config.users.users);
            message = "T3 Docker subordinate UID range overlaps another account.";
          }
          {
            assertion = lib.all (
              u:
              u.name == user
              || lib.all (
                r: r.startGid + r.count <= cfg.subIdStart || r.startGid >= cfg.subIdStart + 65536
              ) u.subGidRanges
            ) (builtins.attrValues config.users.users);
            message = "T3 Docker subordinate GID range overlaps another account.";
          }
        ];
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
          "d /run/t3code-docker 0750 root apps -"
        ];
        systemd.services.t3code-docker-network = {
          description = "Host-controlled T3 Docker network boundary";
          before = [ "user@${uid}.service" ];
          serviceConfig = {
            Type = "oneshot";
            RemainAfterExit = true;
            ExecStart = networkStart;
            ExecStop = networkStop;
          };
        };
        systemd.services.t3code-docker-rootfs = {
          description = "Minimal filesystem for the dedicated rootless Docker manager";
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
        # A genuine user manager (not unsupported system-wide dockerd User=).
        systemd.services."user@${uid}" = {
          overrideStrategy = "asDropin";
          requires = [
            "t3code-docker-network.service"
            "t3code-docker-rootfs.service"
          ];
          after = [
            "t3code-docker-network.service"
            "t3code-docker-rootfs.service"
          ];
          bindsTo = [
            "t3code-docker-network.service"
            "t3code-docker-rootfs.service"
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
            NetworkNamespacePath = "/run/netns/t3code-docker";
            ProtectProc = "invisible";
            Delegate = "cpu cpuset io memory pids";
            MemoryMax = cfg.memoryMax;
            CPUQuota = cfg.cpuQuota;
            TasksMax = cfg.tasksMax;
          };
        };
        # API relay grants only the apps group access, without making the dedicated
        # daemon a member of apps or exposing its private runtime directory.
        systemd.sockets.t3code-docker = {
          wantedBy = [ "sockets.target" ];
          socketConfig = {
            ListenStream = "/run/t3code-docker/docker.sock";
            SocketMode = "0660";
            SocketUser = "root";
            SocketGroup = "apps";
          };
        };
        systemd.services.t3code-docker = {
          requires = [ "user@${uid}.service" ];
          after = [ "user@${uid}.service" ];
          serviceConfig = {
            ExecStart = "${pkgs.systemd}/lib/systemd/systemd-socket-proxyd ${runtime}/docker.sock";
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
          };
        };
        systemd.sockets.t3code-docker-ports = {
          wantedBy = [ "sockets.target" ];
          socketConfig = {
            ListenStream = "/run/t3code-docker/ports.sock";
            SocketMode = "0660";
            SocketUser = "root";
            SocketGroup = "apps";
          };
        };
        systemd.services.t3code-docker-ports = {
          requires = [ "user@${uid}.service" ];
          after = [ "user@${uid}.service" ];
          serviceConfig = {
            ExecStart = "${cfg.bridgePackage}/bin/t3code-docker-bridge gateway";
            DynamicUser = true;
            NetworkNamespacePath = "/run/netns/t3code-docker";
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
