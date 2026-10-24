# Only this definition and its base packages determine container identity.
# Agent releases, host state and tooling are deliberately outside this interface.
{ pkgs }:
let
  inherit (pkgs) lib;
  managedBin = "/home/t3code/.local/state/ghostship-t3-tools/current/bin";
  t3codePackages = with pkgs; [ nix systemd dbus pam sudo bashInteractive coreutils cacert ];
  t3codePath = "${managedBin}:/home/t3code/.local/bin:${lib.makeBinPath t3codePackages}";
  t3codeEntrypoint = pkgs.writeShellScriptBin "t3code-systemd-entrypoint" ''
    set -eu

    exec ${pkgs.systemd}/lib/systemd/systemd
  '';

  t3codeImageContents = t3codePackages ++ [
    t3codeEntrypoint
    pkgs.dockerTools.binSh
    pkgs.dockerTools.usrBinEnv
    pkgs.dockerTools.caCertificates
  ];

  imageArgs = {
    name = "localhost/ghostship-t3code";
    tag = "t3code-runtime";
    contents = t3codeImageContents;
    extraCommands = ''
      mkdir -p etc/nix etc/pam.d etc/sudoers.d etc/systemd/system/multi-user.target.wants etc/systemd/user/sockets.target.wants usr/bin usr/share/systemd/user nix/store nix/var/log/nix nix/var/nix tmp workspace home/t3code
      mkdir -p mnt/share run/user var/empty var/log/journal var/run
      mkdir -p bin
      mkdir -p usr/share/t3code-command-code usr/share/t3code-provider-privacy
      cp -r ${./command-code}/. usr/share/t3code-command-code/
      cp -r ${./provider-privacy}/. usr/share/t3code-provider-privacy/
      # systemd does not inherit the image's PATH for its services. Managed
      # helpers need these commands before their own environment setup runs.
      for manager in system user; do
        cat > etc/systemd/$manager.conf <<'EOF'
      [Manager]
      DefaultEnvironment=PATH=${t3codePath}:/bin:/usr/bin
      EOF
      done
      # Existing provider settings use this path; the payload stays managed in home.
      ln -s ${managedBin}/agy_acp_server.par bin/agy_acp_server.par
      mkdir -p lib lib64
      ln -s ${pkgs.stdenv.cc.bintools.dynamicLinker} lib/$(basename ${pkgs.stdenv.cc.bintools.dynamicLinker})
      ln -s ${pkgs.stdenv.cc.bintools.dynamicLinker} lib64/$(basename ${pkgs.stdenv.cc.bintools.dynamicLinker})
      chmod 1777 tmp
      chmod 0555 var/empty
      cp ${pkgs.sudo}/bin/sudo usr/bin/sudo
      chmod 0755 usr/bin/sudo
      cat > etc/passwd <<'EOF'
      root:x:0:0:root:/root:/bin/sh
      nobody:x:65534:65534:Unprivileged:/var/empty:/bin/sh
      t3code:x:3000:3000:T3 Code:/home/t3code:/bin/sh
      EOF
      cat > etc/group <<'EOF'
      root:x:0:
      nobody:x:65534:
      t3code:x:3000:
      EOF
      nixbld_members=""
      nixbld_index=1
      while [ "$nixbld_index" -le 32 ]; do
        printf 'nixbld%s:x:%s:30000:Nix build user %s:/var/empty:/bin/sh\n' \
          "$nixbld_index" "$((30000 + nixbld_index))" "$nixbld_index" >> etc/passwd
        if [ -n "$nixbld_members" ]; then
          nixbld_members="$nixbld_members,"
        fi
        nixbld_members="$nixbld_members""nixbld$nixbld_index"
        nixbld_index="$((nixbld_index + 1))"
      done
      printf 'nixbld:x:30000:%s\n' "$nixbld_members" >> etc/group
      cat > etc/nix/nix.conf <<'EOF'
      experimental-features = nix-command flakes
      sandbox = false
      allowed-users = root t3code
      trusted-users = root
      max-jobs = 2
      cores = 2
      build-users-group = nixbld
      EOF
      rm -f etc/sudoers etc/sudoers.d/t3code-apply-config etc/pam.d/sudo
      cat > etc/sudoers <<'EOF'
      root ALL=(ALL:ALL) ALL
      #includedir /etc/sudoers.d
      EOF
      chmod 0440 etc/sudoers
      cat > etc/sudoers.d/t3code-apply-config <<'EOF'
      t3code ALL=(root) NOPASSWD: ${pkgs.systemd}/bin/systemctl reset-failed t3code-server.service
      t3code ALL=(root) NOPASSWD: ${pkgs.systemd}/bin/systemctl restart t3code-server.service
      EOF
      chmod 0440 etc/sudoers.d/t3code-apply-config
      rm -f etc/pam.d/systemd-user
      cat > etc/pam.d/systemd-user <<'EOF'
      account required ${pkgs.pam}/lib/security/pam_permit.so
      session required ${pkgs.pam}/lib/security/pam_permit.so
      EOF
      cat > etc/pam.d/sudo <<'EOF'
      auth sufficient ${pkgs.pam}/lib/security/pam_permit.so
      account required ${pkgs.pam}/lib/security/pam_permit.so
      session required ${pkgs.pam}/lib/security/pam_permit.so
      EOF
      for system_unit in halt.target shutdown.target final.target systemd-halt.service umount.target; do
        cp -a "${pkgs.systemd}/example/systemd/system/$system_unit" etc/systemd/system/
      done
      cp -a ${pkgs.systemd}/example/systemd/user/. usr/share/systemd/user/
      rm -f etc/systemd/user/dbus.socket etc/systemd/user/dbus.service etc/systemd/user/sockets.target.wants/dbus.socket
      cat > etc/systemd/user/dbus.socket <<'EOF'
      [Unit]
      Description=D-Bus User Message Bus Socket

      [Socket]
      ListenStream=%t/bus
      ExecStartPost=-${pkgs.systemd}/bin/systemctl --user set-environment DBUS_SESSION_BUS_ADDRESS=unix:path=%t/bus

      [Install]
      WantedBy=sockets.target
      EOF
      cat > etc/systemd/user/dbus.service <<'EOF'
      [Unit]
      Description=D-Bus User Message Bus
      Documentation=man:dbus-daemon(1)
      Requires=dbus.socket

      [Service]
      Type=notify
      NotifyAccess=main
      ExecStart=${pkgs.dbus}/bin/dbus-daemon --config-file=${pkgs.dbus}/share/dbus-1/session.conf --address=systemd: --nofork --nopidfile --systemd-activation --syslog-only
      ExecReload=${pkgs.dbus}/bin/dbus-send --print-reply --session --type=method_call --dest=org.freedesktop.DBus / org.freedesktop.DBus.ReloadConfig
      Slice=session.slice
      EOF
      mkdir -p etc/systemd/user/default.target.wants
      cat > etc/systemd/user/t3code-podman-bridge.service <<'BRIDGE'
      [Unit]
      Description=Localhost access to isolated development Podman ports
      [Service]
      ExecStart=/home/t3code/.local/state/t3code-podman-bridge/bin/t3code-podman-bridge bridge
      Restart=always
      RestartSec=2
      [Install]
      WantedBy=default.target
      BRIDGE
      ln -s ../t3code-podman-bridge.service etc/systemd/user/default.target.wants/t3code-podman-bridge.service
      ln -s ../dbus.socket etc/systemd/user/sockets.target.wants/dbus.socket
      cat > etc/systemd/system/t3code-container-setup.service <<'EOF'
      [Unit]
      Description=Prepare T3 Code container state
      DefaultDependencies=no
      Conflicts=shutdown.target
      Before=shutdown.target

      [Service]
      Type=oneshot
      ExecStart=${managedBin}/t3code-container-setup
      RemainAfterExit=yes
      TimeoutStartSec=20m
      TasksMax=infinity

      [Install]
      WantedBy=multi-user.target
      EOF
      cat > etc/systemd/system/nix-daemon.service <<'EOF'
      [Unit]
      Description=Nix package manager daemon
      DefaultDependencies=no
      After=t3code-container-setup.service nix-daemon.socket
      Requires=t3code-container-setup.service nix-daemon.socket
      Conflicts=shutdown.target
      Before=user@3000.service t3code-bootstrap.service t3code-server.service shutdown.target

      [Service]
      Type=simple
      ExecStart=@${pkgs.nix}/bin/nix-daemon nix-daemon --daemon
      KillMode=mixed
      LimitNOFILE=1048576
      Delegate=yes
      Restart=always
      RestartSec=5
      TimeoutStopSec=30s
      TasksMax=infinity

      [Install]
      WantedBy=multi-user.target
      EOF
      cat > etc/systemd/system/nix-daemon.socket <<'EOF'
      [Unit]
      Description=Nix package manager daemon socket
      DefaultDependencies=no
      After=t3code-container-setup.service
      Requires=t3code-container-setup.service
      Conflicts=shutdown.target
      Before=nix-daemon.service user@3000.service t3code-bootstrap.service t3code-server.service shutdown.target

      [Socket]
      ListenStream=/nix/var/nix/daemon-socket/socket
      SocketMode=0666
      DirectoryMode=0755
      RemoveOnStop=true

      [Install]
      WantedBy=multi-user.target
      EOF
      cat > etc/systemd/system/user@.service <<'EOF'
      [Unit]
      Description=T3 Code user manager for UID %i
      Documentation=man:user@.service(5)
      DefaultDependencies=no
      After=t3code-container-setup.service nix-daemon.socket
      Requires=t3code-container-setup.service nix-daemon.socket
      Conflicts=shutdown.target
      Before=t3code-bootstrap.service t3code-server.service shutdown.target
      IgnoreOnIsolate=yes

      [Service]
      User=%i
      PAMName=systemd-user
      Type=notify-reload
      Environment=HOME=/home/t3code
      Environment=USER=t3code
      Environment=LOGNAME=t3code
      Environment=XDG_RUNTIME_DIR=/run/user/%i
      Environment=DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/%i/bus
      Environment=NIX_REMOTE=daemon
      ExecStart=${pkgs.systemd}/lib/systemd/systemd --user
      Slice=user-%i.slice
      ReloadSignal=RTMIN+25
      KillMode=mixed
      Delegate=pids memory cpu
      DelegateSubgroup=init.scope
      TasksMax=infinity
      TimeoutStopSec=10s
      KeyringMode=inherit
      OOMScoreAdjust=100
      MemoryPressureWatch=skip
      Restart=always
      RestartSec=5

      [Install]
      WantedBy=multi-user.target
      EOF
      cat > etc/systemd/system/t3code-engine-ready.service <<'EOF'
      [Unit]
      Description=T3 Code rootless Podman readiness
      DefaultDependencies=no
      After=t3code-container-setup.service
      Requires=t3code-container-setup.service
      Conflicts=shutdown.target
      Before=shutdown.target

      [Service]
      Type=notify
      NotifyAccess=all
      ExecStart=${managedBin}/t3code-engine-ready
      Restart=always
      RestartSec=5
      TimeoutStopSec=30s
      TimeoutStartSec=180s
      TasksMax=infinity

      [Install]
      WantedBy=multi-user.target
      EOF
      cat > etc/systemd/system/t3code-bootstrap.service <<'EOF'
      [Unit]
      Description=Run T3 Code bootstrap hooks
      DefaultDependencies=no
      After=t3code-container-setup.service nix-daemon.socket user@3000.service t3code-engine-ready.service
      Requires=t3code-container-setup.service nix-daemon.socket user@3000.service t3code-engine-ready.service
      Conflicts=shutdown.target
      Before=shutdown.target

      [Service]
      Type=oneshot
      User=t3code
      Group=t3code
      Environment=HOME=/home/t3code
      Environment=USER=t3code
      Environment=XDG_RUNTIME_DIR=/run/user/3000
      Environment=DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/3000/bus
      Environment=OPENCODE_AUTOMATION_DIR=/home/t3code/.automation
      Environment=PATH=${t3codePath}:/home/t3code/.local/bin:/home/t3code/.local/share/t3code-tools/npm/bin:/bin:/usr/bin
      ExecStart=${managedBin}/t3code-bootstrap
      RemainAfterExit=yes
      TimeoutStartSec=20m
      StandardOutput=append:/home/t3code/.t3code-container/logs/t3code-bootstrap.log
      StandardError=append:/home/t3code/.t3code-container/logs/t3code-bootstrap.log
      TasksMax=infinity

      [Install]
      WantedBy=multi-user.target
      EOF
      cat > etc/systemd/system/t3code-server.service <<'EOF'
      [Unit]
      Description=T3 Code server and web UI
      DefaultDependencies=no
      After=t3code-container-setup.service user@3000.service t3code-engine-ready.service t3code-bootstrap.service
      Requires=t3code-container-setup.service user@3000.service t3code-engine-ready.service t3code-bootstrap.service
      Conflicts=shutdown.target
      Before=shutdown.target

      [Service]
      Type=simple
      User=t3code
      Group=t3code
      Environment=HOME=/home/t3code
      Environment=USER=t3code
      Environment=XDG_RUNTIME_DIR=/run/user/3000
      Environment=DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/3000/bus
      Environment=OPENCODE_AUTOMATION_DIR=/home/t3code/.automation
      Environment=PATH=${t3codePath}:/home/t3code/.local/bin:/home/t3code/.local/share/t3code-tools/npm/bin:/bin:/usr/bin
      ExecStartPre=${managedBin}/t3code-run-hooks before-t3code.d
      ExecStartPre=-${managedBin}/python3 /usr/share/t3code-command-code/setup.py
      ExecStartPre=-${managedBin}/python3 /usr/share/t3code-provider-privacy/setup.py
      ExecStartPre=-${managedBin}/t3code-opencode-model-catalog
      ExecStartPre=-${managedBin}/t3code-free-instance-reconcile
      ExecStartPre=+${pkgs.coreutils}/bin/rm -f /run/t3code-tool-update/restart.pending /home/t3code/.local/share/t3code-tools/t3/activation.pending
      ExecStart=${managedBin}/t3code-server-run
      ExecStartPost=${managedBin}/t3code-snapshot-config
      Restart=always
      RestartSec=5
      TimeoutStartSec=20m
      TimeoutStopSec=10s
      SuccessExitStatus=0 143
      StandardOutput=append:/home/t3code/.t3code-container/logs/t3code-server.service.log
      StandardError=append:/home/t3code/.t3code-container/logs/t3code-server.service.log
      # This cgroup includes every provider and its tools, not only the web server.
      MemoryHigh=36G
      MemoryMax=40G
      OOMPolicy=continue
      TasksMax=infinity

      [Install]
      WantedBy=multi-user.target
      EOF
      cat > etc/systemd/system/t3code-access-proxy.service <<'EOF'
      [Unit]
      Description=T3 Code access through the Cloudflare-authenticated site
      DefaultDependencies=no
      After=t3code-server.service
      Requires=t3code-container-setup.service
      Conflicts=shutdown.target
      Before=shutdown.target

      [Service]
      User=t3code
      Group=t3code
      Environment=HOME=/home/t3code
      ExecStart=${managedBin}/t3code-access-proxy
      Restart=always
      RestartSec=5
      StandardOutput=append:/home/t3code/.t3code-container/logs/t3code-access-proxy.log
      StandardError=append:/home/t3code/.t3code-container/logs/t3code-access-proxy.log

      [Install]
      WantedBy=multi-user.target
      EOF
      cat > etc/systemd/system/t3code-tool-auto-update.service <<'EOF'
      [Unit]
      Description=Update T3 Code, Codex, Antigravity, OpenCode, and Ghostship tooling
      DefaultDependencies=no
      After=t3code-bootstrap.service
      Requires=t3code-bootstrap.service
      Conflicts=shutdown.target
      Before=shutdown.target

      [Service]
      Type=oneshot
      Environment=PATH=${t3codePath}:/home/t3code/.local/bin:/home/t3code/.local/share/t3code-tools/npm/bin:/bin:/usr/bin
      ExecStart=${managedBin}/t3code-tool-auto-update
      StandardOutput=append:/home/t3code/.t3code-container/logs/t3code-tool-auto-update.log
      StandardError=append:/home/t3code/.t3code-container/logs/t3code-tool-auto-update.log
      TasksMax=infinity
      EOF
      cat > etc/systemd/system/t3code-tool-auto-update.timer <<'EOF'
      [Unit]
      Description=Periodic T3 Code agent tool updates
      DefaultDependencies=no
      After=t3code-bootstrap.service
      Conflicts=shutdown.target
      Before=shutdown.target

      [Timer]
      OnBootSec=10m
      OnUnitActiveSec=4h
      Persistent=true
      Unit=t3code-tool-auto-update.service

      [Install]
      WantedBy=multi-user.target
      EOF
      cat > etc/systemd/system/t3code-provider-update-watch.service <<'EOF'
      [Unit]
      Description=Start tool maintenance when a provider update is published
      DefaultDependencies=no
      After=t3code-bootstrap.service
      Requires=t3code-bootstrap.service
      Conflicts=shutdown.target
      Before=shutdown.target

      [Service]
      Type=oneshot
      Environment=PATH=${t3codePath}:/bin:/usr/bin
      ExecStart=${managedBin}/t3code-provider-update-watch
      StandardOutput=append:/home/t3code/.t3code-container/logs/t3code-tool-auto-update.log
      StandardError=append:/home/t3code/.t3code-container/logs/t3code-tool-auto-update.log
      EOF
      cat > etc/systemd/system/t3code-provider-update-watch.timer <<'EOF'
      [Unit]
      Description=Check for provider releases T3 Code would advise
      DefaultDependencies=no
      After=t3code-bootstrap.service
      Conflicts=shutdown.target
      Before=shutdown.target

      [Timer]
      OnBootSec=5m
      OnUnitActiveSec=10m
      Unit=t3code-provider-update-watch.service

      [Install]
      WantedBy=multi-user.target
      EOF
      cat > etc/systemd/system/t3code-ghostship-agent-sync.service <<'EOF'
      [Unit]
      Description=Sync and install Ghostship agent tooling from GitHub main
      DefaultDependencies=no
      After=t3code-bootstrap.service
      Requires=t3code-bootstrap.service
      Conflicts=shutdown.target
      Before=shutdown.target

      [Service]
      Type=oneshot
      Environment=PATH=${t3codePath}:/home/t3code/.local/bin:/home/t3code/.local/share/t3code-tools/npm/bin:/bin:/usr/bin
      ExecStart=${managedBin}/t3code-install-ghostship-agent
      StandardOutput=append:/home/t3code/.t3code-container/logs/t3code-ghostship-agent-sync.log
      StandardError=append:/home/t3code/.t3code-container/logs/t3code-ghostship-agent-sync.log
      TasksMax=infinity
      EOF
      cat > etc/systemd/system/t3code-ghostship-agent-sync.timer <<'EOF'
      [Unit]
      Description=Periodic Ghostship agent tooling sync
      DefaultDependencies=no
      After=t3code-bootstrap.service
      Conflicts=shutdown.target
      Before=shutdown.target

      [Timer]
      OnBootSec=15m
      OnUnitActiveSec=30m
      Persistent=true
      Unit=t3code-ghostship-agent-sync.service

      [Install]
      WantedBy=multi-user.target
      EOF
      cat > etc/systemd/system/t3code-tool-update-restart.service <<'EOF'
      [Unit]
      Description=Restart T3 Code after queued maintenance becomes idle
      DefaultDependencies=no
      After=t3code-bootstrap.service
      Requires=t3code-bootstrap.service
      Conflicts=shutdown.target
      Before=shutdown.target

      [Service]
      Type=oneshot
      Environment=PATH=${t3codePath}:/home/t3code/.local/bin:/home/t3code/.local/share/t3code-tools/npm/bin:/bin:/usr/bin
      ExecStart=${managedBin}/t3code-tool-update-restart
      StandardOutput=append:/home/t3code/.t3code-container/logs/t3code-tool-update-restart.log
      StandardError=append:/home/t3code/.t3code-container/logs/t3code-tool-update-restart.log
      TasksMax=infinity
      EOF
      cat > etc/systemd/system/t3code-tool-update-restart.timer <<'EOF'
      [Unit]
      Description=Apply queued T3 Code maintenance when idle
      DefaultDependencies=no
      After=t3code-bootstrap.service
      Conflicts=shutdown.target
      Before=shutdown.target

      [Timer]
      OnBootSec=2m
      OnUnitActiveSec=1m
      Unit=t3code-tool-update-restart.service

      [Install]
      WantedBy=multi-user.target
      EOF
      cat > etc/systemd/system/t3code-server-monitor.service <<'EOF'
      [Unit]
      Description=Monitor T3 Code server and agent tools
      DefaultDependencies=no
      After=t3code-server.service
      Conflicts=shutdown.target
      Before=shutdown.target

      [Service]
      Type=oneshot
      Environment=PATH=${t3codePath}:/home/t3code/.local/bin:/home/t3code/.local/share/t3code-tools/npm/bin:/bin:/usr/bin
      ExecStart=${managedBin}/t3code-server-monitor
      StandardOutput=append:/home/t3code/.t3code-container/logs/t3code-server-monitor.log
      StandardError=append:/home/t3code/.t3code-container/logs/t3code-server-monitor.log
      TasksMax=infinity
      EOF
      cat > etc/systemd/system/t3code-server-monitor.timer <<'EOF'
      [Unit]
      Description=Periodic T3 Code server monitor
      DefaultDependencies=no
      After=t3code-server.service
      Conflicts=shutdown.target
      Before=shutdown.target

      [Timer]
      OnBootSec=2m
      OnUnitActiveSec=1m
      Unit=t3code-server-monitor.service

      [Install]
      WantedBy=multi-user.target
      EOF
      cat > etc/systemd/system/t3code-process-memory-guard.service <<'EOF'
      [Unit]
      Description=Contain oversized T3 Code child processes
      DefaultDependencies=no
      After=t3code-server.service
      Conflicts=shutdown.target
      Before=shutdown.target

      [Service]
      Type=oneshot
      ExecStart=${managedBin}/t3code-process-memory-guard
      StandardOutput=append:/home/t3code/.t3code-container/logs/t3code-process-memory-guard.log
      StandardError=append:/home/t3code/.t3code-container/logs/t3code-process-memory-guard.log
      UMask=0077
      TimeoutStartSec=10s
      TasksMax=256
      EOF
      cat > etc/systemd/system/t3code-process-memory-guard.timer <<'EOF'
      [Unit]
      Description=Check T3 Code child memory every 5 seconds
      DefaultDependencies=no
      After=t3code-server.service
      Conflicts=shutdown.target
      Before=shutdown.target

      [Timer]
      OnBootSec=15s
      OnUnitActiveSec=5s
      AccuracySec=1s
      Unit=t3code-process-memory-guard.service

      [Install]
      WantedBy=multi-user.target
      EOF
      cat > etc/systemd/system/t3code-retention.service <<'EOF'
      [Unit]
      Description=Retain T3 Code logs and archive or delete old threads
      DefaultDependencies=no
      After=t3code-server.service
      Requires=t3code-bootstrap.service
      Conflicts=shutdown.target
      Before=shutdown.target

      [Service]
      Type=oneshot
      User=t3code
      Group=t3code
      Environment=PATH=${t3codePath}:/home/t3code/.local/bin:/home/t3code/.local/share/t3code-tools/npm/bin:/bin:/usr/bin
      Environment=HOME=/home/t3code
      Environment=T3CODE_HOME=/home/t3code/.t3
      ExecStart=${managedBin}/t3code-retention
      StandardOutput=append:/home/t3code/.t3code-container/logs/t3code-retention.log
      StandardError=append:/home/t3code/.t3code-container/logs/t3code-retention.log
      TasksMax=infinity
      TimeoutStartSec=30m
      EOF
      cat > etc/systemd/system/t3code-retention.timer <<'EOF'
      [Unit]
      Description=Daily T3 Code retention
      DefaultDependencies=no
      After=t3code-server.service
      Conflicts=shutdown.target
      Before=shutdown.target

      [Timer]
      OnBootSec=25m
      OnUnitActiveSec=24h
      Persistent=true
      Unit=t3code-retention.service

      [Install]
      WantedBy=multi-user.target
      EOF
      cat > etc/systemd/system/t3code-free-instance.service <<'EOF'
      [Unit]
      Description=Reconcile the one-off free-worker T3 provider instance
      DefaultDependencies=no
      After=t3code-container-setup.service t3code-server.service
      Requires=t3code-container-setup.service
      Conflicts=shutdown.target
      Before=shutdown.target

      [Service]
      Type=oneshot
      User=t3code
      Group=t3code
      Environment=HOME=/home/t3code
      Environment=USER=t3code
      Environment=XDG_RUNTIME_DIR=/run/user/3000
      Environment=DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/3000/bus
      Environment=OPENCODE_AUTOMATION_DIR=/home/t3code/.automation
      Environment=PATH=${t3codePath}:/home/t3code/.local/bin:/home/t3code/.local/share/t3code-tools/npm/bin:/bin:/usr/bin
      ExecStart=${managedBin}/t3code-free-instance-reconcile
      StandardOutput=append:/home/t3code/.t3code-container/logs/t3code-free-instance.log
      StandardError=append:/home/t3code/.t3code-container/logs/t3code-free-instance.log
      TasksMax=infinity
      TimeoutStartSec=5m
      EOF
      cat > etc/systemd/system/t3code-free-instance.timer <<'EOF'
      [Unit]
      Description=Reconcile the one-off free-worker T3 provider instance
      DefaultDependencies=no
      After=t3code-container-setup.service
      Conflicts=shutdown.target
      Before=shutdown.target

      [Timer]
      OnBootSec=2m
      OnUnitActiveSec=15m
      Unit=t3code-free-instance.service

      [Install]
      WantedBy=multi-user.target
      EOF
      cat > etc/systemd/system/multi-user.target <<'EOF'
      [Unit]
      Description=T3 Code Multi-User System
      DefaultDependencies=no
      Wants=t3code-container-setup.service nix-daemon.socket nix-daemon.service user@3000.service t3code-engine-ready.service t3code-bootstrap.service t3code-server.service t3code-access-proxy.service t3code-tool-auto-update.timer t3code-provider-update-watch.timer t3code-ghostship-agent-sync.timer t3code-tool-update-restart.timer t3code-server-monitor.timer t3code-process-memory-guard.timer t3code-retention.timer t3code-free-instance.timer
      After=t3code-container-setup.service nix-daemon.socket user@3000.service t3code-engine-ready.service
      AllowIsolate=yes
      EOF
      ln -s multi-user.target etc/systemd/system/default.target
      ln -s ../t3code-container-setup.service etc/systemd/system/multi-user.target.wants/t3code-container-setup.service
      ln -s ../nix-daemon.socket etc/systemd/system/multi-user.target.wants/nix-daemon.socket
      ln -s ../nix-daemon.service etc/systemd/system/multi-user.target.wants/nix-daemon.service
      ln -s ../user@.service etc/systemd/system/multi-user.target.wants/user@3000.service
      ln -s ../t3code-engine-ready.service etc/systemd/system/multi-user.target.wants/t3code-engine-ready.service
      ln -s ../t3code-bootstrap.service etc/systemd/system/multi-user.target.wants/t3code-bootstrap.service
      ln -s ../t3code-server.service etc/systemd/system/multi-user.target.wants/t3code-server.service
      ln -s ../t3code-access-proxy.service etc/systemd/system/multi-user.target.wants/t3code-access-proxy.service
      ln -s ../t3code-tool-auto-update.timer etc/systemd/system/multi-user.target.wants/t3code-tool-auto-update.timer
      ln -s ../t3code-provider-update-watch.timer etc/systemd/system/multi-user.target.wants/t3code-provider-update-watch.timer
      ln -s ../t3code-ghostship-agent-sync.timer etc/systemd/system/multi-user.target.wants/t3code-ghostship-agent-sync.timer
      ln -s ../t3code-tool-update-restart.timer etc/systemd/system/multi-user.target.wants/t3code-tool-update-restart.timer
      ln -s ../t3code-server-monitor.timer etc/systemd/system/multi-user.target.wants/t3code-server-monitor.timer
      ln -s ../t3code-process-memory-guard.timer etc/systemd/system/multi-user.target.wants/t3code-process-memory-guard.timer
      ln -s ../t3code-retention.timer etc/systemd/system/multi-user.target.wants/t3code-retention.timer
      ln -s ../t3code-free-instance.timer etc/systemd/system/multi-user.target.wants/t3code-free-instance.timer
    '';
    fakeRootCommands = ''
      chown -R root:root nix/store nix/var/log/nix nix/var/nix
      chmod -R u+rwX,go+rX nix/store nix/var/log/nix nix/var/nix
      chown 0:0 usr/bin/sudo
      chmod 4755 usr/bin/sudo
    '';
    config = {
      Cmd = [ "${t3codeEntrypoint}/bin/t3code-systemd-entrypoint" ];
      Env = [
        "HOME=/home/t3code"
        "USER=t3code"
        "CONTAINER_HOST=unix:///var/run/podman/podman.sock"
        "PODMAN_COMPOSE_PROVIDER=${managedBin}/podman-compose"
        "XDG_RUNTIME_DIR=/run/user/3000"
        "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/3000/bus"
        "XDG_CONFIG_HOME=/home/t3code/.config"
        "XDG_STATE_HOME=/home/t3code/.local/state"
        "XDG_CACHE_HOME=/home/t3code/.cache"
        "XDG_DATA_HOME=/home/t3code/.local/share"
        "NPM_CONFIG_PREFIX=/home/t3code/.local/share/t3code-tools/npm"
        "npm_config_prefix=/home/t3code/.local/share/t3code-tools/npm"
        "OPENCODE_AUTOMATION_DIR=/home/t3code/.automation"
        "PATH=${t3codePath}:/home/t3code/.local/bin:/home/t3code/.local/share/t3code-tools/npm/bin:/bin:/usr/bin"
        "NIX_SSL_CERT_FILE=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
        "SSL_CERT_FILE=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
        "NIX_CONFIG=experimental-features = nix-command flakes"
        "NIX_REMOTE=daemon"
        "T3CODE_HOME=/home/t3code/.t3"
        "T3CODE_HOST=127.0.0.1"
        "T3CODE_PORT=3774"
        "T3CODE_NO_BROWSER=true"
      ];
      WorkingDir = "/home/t3code";
      ExposedPorts = {
        "3773/tcp" = { };
      };
    };
  };

  t3codeImage = pkgs.dockerTools.buildLayeredImageWithNixDb imageArgs;
  t3codeDeploymentId = builtins.hashString "sha256" (toString t3codeImage);

in {
  inherit imageArgs;
  image = t3codeImage;
  contents = t3codeImageContents;
  deploymentId = t3codeDeploymentId;
}
