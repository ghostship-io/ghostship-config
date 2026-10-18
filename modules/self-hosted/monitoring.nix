{
  config,
  lib,
  pkgs,
  ...
}:
let
  secrets = config.ghostship.selfHostedSecrets.projections.monitoring.path;
  python = pkgs.python3.withPackages (ps: [
    ps.python-socketio
    ps.requests
    ps.websocket-client
  ]);
  provision = pkgs.writeShellScriptBin "ghostship-monitoring-provision" ''
    set -euo pipefail
    set -a
    . ${secrets}
    set +a
    export KUMA_URL="http://$(${pkgs.podman}/bin/podman inspect uptime-kuma --format '{{(index .NetworkSettings.Networks "ghostship_net").IPAddress}}'):3001"
    exec ${python}/bin/python ${./monitoring-provision.py} ${config.ghostship.appRegistryFile}
  '';
  alert = pkgs.writeShellApplication {
    name = "ghostship-alert";
    runtimeInputs = [
      pkgs.curl
      pkgs.podman
    ];
    excludeShellChecks = [ "SC1091" ];
    text = ''
      set -a
      . ${secrets}
      set +a
      address=$(podman inspect ntfy --format '{{(index .NetworkSettings.Networks "ghostship_net").IPAddress}}')
      # Credential config travels over stdin instead of appearing in argv.
      printf 'user = "publisher:%s"\n' "$NTFY_PUBLISH_PASSWORD" |
        curl --config - --fail --silent --show-error --max-time 15 \
          --data-binary "$*" "http://$address:8080/operations"
    '';
  };
