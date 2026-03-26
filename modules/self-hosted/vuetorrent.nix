{ config, lib, pkgs, ... }:

let
  vuetorrent-config-script = pkgs.writeShellScriptBin "vuetorrent-config.sh" ''
    #!/bin/sh
    set -eu
    # qBittorrent (VueTorrent) configuration

    CONFIG_DIR="/srv/apps/vuetorrent"
    CONFIG_FILE="$CONFIG_DIR/qBittorrent/qBittorrent.conf"
    UI_DIR="$CONFIG_DIR/ui"

    # 1. Ensure directories exist
    mkdir -p "$CONFIG_DIR/qBittorrent" "$UI_DIR"
    chown -R 3000:3000 "$CONFIG_DIR"

    # 2. Download VueTorrent UI if missing
    if [ ! -f "$UI_DIR/index.html" ]; then
      echo "Downloading VueTorrent UI..."
      TEMP_ZIP=$(mktemp)
      ${pkgs.curl}/bin/curl -L "https://github.com/WDaan/VueTorrent/releases/latest/download/vuetorrent.zip" -o "$TEMP_ZIP"
      TEMP_EXTRACT=$(mktemp -d)
      ${pkgs.unzip}/bin/unzip -o "$TEMP_ZIP" -d "$TEMP_EXTRACT"
      
      # The zip usually contains a 'vuetorrent' folder with a 'public' subfolder
      if [ -d "$TEMP_EXTRACT/vuetorrent/public" ]; then
        cp -r "$TEMP_EXTRACT/vuetorrent/public/." "$UI_DIR/"
      elif [ -d "$TEMP_EXTRACT/vuetorrent" ]; then
        cp -r "$TEMP_EXTRACT/vuetorrent/." "$UI_DIR/"
      else
        cp -r "$TEMP_EXTRACT/." "$UI_DIR/"
      fi
      
      rm -rf "$TEMP_EXTRACT" "$TEMP_ZIP"
      chown -R 3000:3000 "$UI_DIR"
      echo "VueTorrent UI downloaded and extracted"
    fi

    # 3. Update config if it exists
    if [ -f "$CONFIG_FILE" ]; then
      echo "Surgically updating VueTorrent config..."
      ${pkgs.ghostship-config}/bin/ghostship-config set "$CONFIG_FILE" \
        WebUI.Port=literal:5000 \
        WebUI.AuthSubnetWhitelist=literal:0.0.0.0/0 \
        WebUI.AuthSubnetWhitelistEnabled=literal:true \
        WebUI.CSRFProtection=literal:false \
        WebUI.ClickjackingProtection=literal:false \
        WebUI.HostHeaderValidation=literal:false \
        WebUI.AlternativeUIEnabled=literal:true \
        WebUI.RootFolder=literal:/vuetorrent-ui \
        WebUI.Username=literal:admin
      
      echo "VueTorrent config updated"
    fi
  '';
in
{
  virtualisation.oci-containers.containers."vuetorrent" = {
    image = "lscr.io/linuxserver/qbittorrent:latest";
    user = "3000:3000";
    extraOptions = [
      "--network=container:gluetun"
      "--health-cmd=wget -q --spider https://google.com || exit 1"
      "--health-interval=1m"
      "--health-timeout=10s"
      "--health-retries=3"
      "--health-start-period=30s"
    ];
    environment = {
      TZ = "UTC";
      PUID = "3000";
      PGID = "3000";
      WEBUI_PORT = "5000";
    };
    volumes = [
      "/srv/apps/vuetorrent:/config"
      "/srv/apps/vuetorrent/ui:/vuetorrent-ui:ro"
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
    "d /srv/apps/vuetorrent/ui 0755 apps apps -"
  ];

  system.activationScripts.vuetorrent-config = {
    text = ''
      ${vuetorrent-config-script}/bin/vuetorrent-config.sh
    '';
  };
}
