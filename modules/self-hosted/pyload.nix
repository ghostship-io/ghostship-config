{ config, pkgs, ... }:

let
  pyloadInitConfigRun =
    let
      upstream = ''
        #!/usr/bin/with-contenv bash
        # shellcheck shell=bash

        # create our folders
        mkdir -p \
            /config/settings \
            /downloads

        # default config file
        cp -n \
            /defaults/pyload.cfg \
            /config/settings/pyload.cfg

        # permissions
        lsiown -R abc:abc \
            /config
        lsiown abc:abc \
            /downloads
      '';
      originalPermissionsBlock = ''
        # permissions
        lsiown -R abc:abc \
            /config
        lsiown abc:abc \
            /downloads
      '';
      patchedPermissionsBlock = ''
        # permissions
        lsiown -R abc:abc \
            /config

        echo "**** Skipping ownership changes for /downloads; host permissions are managed outside the container. ****"
      '';
      patched = builtins.replaceStrings
        [ originalPermissionsBlock ]
        [ patchedPermissionsBlock ]
        upstream;
    in
    assert patched != upstream;
    pkgs.writeTextFile {
      name = "pyload-init-pyload-config-run";
      executable = true;
      text = patched;
    };
in

{
  virtualisation.oci-containers.containers."pyload" = {
    image = "lscr.io/linuxserver/pyload-ng:latest";
    extraOptions = [
      "--network=ghostship_net"
      "--health-cmd=wget -q --spider --tries=1 --timeout=5 http://127.0.0.1:8000/ || exit 1"
      "--health-interval=30s"
      "--health-timeout=10s"
      "--health-retries=5"
      "--health-start-period=1m"
      "--health-on-failure=kill"
    ];
    environment = {
      PUID = "3000";
      PGID = "3000";
      TZ = "UTC";
    };
    volumes = [
      "/srv/apps/pyload:/config"
      "/mnt/share/Downloads:/downloads"
      "${pyloadInitConfigRun}:/etc/s6-overlay/s6-rc.d/init-pyload-config/run:ro"
    ];
  };

  systemd.services.podman-pyload = {
    after = [ "mnt-share.mount" ];
    wants = [ "mnt-share.mount" ];
  };

  systemd.tmpfiles.rules = [
    "d /srv/apps/pyload 0755 apps apps -"
  ];

  system.activationScripts.pyload-config = {
    text = ''
      CONFIG_FILE="/srv/apps/pyload/settings/pyload.cfg"

      if [ -f "$CONFIG_FILE" ]; then
        echo "Surgically updating pyload config..."

        pyload_args=(
          "download.max_downloads=literal:10"
          "general.storage_folder=literal:/downloads/PyLoad"
          "general.debug_level=literal:debug"
          "general.folder_per_package=literal:true"
          "webui.session_lifetime=literal:5256000"
          "webui.autologin=literal:true"
        )

        ${pkgs.ghostship-config}/bin/ghostship-config set "$CONFIG_FILE" "''${pyload_args[@]}"

        chown 3000:3000 "$CONFIG_FILE"
      fi
    '';
  };
}
