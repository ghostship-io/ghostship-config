{ config, pkgs, ... }:

let
  plex-config-script = pkgs.writeShellScriptBin "plex-config.sh" ''
    #!/bin/sh
    set -eu

    CONFIG_DIR="/srv/apps/plex"
    PMS_DIR="$CONFIG_DIR/Library/Application Support/Plex Media Server"
    PREFS_FILE="$PMS_DIR/Preferences.xml"

    # Apply yq transformations to the Preferences.xml
    if [ -f "$PREFS_FILE" ]; then
      echo "Updating Plex Preferences.xml via ghostship-config..."
      
      plex_args=(
        Preferences.@FriendlyName=literal:"Ghostship Plex"
        Preferences.@LanNetworksBandwidth=literal:"192.168.200.0/255.255.255.0,10.89.0.0/255.255.255.0"
        Preferences.@customConnections=literal:http://192.168.200.135:32400
        Preferences.@allowedNetworks=literal:"192.168.200.0/255.255.255.0,10.89.0.0/255.255.255.0"
        Preferences.@lanNetworks=literal:192.168.200.0/255.255.255.0
        Preferences.@ManualPortMappingMode=literal:1
        Preferences.@TranscoderQuality=literal:1
        Preferences.@ButlerStartHour=literal:3
        Preferences.@ButlerEndHour=literal:6
        Preferences.@ButlerTaskRefreshLibraries=literal:1
        Preferences.@FSEventLibraryUpdatesEnabled=literal:1
        Preferences.@ScheduledLibraryUpdateInterval=literal:21600
        Preferences.@GenerateBIFBehavior=literal:never
        Preferences.@GenerateVADBehavior=literal:scheduled
        Preferences.@AcceptedEULA=literal:1
      )

      ${pkgs.ghostship-config}/bin/ghostship-config set "$PREFS_FILE" "${plex_args[@]}"

      # Ensure permissions are correct after yq edit
      chown 3000:3000 "$PREFS_FILE"
      chmod 600 "$PREFS_FILE"
      echo "Plex Preferences.xml updated"
    else
      echo "Plex Preferences.xml not found at $PREFS_FILE, skipping update"
    fi
  '';
in
{
  virtualisation.oci-containers.containers."plex" = {
    image = "lscr.io/linuxserver/plex:latest";
    user = "3000:3000";
    extraOptions = [
      "--network=ghostship_net"
    ];
    ports = [
      "32400:32400"
      "1900:1900/udp"
      "3005:3005"
      "5353:5353/udp"
      "8324:8324"
      "32410:32410/udp"
      "32412:32412/udp"
      "32413:32413/udp"
      "32414:32414/udp"
      "32469:32469"
    ];
    environment = {
      PUID = "3000";
      PGID = "3000";
      TZ = "UTC";
      VERSION = "latest";
    };
    environmentFiles = [
      "/run/secrets/plex-secrets"
    ];
    devices = [
      "/dev/dri:/dev/dri"
    ];
    volumes = [
      "/srv/apps/plex:/config:rw"
      "/mnt/share/Library:/library:rw"
    ];
  };

  systemd.services.podman-plex = {
    after = [ "mnt-share.mount" ];
    wants = [ "mnt-share.mount" ];
  };

  systemd.tmpfiles.rules = [
    "d /srv/apps/plex 0755 apps apps -"
    "d '/srv/apps/plex/Library' 0755 apps apps -"
    "d '/srv/apps/plex/Library/Application Support' 0755 apps apps -"
    "d '/srv/apps/plex/Library/Application Support/Plex Media Server' 0755 apps apps -"
    "d '/srv/apps/plex/Library/Application Support/Plex Media Server/Plug-in Support' 0755 apps apps -"
    "d '/srv/apps/plex/Library/Application Support/Plex Media Server/Plug-in Support/Databases' 0755 apps apps -"
  ];

  system.activationScripts.plex-config = {
    text = ''
      ${plex-config-script}/bin/plex-config.sh
    '';
  };
}
