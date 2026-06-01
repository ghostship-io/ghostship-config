{
  config,
  lib,
  pkgs,
  ...
}:

let
  vuetorrent-ui = pkgs.fetchzip {
    url = "https://github.com/VueTorrent/VueTorrent/releases/download/v2.33.0/vuetorrent.zip";
    hash = "sha256-AnQ606UTmm59V9fQEyMDx9WVIjwBNiOFi9rms+RSdNk=";
  };

  qbittorrent-config-script = pkgs.writeShellScriptBin "qbittorrent-config.sh" ''
    #!/bin/sh
    set -eu
    # qBittorrent (VueTorrent) configuration

    OLD_CONFIG_DIR="/srv/apps/vuetorrent"
    CONFIG_DIR="/srv/apps/qbittorrent"
    CONFIG_FILE="$CONFIG_DIR/qBittorrent/qBittorrent.conf"
    LOCK_FILE="$CONFIG_DIR/qBittorrent/lockfile"
    LEGACY_UI_DIR="$CONFIG_DIR/ui"
    LEGACY_RELEASE_MARKER="$CONFIG_DIR/.vuetorrent-release-url"

    if [ -d "$OLD_CONFIG_DIR" ] && [ ! -f "$CONFIG_FILE" ]; then
      if [ -d "$CONFIG_DIR" ] && [ -z "$(${pkgs.findutils}/bin/find "$CONFIG_DIR" -mindepth 1 -maxdepth 1 -print -quit)" ]; then
        ${pkgs.coreutils}/bin/rmdir "$CONFIG_DIR"
      fi
      if [ ! -e "$CONFIG_DIR" ]; then
        ${pkgs.coreutils}/bin/mv "$OLD_CONFIG_DIR" "$CONFIG_DIR"
      fi
    fi

    # 1. Ensure directories exist
    mkdir -p "$CONFIG_DIR/qBittorrent"
    chown -R 3000:3000 "$CONFIG_DIR"

    # 2. Remove the legacy manual VueTorrent download state. The supported
    # Nix store mount now supplies the UI inside the container.
    if [ -e "$LEGACY_UI_DIR" ] || [ -e "$LEGACY_RELEASE_MARKER" ]; then
      echo "Removing legacy VueTorrent UI state..."
      ${pkgs.coreutils}/bin/rm -rf "$LEGACY_UI_DIR" "$LEGACY_RELEASE_MARKER"
    fi

    # 3. Update config if it exists
    if [ -f "$CONFIG_FILE" ]; then
      echo "Surgically updating qBittorrent config..."

      # Remove legacy KV-style lines from the old broken writer.
      ${pkgs.gnused}/bin/sed -i '/^WebUI\./d' "$CONFIG_FILE"

      vt_args=(
        Preferences.WebUI\\Address=literal:*
        Preferences.WebUI\\Port=literal:5000
        Preferences.WebUI\\ServerDomains=literal:*
        Preferences.WebUI\\AuthSubnetWhitelist=literal:127.0.0.0/8,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16
        Preferences.WebUI\\AuthSubnetWhitelistEnabled=literal:true
        Preferences.WebUI\\CSRFProtection=literal:false
        Preferences.WebUI\\ClickjackingProtection=literal:false
        Preferences.WebUI\\HostHeaderValidation=literal:false
        Preferences.WebUI\\ReverseProxySupportEnabled=literal:true
        Preferences.WebUI\\AlternativeUIEnabled=literal:true
        Preferences.WebUI\\RootFolder=literal:/vuetorrent
        Preferences.Queueing\\QueueingEnabled=literal:true
        Preferences.Queueing\\MaxActiveDownloads=literal:5
        Preferences.Queueing\\MaxActiveTorrents=literal:20
        Preferences.Connection\\GlobalDLLimit=literal:20480
        Preferences.Advanced\\RecheckOnCompletion=literal:true
        Preferences.Downloads\\SavePath=literal:/downloads/Torrent
        Preferences.Downloads\\TempPath=literal:/downloads/Torrent/.incomplete
        BitTorrent.Session\\DefaultSavePath=literal:/downloads/Torrent
        BitTorrent.Session\\TempPath=literal:/downloads/Torrent/.incomplete
        BitTorrent.Session\\TempPathEnabled=literal:true
        BitTorrent.Session\\IgnoreSlowTorrentsForQueueing=literal:true
      )

      ${pkgs.ghostship-config}/bin/ghostship-config set "$CONFIG_FILE" "''${vt_args[@]}"
      ${pkgs.gnused}/bin/sed -i 's/^WebUI\\Address = /WebUI\\Address=/' "$CONFIG_FILE"
      ${pkgs.coreutils}/bin/rm -f "$LOCK_FILE"
      
      echo "qBittorrent config updated"
    fi
  '';

  qbittorrent-prestart-script = pkgs.writeShellScriptBin "qbittorrent-prestart.sh" ''
    #!/bin/sh
    set -eu

    CONFIG_FILE="/srv/apps/qbittorrent/qBittorrent/qBittorrent.conf"
    LOCK_FILE="/srv/apps/qbittorrent/qBittorrent/lockfile"
    DOWNLOAD_TEMP_DIR="/mnt/share/Downloads/Torrent/.incomplete"
    TUN_INTERFACE="tun0"
    TUN_IP=""

    ${pkgs.coreutils}/bin/install -d -m 0777 "$DOWNLOAD_TEMP_DIR"

    if [ ! -f "$CONFIG_FILE" ]; then
      exit 0
    fi

    for _ in $(seq 1 30); do
      TUN_IP=$(${pkgs.podman}/bin/podman exec gluetun sh -c "ip -4 -o addr show dev $TUN_INTERFACE 2>/dev/null | tr -s ' ' | cut -d' ' -f4 | cut -d/ -f1 | head -n1" 2>/dev/null || true)
      if [ -n "$TUN_IP" ]; then
        break
      fi
      sleep 1
    done

    if [ -z "$TUN_IP" ]; then
      echo "qBittorrent pre-start could not determine Gluetun $TUN_INTERFACE address; leaving qBittorrent binding unchanged." >&2
      exit 0
    fi

    vt_bind_args=(
      BitTorrent.Session\\Interface=literal:$TUN_INTERFACE
      BitTorrent.Session\\InterfaceName=literal:$TUN_INTERFACE
      BitTorrent.Session\\InterfaceAddress=literal:$TUN_IP
    )

    ${pkgs.ghostship-config}/bin/ghostship-config set "$CONFIG_FILE" "''${vt_bind_args[@]}"
    ${pkgs.gnused}/bin/sed -i 's/^WebUI\\Address = /WebUI\\Address=/' "$CONFIG_FILE"
    ${pkgs.coreutils}/bin/rm -f "$LOCK_FILE"
    echo "Primed qBittorrent binding for $TUN_INTERFACE/$TUN_IP before startup."
  '';
  qbittorrent-auto-resume-script = pkgs.writeShellScriptBin "qbittorrent-auto-resume" ''
    #!/bin/sh
    set -eu

    STATE_DIR="/srv/apps/qbittorrent"
    STATE_FILE="$STATE_DIR/auto-resume-attempts.json"
    QBT_API="http://127.0.0.1:5000/api/v2"

    mkdir -p "$STATE_DIR"

    if [ ! -s "$STATE_FILE" ] || ! ${pkgs.jq}/bin/jq -e 'type == "object"' "$STATE_FILE" >/dev/null 2>&1; then
      printf '{}\n' > "$STATE_FILE"
    fi

    if ! ${pkgs.podman}/bin/podman ps --filter "name=gluetun" --filter "status=running" --format '{{.Names}}' | ${pkgs.gnugrep}/bin/grep -qx gluetun; then
      echo "Gluetun is not running; skipping qBittorrent auto-resume."
      exit 0
    fi

    if ! ${pkgs.podman}/bin/podman ps --filter "name=qbittorrent" --filter "status=running" --format '{{.Names}}' | ${pkgs.gnugrep}/bin/grep -qx qbittorrent; then
      echo "qBittorrent is not running; skipping qBittorrent auto-resume."
      exit 0
    fi

    if ! ${pkgs.podman}/bin/podman exec gluetun wget -qO- "$QBT_API/app/version" >/dev/null 2>&1; then
      echo "qBittorrent API is not reachable; skipping qBittorrent auto-resume."
      exit 0
    fi

    all_torrents=$(${pkgs.podman}/bin/podman exec gluetun wget -qO- "$QBT_API/torrents/info" 2>/dev/null || true)
    if ! printf '%s' "$all_torrents" | ${pkgs.jq}/bin/jq -e 'type == "array"' >/dev/null 2>&1; then
      echo "qBittorrent all-torrents response was not valid JSON; skipping qBittorrent auto-resume."
      exit 0
    fi

    errored_torrents=$(${pkgs.podman}/bin/podman exec gluetun wget -qO- "$QBT_API/torrents/info?filter=errored" 2>/dev/null || true)
    if ! printf '%s' "$errored_torrents" | ${pkgs.jq}/bin/jq -e 'type == "array"' >/dev/null 2>&1; then
      echo "qBittorrent errored-torrents response was not valid JSON; skipping qBittorrent auto-resume."
      exit 0
    fi

    hashes_file=$(mktemp "$STATE_DIR/.auto-resume-hashes.XXXXXX")
    work_state=$(mktemp "$STATE_DIR/.auto-resume-state.XXXXXX")
    next_state=$(mktemp "$STATE_DIR/.auto-resume-next.XXXXXX")
    trap 'rm -f "$hashes_file" "$work_state" "$next_state"' EXIT

    all_hashes=$(printf '%s' "$all_torrents" | ${pkgs.jq}/bin/jq -c '[.[].hash]')
    ${pkgs.jq}/bin/jq --argjson hashes "$all_hashes" \
      'with_entries(select(.key as $hash | $hashes | index($hash)))' \
      "$STATE_FILE" > "$work_state"

    printf '%s' "$errored_torrents" | ${pkgs.jq}/bin/jq -r '.[].hash' > "$hashes_file"

    resumed=0
    while IFS= read -r hash; do
      [ -n "$hash" ] || continue
      attempts=$(${pkgs.jq}/bin/jq -r --arg hash "$hash" '.[$hash] // 0' "$work_state")

      if ${pkgs.podman}/bin/podman exec gluetun wget -qO- --post-data "hashes=$hash" "$QBT_API/torrents/start" >/dev/null 2>&1; then
        next_attempts=$((attempts + 1))
        ${pkgs.jq}/bin/jq --arg hash "$hash" --argjson attempts "$next_attempts" '.[$hash] = $attempts' "$work_state" > "$next_state"
        mv "$next_state" "$work_state"
        echo "Resumed errored qBittorrent torrent $hash (automatic attempt $next_attempts)."
        resumed=$((resumed + 1))
      else
        echo "Failed to resume errored qBittorrent torrent $hash; attempt count unchanged."
      fi
    done < "$hashes_file"

    mv "$work_state" "$STATE_FILE"
    chmod 0644 "$STATE_FILE"
    echo "qBittorrent auto-resume complete: resumed=$resumed."
  '';
