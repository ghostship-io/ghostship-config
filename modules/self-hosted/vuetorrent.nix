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
      )

      ${pkgs.ghostship-config}/bin/ghostship-config set "$CONFIG_FILE" "''${vt_args[@]}"
      
      echo "VueTorrent config updated"
    fi
  '';
in
{
  virtualisation.oci-containers.containers."vuetorrent" = {
    image = "lscr.io/linuxserver/qbittorrent:latest";
    extraOptions = [
      "--network=container:gluetun"
      "--health-cmd=wget -q --spider --tries=1 --timeout=5 https://google.com || exit 1"
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
    wants = [ "mnt-share.mount" ];
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
