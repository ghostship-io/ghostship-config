{ config, pkgs, ... }:

let
  pyload-secrets = config.ghostship.selfHostedSecrets.projections.pyload.path;
  pyloadImage = "lscr.io/linuxserver/pyload-ng:latest";
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
      originalDefaultConfigBlock = ''
        # default config file
        cp -n \
            /defaults/pyload.cfg \
            /config/settings/pyload.cfg
      '';
      patchedDefaultConfigBlock = ''
        # default config file
        cp -n \
            /defaults/pyload.cfg \
            /config/settings/pyload.cfg

        sed -i -E \
            's#^([[:space:]]*folder storage_folder : "Download folder" = ).*#\1/downloads/PyLoad#' \
            /config/settings/pyload.cfg
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
      patched =
        builtins.replaceStrings
          [
            originalDefaultConfigBlock
            originalPermissionsBlock
          ]
          [
            patchedDefaultConfigBlock
            patchedPermissionsBlock
          ]
          upstream;
    in
    assert patched != upstream;
    pkgs.writeTextFile {
      name = "pyload-init-pyload-config-run";
      executable = true;
      text = patched;
    };
  pyloadSvcRun = pkgs.writeTextFile {
    name = "pyload-svc-run";
    executable = true;
    text = ''
      #!/usr/bin/with-contenv bash
      # shellcheck shell=bash

      PORT=$(sed -n -e '/webui/,/proxy/p' /config/settings/pyload.cfg | grep "Port" | awk -F '=' '{print $2}' | tr -d ' ')

      export LD_PRELOAD="/lib/libgcompat.so.0"

      exec \
          s6-notifyoncheck -d -n 300 -w 1000 -c "nc -z localhost ''${PORT:-8000}" \
          s6-setuidgid abc pyload --userdir /config
    '';
  };
  pyloadRestartFailedScript = pkgs.writeTextFile {
    name = "pyload-restart-failed.py";
    executable = true;
    text = ''
      import json
      import os
      import sys
      import urllib.error
      import urllib.request

      API_BASE = os.environ.get("PYLOAD_API_URL", "http://pyload:8000").rstrip("/")
      API_KEY = os.environ.get("PYLOAD_API_KEY", "").strip()
      TIMEOUT_SECONDS = 30


      def fail(message: str) -> None:
          print(f"pyLoad failed retry: {message}", file=sys.stderr)
          raise SystemExit(1)


      def request_json(path: str, method: str = "GET"):
          request = urllib.request.Request(
              f"{API_BASE}{path}",
              headers={"X-API-Key": API_KEY},
              method=method,
          )
          if method == "POST":
              request.data = b""

          try:
              with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                  body = response.read()
          except urllib.error.HTTPError as exc:
              detail = exc.read().decode("utf-8", errors="replace").strip()
              if len(detail) > 240:
                  detail = detail[:240] + "..."
              fail(f"{method} {path} returned HTTP {exc.code}: {detail}")
          except urllib.error.URLError as exc:
              fail(f"{method} {path} failed: {exc.reason}")

          if not body:
              return None

          try:
              return json.loads(body.decode("utf-8"))
          except json.JSONDecodeError as exc:
              fail(f"{method} {path} returned invalid JSON: {exc}")


      def is_failed_link(link: dict) -> bool:
          status = link.get("status")
          status_name = str(
              link.get("statusname")
              or link.get("status_name")
              or link.get("statusmsg")
              or ""
          ).lower()
          return status == 8 or status_name == "failed"


      def main() -> int:
          if not API_KEY:
              fail("PYLOAD_API_KEY is missing")

          queue = request_json("/api/get_queue_data")
          if not isinstance(queue, list):
              fail("GET /api/get_queue_data returned an unexpected payload")

          package_count = len(queue)
          link_count = 0
          failed_count = 0

          for package in queue:
              links = package.get("links", []) if isinstance(package, dict) else []
              if isinstance(links, dict):
                  links = links.values()
              for link in links:
                  if not isinstance(link, dict):
                      continue
                  link_count += 1
                  if is_failed_link(link):
                      failed_count += 1

          if failed_count == 0:
              print(
                  "pyLoad failed retry: "
                  f"queue_packages={package_count} queue_links={link_count} "
                  "failed_links=0; nothing to restart"
              )
              return 0

          request_json("/api/restart_failed", method="POST")
          print(
              "pyLoad failed retry: "
              f"queue_packages={package_count} queue_links={link_count} "
              f"restarted_failed_links={failed_count}"
          )
          return 0


      raise SystemExit(main())
    '';
  };
  pyloadRestartFailedRunner = pkgs.writeShellScriptBin "pyload-restart-failed" ''
    set -euo pipefail

    exec ${pkgs.podman}/bin/podman run \
      --rm \
      --replace \
      --name pyload-restart-failed \
      --pull=never \
      --network=ghostship_net \
      --env-file ${pyload-secrets} \
      --entrypoint /lsiopy/bin/python3 \
      -v ${pyloadRestartFailedScript}:/run/pyload-restart-failed.py:ro \
      ${pyloadImage} \
      /run/pyload-restart-failed.py
  '';
in

{
  virtualisation.oci-containers.containers."pyload" = {
    image = pyloadImage;
    pull = "always";
    labels = {
      "io.containers.autoupdate" = "registry";
    };
    extraOptions = [
      "--network=ghostship_net"
      "--health-cmd=wget -q -O /dev/null --tries=1 --timeout=5 http://127.0.0.1:8000/favicon.ico || exit 1"
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
      "${pyloadSvcRun}:/etc/s6-overlay/s6-rc.d/svc-pyload/run:ro"
    ];
  };

  systemd.services.podman-pyload = {
    after = [ "mnt-share.mount" ];
    wants = [ "mnt-share.mount" ];
  };

  systemd.services.pyload-restart-failed = {
    description = "Restart failed pyLoad downloads";
    after = [
      "init-ghostship-net.service"
      "podman-pyload.service"
    ];
    wants = [
      "init-ghostship-net.service"
      "podman-pyload.service"
    ];
    serviceConfig = {
      Type = "oneshot";
      ExecStart = "${pyloadRestartFailedRunner}/bin/pyload-restart-failed";
    };
  };

  systemd.timers.pyload-restart-failed = {
    description = "Daily restart of failed pyLoad downloads";
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnCalendar = "*-*-* 04:00:00";
      Persistent = true;
      Unit = "pyload-restart-failed.service";
    };
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