in
{
  virtualisation.oci-containers.containers."qbittorrent" = {
    image = "lscr.io/linuxserver/qbittorrent:latest";
    pull = "always";
    labels = {
      "io.containers.autoupdate" = "registry";
    };
    extraOptions = [
      "--network=container:gluetun"
      "--health-cmd=wget -q --spider --tries=1 --timeout=5 http://127.0.0.1:5000/ || exit 1"
      "--health-interval=30s"
      "--health-timeout=10s"
      "--health-retries=5"
      "--health-start-period=1m"
      "--health-on-failure=kill"
    ];
    environment = {
      TZ = "UTC";
      PUID = "3000";
      PGID = "3000";
      WEBUI_PORT = "5000";
    };
    volumes = [
      "/srv/apps/qbittorrent:/config"
      "/mnt/share/Downloads:/downloads"
      "${vuetorrent-ui}:/vuetorrent:ro"
    ];
  };

  systemd.services.podman-qbittorrent = {
    after = [
      "mnt-share.mount"
      "podman-gluetun.service"
    ];
    bindsTo = [ "podman-gluetun.service" ];
    partOf = [ "podman-gluetun.service" ];
    requires = [ "podman-gluetun.service" ];
    wants = [ "mnt-share.mount" ];
    preStart = lib.mkAfter ''
      ${qbittorrent-prestart-script}/bin/qbittorrent-prestart.sh
    '';
  };

  systemd.services.qbittorrent-auto-resume = {
    description = "Resume errored qBittorrent torrents indefinitely";
    after = [
      "podman-gluetun.service"
      "podman-qbittorrent.service"
    ];
    wants = [
      "podman-gluetun.service"
      "podman-qbittorrent.service"
    ];
    serviceConfig = {
      Type = "oneshot";
      ExecStart = "${qbittorrent-auto-resume-script}/bin/qbittorrent-auto-resume";
    };
  };

  systemd.timers.qbittorrent-auto-resume = {
    description = "Periodically resume errored qBittorrent torrents";
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnBootSec = "10m";
      OnUnitActiveSec = "5m";
      Persistent = true;
      Unit = "qbittorrent-auto-resume.service";
    };
  };

  systemd.tmpfiles.rules = [
    "d /srv/apps/qbittorrent 0755 apps apps -"
    "d /srv/apps/qbittorrent/qBittorrent 0755 apps apps -"
  ];

  system.activationScripts.qbittorrent-config = {
    text = ''
      ${qbittorrent-config-script}/bin/qbittorrent-config.sh
    '';
  };
}
