{ config, lib, pkgs, ... }:

let
  vuetorrent-config-script = pkgs.writeShellScriptBin "vuetorrent-config.sh" ''
    #!/bin/sh
    set -eu
    # qBittorrent (VueTorrent) configuration

    CONFIG_DIR="/srv/apps/vuetorrent"
    CONFIG_FILE="$CONFIG_DIR/qBittorrent/qBittorrent.conf"
    LEGACY_UI_DIR="$CONFIG_DIR/ui"
    LEGACY_RELEASE_MARKER="$CONFIG_DIR/.vuetorrent-release-url"

    # 1. Ensure directories exist
    mkdir -p "$CONFIG_DIR/qBittorrent"
    chown -R 3000:3000 "$CONFIG_DIR"

    # 2. Remove the legacy manual VueTorrent download state. The supported
    # LSIO Docker mod now supplies the UI inside the container.
    if [ -e "$LEGACY_UI_DIR" ] || [ -e "$LEGACY_RELEASE_MARKER" ]; then
      echo "Removing legacy VueTorrent UI state..."
      ${pkgs.coreutils}/bin/rm -rf "$LEGACY_UI_DIR" "$LEGACY_RELEASE_MARKER"
    fi

    # 3. Update config if it exists
    if [ -f "$CONFIG_FILE" ]; then
      echo "Surgically updating VueTorrent config..."

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
      
      echo "VueTorrent config updated"
    fi
  '';

  vuetorrent-prestart-script = pkgs.writeShellScriptBin "vuetorrent-prestart.sh" ''
    #!/bin/sh
    set -eu

    CONFIG_FILE="/srv/apps/vuetorrent/qBittorrent/qBittorrent.conf"
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
      echo "VueTorrent pre-start could not determine Gluetun $TUN_INTERFACE address; leaving qBittorrent binding unchanged." >&2
      exit 0
    fi

    vt_bind_args=(
      BitTorrent.Session\\Interface=literal:$TUN_INTERFACE
      BitTorrent.Session\\InterfaceName=literal:$TUN_INTERFACE
      BitTorrent.Session\\InterfaceAddress=literal:$TUN_IP
    )

    ${pkgs.ghostship-config}/bin/ghostship-config set "$CONFIG_FILE" "''${vt_bind_args[@]}"
    echo "Primed VueTorrent binding for $TUN_INTERFACE/$TUN_IP before startup."
  '';
  vuetorrent-auto-resume-script = pkgs.writeShellScriptBin "vuetorrent-auto-resume" ''
    #!/bin/sh
    set -eu

    STATE_DIR="/srv/apps/vuetorrent"
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

    if ! ${pkgs.podman}/bin/podman ps --filter "name=vuetorrent" --filter "status=running" --format '{{.Names}}' | ${pkgs.gnugrep}/bin/grep -qx vuetorrent; then
      echo "VueTorrent is not running; skipping qBittorrent auto-resume."
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
  virtualisation.oci-containers.containers."vuetorrent" = {
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
      "/srv/apps/vuetorrent:/config"
      "/mnt/share/Downloads:/downloads"
    ];
  };

  systemd.services.podman-vuetorrent = {
    after = [ "mnt-share.mount" "podman-gluetun.service" ];
    bindsTo = [ "podman-gluetun.service" ];
    partOf = [ "podman-gluetun.service" ];
    requires = [ "podman-gluetun.service" ];
    wants = [ "mnt-share.mount" ];
    preStart = lib.mkAfter ''
      ${vuetorrent-prestart-script}/bin/vuetorrent-prestart.sh
    '';
  };

  systemd.services.vuetorrent-auto-resume = {
    description = "Resume errored qBittorrent torrents indefinitely";
    after = [
      "podman-gluetun.service"
      "podman-vuetorrent.service"
    ];
    wants = [
      "podman-gluetun.service"
      "podman-vuetorrent.service"
    ];
    serviceConfig = {
      Type = "oneshot";
      ExecStart = "${vuetorrent-auto-resume-script}/bin/vuetorrent-auto-resume";
    };
  };

  systemd.timers.vuetorrent-auto-resume = {
    description = "Periodically resume errored qBittorrent torrents";
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnBootSec = "10m";
      OnUnitActiveSec = "5m";
      Persistent = true;
      Unit = "vuetorrent-auto-resume.service";
    };
  };

  systemd.tmpfiles.rules = [
    "d /srv/apps/vuetorrent 0755 apps apps -"
    "d /srv/apps/vuetorrent/qBittorrent 0755 apps apps -"
  ];

  system.activationScripts.vuetorrent-config = {
    text = ''
      ${vuetorrent-config-script}/bin/vuetorrent-config.sh
    '';
  };
}
