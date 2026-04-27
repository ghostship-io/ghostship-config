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
        Preferences.Connection\\GlobalDLLimit=literal:10240
      )

      ${pkgs.ghostship-config}/bin/ghostship-config set "$CONFIG_FILE" "''${vt_args[@]}"
      
      echo "VueTorrent config updated"
    fi
  '';

  vuetorrent-prestart-script = pkgs.writeShellScriptBin "vuetorrent-prestart.sh" ''
    #!/bin/sh
    set -eu

    CONFIG_FILE="/srv/apps/vuetorrent/qBittorrent/qBittorrent.conf"
    TUN_INTERFACE="tun0"
    TUN_IP=""

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
      DOCKER_MODS = "ghcr.io/vuetorrent/vuetorrent-lsio-mod:latest";
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
