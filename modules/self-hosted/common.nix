{ config, lib, pkgs, ... }:

{
  # Shared configuration for all self-hosted services
  # (Podman is used by default in NixOS)

  # Service user for self-hosted apps
  users.users.apps = {
    isSystemUser = true;
    uid = 3000;
    group = "apps";
    description = "Service user for self-hosted apps";
    shell = "/run/current-system/sw/bin/nologin";
  };
  users.groups.apps.gid = 3000;

  # Common network for all ghostship services
  systemd.services.init-ghostship-net = {
    description = "Create ghostship_net podman network";
    after = [ "network.target" ];
    wantedBy = [ "multi-user.target" ];
    serviceConfig.Type = "oneshot";
    script = ''
      ${pkgs.podman}/bin/podman network inspect ghostship_net >/dev/null 2>&1 || \
      ${pkgs.podman}/bin/podman network create ghostship_net
    '';
  };

  systemd.services.podman-auto-update = {
    description = "Run native Podman auto-update for Ghostship containers";
    after = [ "network-online.target" "init-ghostship-net.service" ];
    wants = [ "network-online.target" "init-ghostship-net.service" ];
    serviceConfig = {
      Type = "oneshot";
      ExecStart = "${pkgs.podman}/bin/podman auto-update";
    };
  };

  systemd.timers.podman-auto-update = {
    description = "Daily native Podman auto-update for Ghostship containers";
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnCalendar = "daily";
      Persistent = true;
      RandomizedDelaySec = "30m";
    };
  };

  # Base directory for all app configurations with strict ownership
  systemd.tmpfiles.rules = [
    "d /srv/apps 0755 apps apps -"
  ];
}
