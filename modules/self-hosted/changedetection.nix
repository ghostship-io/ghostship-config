{ pkgs, ... }:

let
  changedetection-state-dir = "/srv/apps/changedetection";
  legacy-changedetection-state-dir = "/srv/apps/changedetectionio";
  changedetection-env = "${changedetection-state-dir}/changedetection.env";
  changedetection-profile-bootstrap = pkgs.writeTextFile {
    name = "changedetection-profile-bootstrap.py";
    executable = true;
    text = ''
      #!${pkgs.python3}/bin/python3
      import json
      import sqlite3
      import subprocess
      import time
      from pathlib import Path

      PROFILE_NAME = "Changedetection"
      DB_PATH = Path("/srv/apps/cloakbrowser/data/profiles.db")
      ENV_PATH = Path("${changedetection-env}")
      PODMAN = "${pkgs.podman}/bin/podman"
      CONTAINER = "cloakbrowser"
      CONTAINER_PYTHON = "/usr/local/bin/python3"

      STATUS_CODE = """
      import sys
      import urllib.request

      try:
          with urllib.request.urlopen("http://127.0.0.1:8080/api/status", timeout=5) as response:
              sys.exit(0 if response.status == 200 else 1)
      except Exception:
          sys.exit(1)
      """

      PROFILE_STATUS_CODE = """
      import json
      import sys
      import urllib.request

      profile_id = sys.argv[1]
      with urllib.request.urlopen(
          f"http://127.0.0.1:8080/api/profiles/{profile_id}/status",
          timeout=5,
      ) as response:
          data = json.load(response)
      print(data.get("status", ""), end="")
      """

      PROFILE_LAUNCH_CODE = """
      import sys
      import urllib.error
      import urllib.request

      profile_id = sys.argv[1]
      request = urllib.request.Request(
          f"http://127.0.0.1:8080/api/profiles/{profile_id}/launch",
          method="POST",
      )

      try:
          with urllib.request.urlopen(request, timeout=30) as response:
              sys.exit(0 if 200 <= response.status < 300 else 1)
      except urllib.error.HTTPError as exc:
          if exc.code == 409:
              sys.exit(0)
          raise
      """


      def podman_exec(code: str, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
          result = subprocess.run(
              [PODMAN, "exec", "-i", CONTAINER, CONTAINER_PYTHON, "-c", code, *args],
              check=False,
              capture_output=True,
              text=True,
          )
          if check and result.returncode != 0:
              raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "podman exec failed")
          return result


      def wait_for_profile() -> str:
          for _ in range(120):
              if DB_PATH.exists():
                  with sqlite3.connect(DB_PATH) as connection:
                      row = connection.execute(
                          "SELECT id FROM profiles WHERE name = ?",
                          (PROFILE_NAME,),
                      ).fetchone()
                  if row and row[0]:
                      return row[0]
              time.sleep(1)
          raise RuntimeError(
              f"CloakBrowser profile '{PROFILE_NAME}' was not found in {DB_PATH}"
          )


      def wait_for_manager() -> None:
          for _ in range(120):
              result = podman_exec(STATUS_CODE, check=False)
              if result.returncode == 0:
                  return
              time.sleep(1)
          raise RuntimeError("CloakBrowser manager never became ready")


      def ensure_profile_running(profile_id: str) -> None:
          status = podman_exec(PROFILE_STATUS_CODE, profile_id, check=False)
          if status.returncode == 0 and status.stdout.strip() == "running":
              return
          podman_exec(PROFILE_LAUNCH_CODE, profile_id)


      def write_env(profile_id: str) -> None:
          ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
          ENV_PATH.write_text(
              "PLAYWRIGHT_DRIVER_URL="
              f"http://cloakbrowser:8080/api/profiles/{profile_id}/cdp\n"
          )
          ENV_PATH.chmod(0o600)


      def main() -> None:
          profile_id = wait_for_profile()
          wait_for_manager()
          ensure_profile_running(profile_id)
          write_env(profile_id)


      if __name__ == "__main__":
          main()
    '';
  };
  changedetection-pre-start = pkgs.writeShellScript "changedetection-pre-start" ''
    set -euo pipefail

    if [ -d "${legacy-changedetection-state-dir}" ]; then
      if [ ! -e "${changedetection-state-dir}" ] || [ -z "$(${pkgs.findutils}/bin/find "${changedetection-state-dir}" -mindepth 1 -print -quit 2>/dev/null)" ]; then
        rmdir "${changedetection-state-dir}" 2>/dev/null || true
        mv "${legacy-changedetection-state-dir}" "${changedetection-state-dir}"
      else
        shopt -s dotglob nullglob
        legacy_entries=("${legacy-changedetection-state-dir}"/*)
        if [ ''${#legacy_entries[@]} -gt 0 ]; then
          mv "${legacy-changedetection-state-dir}"/* "${changedetection-state-dir}/"
        fi
        shopt -u dotglob nullglob
        rmdir "${legacy-changedetection-state-dir}" 2>/dev/null || true
      fi
    fi

    ${changedetection-profile-bootstrap}
  '';
in
{
  virtualisation.oci-containers.containers."changedetection" = {
    image = "ghcr.io/dgtlmoon/changedetection.io:latest";
    pull = "always";
    labels = {
      "io.containers.autoupdate" = "registry";
    };
    extraOptions = [
      "--network=ghostship_net"
      "--health-cmd=python3 -c 'import urllib.request; urllib.request.urlopen(\"http://127.0.0.1:5000/\", timeout=5).read(1)' || exit 1"
      "--health-interval=30s"
      "--health-timeout=10s"
      "--health-retries=5"
      "--health-start-period=2m"
      "--health-on-failure=kill"
    ];
    environment = {
      DISABLE_VERSION_CHECK = "true";
      HIDE_REFERER = "true";
      PORT = "5000";
      TZ = "UTC";
    };
    environmentFiles = [
      changedetection-env
    ];
    volumes = [
      "${changedetection-state-dir}:/datastore:rw"
    ];
  };

  systemd.services.podman-changedetection = {
    after = [ "podman-cloakbrowser.service" ];
    requires = [ "podman-cloakbrowser.service" ];
    preStart = "${changedetection-pre-start}";
  };

  systemd.tmpfiles.rules = [
    "d ${changedetection-state-dir} 0755 apps apps -"
  ];
}
