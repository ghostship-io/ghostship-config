# Falco runtime detection: a native service on the host kernel's modern eBPF
# probe (user decision 2026-10-21: no privileged container). Events go to the
# journal as JSON; Vector ships them to VictoriaLogs (siem/collection.nix).
{ pkgs, lib, ... }:
let
  falco = pkgs.callPackage ../../../packages/falco.nix { };
  config = (pkgs.formats.yaml { }).generate "falco.yaml" {
    engine = {
      kind = "modern_ebpf";
      modern_ebpf = {
        cpus_for_each_buffer = 2;
        buf_size_preset = 4;
        drop_failed_exit = false;
      };
    };
    rules_files = [
      "${falco}/share/falco/falco_rules.yaml"
      "${./falco/ghostship_rules.yaml}"
    ];
    load_plugins = [ "container" ];
    plugins = [
      {
        name = "container";
        library_path = "${falco}/share/falco/plugins/libcontainer.so";
        init_config = {
          label_max_len = 100;
          with_size = false;
        };
      }
    ];
    # Notice and above: upstream's informational rules are mostly inventory.
    priority = "notice";
    # Append the container plugin's fields (container id, name, image) to
    # every alert; without this they are missing from the output.
    append_output = [ { suggested_output = true; } ];
    json_output = true;
    json_include_output_property = true;
    json_include_output_fields_property = true;
    json_include_tags_property = true;
    stdout_output.enabled = true;
    syslog_output.enabled = false;
    file_output.enabled = false;
    http_output.enabled = false;
    program_output.enabled = false;
    webserver.enabled = false;
    log_stderr = true;
    log_syslog = false;
    log_level = "info";
    watch_config_files = false;
    # Dropped kernel events mean blind spots: log them (rate limited).
    syscall_event_drops = {
      actions = [ "log" ];
      rate = 0.03333;
      max_burst = 1;
    };
  };
in
{
  systemd.services.falco = {
    description = "Falco runtime security";
    wantedBy = [ "multi-user.target" ];
    after = [ "network.target" "podman.socket" ];
    serviceConfig = {
      ExecStart = "${falco}/bin/falco -c ${config}";
      Restart = "always";
      RestartSec = 10;
      # The eBPF probe and /proc scans need these; nothing else.
      CapabilityBoundingSet = [
        "CAP_BPF"
        "CAP_PERFMON"
        "CAP_SYS_RESOURCE"
        "CAP_SYS_PTRACE"
        "CAP_DAC_READ_SEARCH"
      ];
      NoNewPrivileges = true;
      ProtectSystem = "strict";
      ProtectHome = "read-only";
      PrivateTmp = true;
      ProtectClock = true;
      ProtectHostname = true;
      ProtectKernelModules = true;
      ProtectKernelTunables = true;
      RestrictRealtime = true;
      RestrictNamespaces = true;
      LockPersonality = true;
      RestrictAddressFamilies = [ "AF_UNIX" "AF_NETLINK" "AF_INET" "AF_INET6" ];
      MemoryMax = "1G";
      Nice = 5;
    };
  };
}