in
{
  environment.systemPackages = [
    provision
    alert
  ];
  ghostship.apps.uptime-kuma = {
    name = "Uptime Kuma";
    group = "Infrastructure";
    description = "Service Monitoring";
    icon = "sh-uptime-kuma";
    order = 180;
    hostname = "uptime.ghostship.io";
    origin = "http://muximux:80";
    muximux = {
      icon = "fa-heartbeat";
    };
  };
  ghostship.apps.ntfy = {
    apparmorProfile = "ghostship-ntfy";
    healthPath = "/v1/health";
    name = "ntfy";
    group = "Infrastructure";
    description = "Android Notifications";
    icon = "sh-ntfy";
    order = 190;
    hostname = "ntfy.ghostship.io";
    origin = "http://ntfy:8080";
    muximux = {
      icon = "fa-bell";
    };
  };

  virtualisation.oci-containers.containers = {
    uptime-kuma = {
      podman.sdnotify = "healthy";
      image = "docker.io/louislam/uptime-kuma:2";
      pull = "always";
      labels."io.containers.autoupdate" = "registry";
      user = "3000:3000";
      environment = {
        UPTIME_KUMA_DB_TYPE = "sqlite";
        TZ = "Pacific/Honolulu";
      };
      volumes = [ "/srv/apps/uptime-kuma:/app/data:rw" ];
      extraOptions = [
        "--network=ghostship_net"
        "--health-cmd=node extra/healthcheck.js"
        "--health-interval=30s"
        "--health-timeout=10s"
        "--health-retries=5"
        "--health-start-period=2m"
        "--health-on-failure=kill"
      ];
    };
    ntfy = {
      podman.sdnotify = "healthy";
      image = "docker.io/binwiederhier/ntfy:latest";
      pull = "always";
      labels."io.containers.autoupdate" = "registry";
      user = "3000:3000";
      cmd = [ "serve" ];
      volumes = [
        "/srv/apps/ntfy:/var/lib/ntfy:rw"
        "/run/ghostship-ntfy:/etc/ntfy:ro"
      ];
      extraOptions = [
        "--network=ghostship_net"
        "--health-cmd=wget -q -O /dev/null http://127.0.0.1:8080/v1/health"
        "--health-interval=30s"
        "--health-timeout=10s"
        "--health-retries=5"
        "--health-start-period=30s"
        "--health-on-failure=kill"
      ];
    };
  };
  systemd.tmpfiles.rules = [
    "d /var/lib/ghostship-monitoring 0700 root root -"
    "d /srv/apps/uptime-kuma 0700 apps apps -"
    "d /srv/apps/ntfy 0700 apps apps -"
    "d /run/ghostship-ntfy 0750 root apps -"
  ];
  systemd.services.podman-ntfy.preStart = ''
    set -euo pipefail
    . ${secrets}
    : "''${NTFY_ADMIN_HASH:?}" "''${NTFY_PUBLISH_HASH:?}" "''${NTFY_READER_HASH:?}"
    umask 077
    cat > /run/ghostship-ntfy/server.yml.new <<EOF
    base-url: https://ntfy.ghostship.io
    listen-http: ':8080'
    behind-proxy: true
    auth-file: /var/lib/ntfy/auth.db
    auth-default-access: deny-all
    enable-login: true
    enable-signup: false
    cache-file: /var/lib/ntfy/cache.db
    cache-duration: 72h
    auth-users:
      - 'the owner:$NTFY_ADMIN_HASH:admin'
      - 'publisher:$NTFY_PUBLISH_HASH:user'
      - 'android:$NTFY_READER_HASH:user'
    auth-access:
      - 'publisher:operations:write-only'
      - 'android:operations:read-only'
    EOF
    chown root:apps /run/ghostship-ntfy/server.yml.new
    chmod 640 /run/ghostship-ntfy/server.yml.new
    mv /run/ghostship-ntfy/server.yml.new /run/ghostship-ntfy/server.yml
  '';
  systemd.services.ghostship-monitoring-provision = {
    description = "Provision Ghostship monitors without overwriting user settings";
    requires = [
      "podman-uptime-kuma.service"
      "podman-ntfy.service"
    ];
    after = [
      "podman-uptime-kuma.service"
      "podman-ntfy.service"
    ];
    wantedBy = [ "multi-user.target" ];
    serviceConfig = {
      Type = "oneshot";
      ExecStart = "${provision}/bin/ghostship-monitoring-provision";
      TimeoutStartSec = "3min";
      UMask = "0077";
    };
  };
  systemd.services."ghostship-failure@" = {
    description = "Notify about failed Ghostship service %i";
    serviceConfig = {
      Type = "oneshot";
      ExecStart = "${alert}/bin/ghostship-alert Service %i failed on chill-penguin";
    };
  };
  systemd.services.ghostship-monitoring-heartbeats = {
    after = [ "ghostship-monitoring-provision.service" ];
    serviceConfig = {
      Type = "oneshot";
      ExecStart = "${pkgs.python3}/bin/python ${./monitoring-heartbeats.py}";
      TimeoutStartSec = "1min";
    };
    path = [ pkgs.podman ];
    unitConfig.ConditionPathExists = "/var/lib/ghostship-monitoring/push.json";
  };
  systemd.timers.ghostship-monitoring-heartbeats = {
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnBootSec = "5min";
      OnUnitActiveSec = "5min";
    };
  };
  systemd.services.podman-auto-update.postStart = ''
    ${pkgs.coreutils}/bin/install -d -m0700 /var/lib/ghostship-monitoring
    ${pkgs.coreutils}/bin/date +%s > /var/lib/ghostship-monitoring/last-update-success
  '';
  systemd.services.ghostship-backup-backup.onFailure = [ "ghostship-failure@%n.service" ];
  systemd.services.ghostship-backup-check.onFailure = [ "ghostship-failure@%n.service" ];
  systemd.services.ghostship-backup-prune.onFailure = [ "ghostship-failure@%n.service" ];
  systemd.services.ghostship-backup-sample.onFailure = [ "ghostship-failure@%n.service" ];
  systemd.services.podman-auto-update.onFailure = [ "ghostship-failure@%n.service" ];
  systemd.services.ghostship-monitoring-provision.onFailure = [ "ghostship-failure@%n.service" ];
  systemd.services.nixos-upgrade = lib.mkIf config.system.autoUpgrade.enable {
    onFailure = [ "ghostship-failure@%n.service" ];
  };
}
