{ lib, pkgs, ... }:

let
  changedetection-state-dir = "/srv/apps/changedetection";
  containers-root = ../../containers;
  containers-root-str = toString containers-root;
  containers-hash = builtins.substring 11 12 containers-root-str;
  changedetection-image = "localhost/ghostship-changedetection-cloakbrowser:${containers-hash}";
  changedetection-build = pkgs.writeShellScriptBin "ghostship-build-changedetection-image" ''
    set -eu

    image="${changedetection-image}"
    dockerfile="${containers-root}/changedetection-cloakbrowser/Dockerfile"
    context_dir="${containers-root}"

    if [ "''${FORCE_REBUILD:-0}" != "1" ] && ${pkgs.podman}/bin/podman image exists "$image"; then
      exit 0
    fi

    ${pkgs.podman}/bin/podman build \
      --pull=always \
      --tag "$image" \
      --file "$dockerfile" \
      "$context_dir"
  '';
  changedetection-pre-start = pkgs.writeTextFile {
    name = "changedetection-pre-start.py";
    executable = true;
    text = ''
      #!${pkgs.python3}/bin/python3
      import json
      from pathlib import Path

      datastore = Path("${changedetection-state-dir}")
      settings = datastore / "changedetection.json"
      legacy_env = datastore / "changedetection.env"

      def rewrite_json(path: Path) -> None:
          data = json.loads(path.read_text())
          changed = False

          if path == settings:
              app = data.get("settings", {}).get("application", {})
              if app.get("fetch_backend") == "html_cloakbrowser":
                  app["fetch_backend"] = "html_webdriver"
                  changed = True
          else:
              if data.get("fetch_backend") == "html_cloakbrowser":
                  data["fetch_backend"] = "html_webdriver"
                  changed = True

          if changed:
              path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")

      if settings.exists():
          rewrite_json(settings)

      for watch_json in datastore.glob("*/watch.json"):
          rewrite_json(watch_json)

      if legacy_env.exists():
          legacy_env.unlink()
    '';
  };
in
{
  virtualisation.oci-containers.containers."changedetection" = {
    image = changedetection-image;
    pull = "never";
    labels = {
      "io.containers.autoupdate" = "disabled";
    };
    extraOptions = [
      "--network=ghostship_net"
      ''--health-cmd=python3 -c 'import urllib.request; urllib.request.urlopen("http://127.0.0.1:5000/", timeout=5).read(1)' || exit 1''
      "--health-interval=30s"
      "--health-timeout=10s"
      "--health-retries=5"
      "--health-start-period=2m"
      "--health-on-failure=kill"
    ];
    environment = {
      CLOAKBROWSER_WRAPPER = "true";
      DISABLE_VERSION_CHECK = "true";
      HIDE_REFERER = "true";
      PORT = "5000";
      TZ = "UTC";
    };
    volumes = [
      "${changedetection-state-dir}:/datastore:rw"
    ];
  };

  systemd.services.podman-changedetection = {
    preStart = lib.mkBefore ''
      ${changedetection-build}/bin/ghostship-build-changedetection-image
      ${changedetection-pre-start}
    '';
  };

  systemd.services.changedetection-local-image-refresh = {
    description = "Refresh the local Changedetection CloakBrowser image";
    after = [ "podman-auto-update.service" ];
    wants = [ "podman-auto-update.service" ];
    serviceConfig.Type = "oneshot";
    script = ''
      FORCE_REBUILD=1 ${changedetection-build}/bin/ghostship-build-changedetection-image
      ${pkgs.systemd}/bin/systemctl try-restart podman-changedetection.service
      ${pkgs.podman}/bin/podman images --format '{{.Repository}}:{{.Tag}}' \
        | while IFS= read -r stale_image; do
            case "$stale_image" in
              localhost/ghostship-changedetection-cloakbrowser:*)
                if [ "$stale_image" != "${changedetection-image}" ]; then
                  ${pkgs.podman}/bin/podman rmi -f "$stale_image" >/dev/null 2>&1 || true
                fi
                ;;
            esac
          done
    '';
  };

  systemd.timers.changedetection-local-image-refresh = {
    description = "Daily local Changedetection CloakBrowser image refresh";
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnCalendar = "daily";
      Persistent = true;
      RandomizedDelaySec = "45m";
    };
  };

  systemd.tmpfiles.rules = [
    "d ${changedetection-state-dir} 0755 apps apps -"
  ];
}
