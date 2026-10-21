# SIEM collection: everything relevant to spotting an intrusion, shipped by one
# native Vector service (no root) into VictoriaLogs, plus host and container
# metrics into VictoriaMetrics. Secrets are redacted before storage.
#
# Sources: the whole journal (kernel audit records including AppArmor and the
# watch rules below, sshd, systemd, firewall refusals, Podman events, Falco and
# every container's output) and the logs that exist only as files (Plex
# requests and server log, Muximux nginx access and error logs).
# Not collected: qBittorrent's log is 0600 to its app user; its WebUI sits
# behind Cloudflare Access.
{ config, lib, pkgs, ... }:
let
  plexLogs = "/srv/apps/plex/Library/Application Support/Plex Media Server/Logs";
  # Outside the root-only store directory: node_exporter must traverse it.
  textfile = "/var/lib/ghostship-container-metrics";
in
{
  services.vector = {
    enable = true;
    journaldAccess = true;
    settings = {
      data_dir = "/var/lib/vector";
      sources = {
        journal = {
          type = "journald";
          current_boot_only = false;
          exclude_units = [ "vector.service" ];
        };
        plex = {
          type = "file";
          include = [ "${plexLogs}/Plex Media Server.log" ];
          read_from = "beginning";
        };
        muximux_nginx = {
          type = "file";
          include = [
            "/srv/apps/muximux/log/nginx/access.log"
            "/srv/apps/muximux/log/nginx/error.log"
          ];
          read_from = "beginning";
        };
        node = {
          type = "prometheus_scrape";
          endpoints = [ "http://127.0.0.1:9100/metrics" ];
          scrape_interval_secs = 30;
        };
        vector_metrics.type = "internal_metrics";
      };
      transforms = {
        journal_shape = {
          type = "remap";
          inputs = [ "journal" ];
          file = ./vector/journal.vrl;
        };
        plex_shape = {
          type = "remap";
          inputs = [ "plex" ];
          file = ./vector/plex.vrl;
        };
        nginx_shape = {
          type = "remap";
          inputs = [ "muximux_nginx" ];
          file = ./vector/nginx.vrl;
        };
        redacted = {
          type = "remap";
          inputs = [ "journal_shape" "plex_shape" "nginx_shape" ];
          file = ./vector/redact.vrl;
        };
      };
      sinks = {
        victorialogs = {
          type = "http";
          inputs = [ "redacted" ];
          uri = "http://127.0.0.1:9428/insert/jsonline?_stream_fields=host,source,stream&_msg_field=message&_time_field=timestamp";
          encoding.codec = "json";
          framing.method = "newline_delimited";
          compression = "gzip";
          healthcheck.enabled = false;
          # Keep events across a store restart instead of dropping them.
          buffer = {
            type = "disk";
            max_size = 2147483648;
            when_full = "block";
          };
        };
        victoriametrics = {
          type = "prometheus_remote_write";
          inputs = [ "node" "vector_metrics" ];
          endpoint = "http://127.0.0.1:8428/api/v1/write";
          healthcheck.enabled = false;
        };
      };
    };
  };

  # Vector only reads and sends to loopback: no capabilities, no new privileges.
  systemd.services.vector.serviceConfig = {
    AmbientCapabilities = lib.mkForce "";
    CapabilityBoundingSet = "";
    NoNewPrivileges = true;
    ProtectKernelTunables = true;
    ProtectKernelModules = true;
    ProtectControlGroups = true;
    RestrictAddressFamilies = [ "AF_INET" "AF_INET6" "AF_UNIX" ];
    RestrictNamespaces = true;
    LockPersonality = true;
    MemoryDenyWriteExecute = true;
    SystemCallArchitectures = "native";
  };

  services.prometheus.exporters.node = {
    enable = true;
    listenAddress = "127.0.0.1";
    port = 9100;
    enabledCollectors = [ "systemd" ];
    extraFlags = [ "--collector.textfile.directory=${textfile}" ];
  };

  # A short-lived root job holds the Podman API, so no long-lived SIEM service
  # does (it could create and exec containers). It writes the container
  # metadata the alert bridge resolves addresses from, and the per-container
  # counters node_exporter exports (see podman-snapshot.py).
  systemd.services.ghostship-podman-snapshot = {
    description = "Container metadata snapshot and resource counters for the SIEM";
    after = [ "podman.socket" ];
    path = [ config.virtualisation.podman.package ];
    serviceConfig = {
      Type = "oneshot";
      ExecStart = "${pkgs.python3}/bin/python3 ${./podman-snapshot.py} /run/ghostship-podman/containers.json ${textfile}/containers.prom";
      RuntimeDirectory = "ghostship-podman";
      RuntimeDirectoryMode = "0755";
      RuntimeDirectoryPreserve = true;
      Nice = 10;
      ProtectHome = true;
      PrivateTmp = true;
      TimeoutStartSec = "2min";
    };
  };
  systemd.timers.ghostship-podman-snapshot = {
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnBootSec = "1min";
      OnUnitActiveSec = "30s";
      AccuracySec = "1s";
    };
  };
  systemd.tmpfiles.rules = [ "d ${textfile} 0755 root root -" ];

  # Intrusion-relevant host changes. Paths must exist or auditctl rejects the
  # whole rule set. NixOS rewrites /etc on each switch, so identity and SSH
  # watches also fire during deployments; alerts correlate them with switches.
  security.audit = {
    # A single complain-mode app start overflowed 8192 (185 lost, 2026-10-21).
    backlogLimit = 32768;
    rules = [
      "-w /etc/passwd -p wa -k identity"
      "-w /etc/shadow -p wa -k identity"
      "-w /etc/group -p wa -k identity"
      "-w /etc/sudoers -p wa -k privilege"
      "-w /etc/ssh/ -p wa -k sshd"
      "-w /root/.ssh/ -p wa -k ssh_keys"
      "-w /home/nixos/.ssh/ -p wa -k ssh_keys"
      # Persistence: runtime units and drop-ins, and the system profile (new generations).
      "-w /run/systemd/system/ -p wa -k persistence"
      "-w /nix/var/nix/profiles/ -p wa -k system_profile"
      "-a always,exit -F arch=b64 -S init_module,finit_module -k module_load"
      "-a always,exit -F arch=b64 -S delete_module -k module_unload"
      "-a always,exit -F arch=b64 -S kexec_load,kexec_file_load -k kexec"
      # PTRACE_ATTACH (0x10) and PTRACE_SEIZE (0x4206): debugger-style process injection.
      "-a always,exit -F arch=b64 -S ptrace -F a0=0x10 -k ptrace_attach"
      "-a always,exit -F arch=b64 -S ptrace -F a0=0x4206 -k ptrace_attach"
    ];
  };

  # Connections the host refused: probes from containers or the LAN.
  networking.firewall.logRefusedConnections = true;
}
