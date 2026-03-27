{ config, lib, pkgs, ... }:

let
  vuetorrent-config-script = pkgs.writeShellScriptBin "vuetorrent-config.sh" ''
    #!/bin/sh
    set -eu
    # qBittorrent (VueTorrent) configuration

    CONFIG_DIR="/srv/apps/vuetorrent"
    CONFIG_FILE="$CONFIG_DIR/qBittorrent/qBittorrent.conf"
    UI_DIR="$CONFIG_DIR/ui"
    PUBLIC_DIR="$UI_DIR/public"
    RELEASE_MARKER="$CONFIG_DIR/.vuetorrent-release-url"
    ASSET_URL="https://github.com/VueTorrent/VueTorrent/releases/latest/download/vuetorrent.zip"

    # 1. Ensure directories exist
    mkdir -p "$CONFIG_DIR/qBittorrent" "$PUBLIC_DIR"
    chown -R 3000:3000 "$CONFIG_DIR"

    # 2. Refresh VueTorrent only when the upstream release URL changes.
    NEEDS_DOWNLOAD=0
    CURRENT_RELEASE_URL=""
    # We follow redirects to get the stable versioned URL (e.g., .../releases/download/v2.32.1/...)
    # instead of the final signed URL which changes every time due to expiration tokens.
    if CURRENT_RELEASE_URL="$(${pkgs.curl}/bin/curl -fsSLI "$ASSET_URL" | ${pkgs.gnugrep}/bin/grep -i "^location:" | ${pkgs.gnugrep}/bin/grep "/releases/download/" | ${pkgs.coreutils}/bin/head -n 1 | ${pkgs.coreutils}/bin/tr -d '\r' | ${pkgs.gnused}/bin/sed 's/^[Ll]ocation: //')" ; then
      if [ -z "$CURRENT_RELEASE_URL" ]; then
         echo "Could not resolve stable release URL, falling back to basic check."
         if [ ! -f "$PUBLIC_DIR/index.html" ]; then NEEDS_DOWNLOAD=1; fi
      elif [ ! -f "$PUBLIC_DIR/index.html" ] || [ ! -f "$RELEASE_MARKER" ] || [ "$(${pkgs.coreutils}/bin/cat "$RELEASE_MARKER")" != "$CURRENT_RELEASE_URL" ]; then
        NEEDS_DOWNLOAD=1
      fi
    elif [ ! -f "$PUBLIC_DIR/index.html" ]; then
      NEEDS_DOWNLOAD=1
    fi

    if [ "$NEEDS_DOWNLOAD" -eq 1 ]; then
      echo "Downloading VueTorrent UI..."
      rm -rf "$PUBLIC_DIR"
      mkdir -p "$PUBLIC_DIR"
      TEMP_ZIP=$(mktemp)
      ${pkgs.curl}/bin/curl -L "$ASSET_URL" -o "$TEMP_ZIP"
      TEMP_EXTRACT=$(mktemp -d)
      ${pkgs.unzip}/bin/unzip -o "$TEMP_ZIP" -d "$TEMP_EXTRACT"

      # The zip usually contains a 'vuetorrent' folder with a 'public' subfolder.
      # qBittorrent 5.x expects the RootFolder to point DIRECTLY to the directory 
      # containing index.html for it to work correctly without 500 errors.
      if [ -d "$TEMP_EXTRACT/vuetorrent/public" ]; then
        cp -r "$TEMP_EXTRACT/vuetorrent/public/." "$PUBLIC_DIR/"
      elif [ -d "$TEMP_EXTRACT/vuetorrent" ]; then
        cp -r "$TEMP_EXTRACT/vuetorrent/." "$PUBLIC_DIR/"
      else
        cp -r "$TEMP_EXTRACT/." "$PUBLIC_DIR/"
      fi

      rm -rf "$TEMP_EXTRACT" "$TEMP_ZIP"
      chown -R 3000:3000 "$PUBLIC_DIR"
      printf '%s\n' "$CURRENT_RELEASE_URL" > "$RELEASE_MARKER"
      echo "VueTorrent UI downloaded and extracted (Version marker: $CURRENT_RELEASE_URL)"
    fi

    # 3. Update config if it exists
    if [ -f "$CONFIG_FILE" ]; then
      echo "Surgically updating VueTorrent config..."

      # Remove legacy KV-style lines from the old broken writer.
      ${pkgs.gnused}/bin/sed -i '/^WebUI\./d' "$CONFIG_FILE"

      ${pkgs.ghostship-config}/bin/ghostship-config set "$CONFIG_FILE" \
        Preferences.WebUI\\Address=literal:* \
        Preferences.WebUI\\Port=literal:5000 \
        Preferences.WebUI\\ServerDomains=literal:* \
        Preferences.WebUI\\AuthSubnetWhitelist=literal:127.0.0.0/8,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16 \
        Preferences.WebUI\\AuthSubnetWhitelistEnabled=literal:true \
        Preferences.WebUI\\CSRFProtection=literal:false \
        Preferences.WebUI\\ClickjackingProtection=literal:false \
        Preferences.WebUI\\HostHeaderValidation=literal:false \
        Preferences.WebUI\\ReverseProxySupportEnabled=literal:true \
        Preferences.WebUI\\AlternativeUIEnabled=literal:true \
        Preferences.WebUI\\RootFolder=literal:/vuetorrent-ui/public
      
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
      "--health-cmd=wget -q --spider --tries=1 --timeout=5 https://google.com || exit 1"
      "--health-interval=30s"
      "--health-timeout=10s"
      "--health-retries=5"
      "--health-start-period=1m"
    ];
    environment = {
      TZ = "UTC";
      PUID = "3000";
      PGID = "3000";
      WEBUI_PORT = "5000";
    };
    volumes = [
      "/srv/apps/vuetorrent:/config"
      "/srv/apps/vuetorrent/ui/public:/vuetorrent-ui/public:ro"
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
    "d /srv/apps/vuetorrent/ui/public 0755 apps apps -"
  ];

  system.activationScripts.vuetorrent-config = {
    text = ''
      ${vuetorrent-config-script}/bin/vuetorrent-config.sh
    '';
  };
}
