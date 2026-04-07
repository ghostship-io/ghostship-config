{ config, lib, pkgs, ... }:

let
  cloakbrowser-startup = pkgs.writeText "cloakbrowser-startup.py" ''
import os
import sys
from pathlib import Path

APP_DIR = Path("/app")
MAIN_PATH = APP_DIR / "backend" / "main.py"
MANAGED_PROFILES = (
    "assistant",
    "operations",
    "supervisor",
    "Changedetection",
)

ORIGINAL_CLASS = """class AuthMiddleware:
    \"\"\"Raw ASGI middleware for optional token auth.

    Uses raw ASGI instead of BaseHTTPMiddleware because the latter
    breaks WebSocket routes (wraps request body, preventing WS upgrade).
    \"\"\"
"""

PATCHED_CLASS = """def _strip_origin_header(scope: Scope) -> None:
    \"\"\"Remove Origin from the ASGI header list in-place.\"\"\"
    headers = scope.get(\"headers\", [])
    if not headers:
        return

    filtered = [(key, val) for key, val in headers if key != b\"origin\"]
    if len(filtered) != len(headers):
        scope[\"headers\"] = filtered


class AuthMiddleware:
    \"\"\"Raw ASGI middleware for optional token auth.

    Uses raw ASGI instead of BaseHTTPMiddleware because the latter
    breaks WebSocket routes (wraps request body, preventing WS upgrade).
    \"\"\"
"""

ORIGINAL_CALL = """    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        # Pass through if auth disabled, or non-HTTP/WS scope (e.g. lifespan)
        if not AUTH_TOKEN or scope[\"type\"] not in (\"http\", \"websocket\"):
            await self.app(scope, receive, send)
            return
"""

PATCHED_CALL = """    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        # Replace the old reverse-proxy workaround at the app boundary.
        if scope[\"type\"] in (\"http\", \"websocket\"):
            _strip_origin_header(scope)

        # Pass through if auth disabled, or non-HTTP/WS scope (e.g. lifespan)
        if not AUTH_TOKEN or scope[\"type\"] not in (\"http\", \"websocket\"):
            await self.app(scope, receive, send)
            return
"""


def patch_manager():
    print(f"Patching {MAIN_PATH} to strip Origin in AuthMiddleware...")
    text = MAIN_PATH.read_text()

    if PATCHED_CLASS in text and PATCHED_CALL in text:
        print("CloakBrowser origin patch already applied.")
        return

    if ORIGINAL_CLASS not in text:
        raise RuntimeError(
            "CloakBrowser patch anchor missing: AuthMiddleware class"
        )

    if ORIGINAL_CALL not in text:
        raise RuntimeError(
            "CloakBrowser patch anchor missing: AuthMiddleware.__call__"
        )

    text = text.replace(ORIGINAL_CLASS, PATCHED_CLASS, 1)
    text = text.replace(ORIGINAL_CALL, PATCHED_CALL, 1)
    MAIN_PATH.write_text(text)
    print("CloakBrowser origin patch applied.")


def init_profiles():
    print("Initializing database and default profiles...")
    sys.path.append(str(APP_DIR))
    try:
        from backend import database as db
        db.init_db()

        profiles_by_name = {p["name"]: p for p in db.list_profiles()}

        for profile_name in MANAGED_PROFILES:
            if profile_name in profiles_by_name:
                continue

            print(f"Creating {profile_name} profile...")
            db.create_profile(
                name=profile_name,
                proxy=None,
                humanize=True,
                geoip=True,
                platform="windows",
            )
            print(f"{profile_name} profile created.")
    except Exception as exc:
        print(f"Failed to initialize profiles: {exc}")


def main():
    patch_manager()
    init_profiles()
    os.execv("/entrypoint.sh", ["/entrypoint.sh"])


if __name__ == "__main__":
    main()
'';
  cloakbrowser-keep-changedetection = pkgs.writeTextFile {
    name = "cloakbrowser-keep-changedetection.py";
    executable = true;
    text = ''
      #!${pkgs.python3}/bin/python3
      import sqlite3
      import subprocess
      import time
      from pathlib import Path

      DB_PATH = Path("/srv/apps/cloakbrowser/data/profiles.db")
      PROFILE_NAME = "Changedetection"
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


      def podman_exec(code: str, *args: str) -> subprocess.CompletedProcess[str]:
          return subprocess.run(
              [PODMAN, "exec", "-i", CONTAINER, CONTAINER_PYTHON, "-c", code, *args],
              check=False,
              capture_output=True,
              text=True,
          )


      def wait_for_profile() -> str | None:
          for _ in range(60):
              if DB_PATH.exists():
                  with sqlite3.connect(DB_PATH) as connection:
                      row = connection.execute(
                          "SELECT id FROM profiles WHERE name = ?",
                          (PROFILE_NAME,),
                      ).fetchone()
                  if row and row[0]:
                      return row[0]
              time.sleep(1)
          return None


      def wait_for_manager() -> bool:
          for _ in range(60):
              result = podman_exec(STATUS_CODE)
              if result.returncode == 0:
                  return True
              time.sleep(1)
          return False


      def profile_status(profile_id: str) -> str:
          result = podman_exec(PROFILE_STATUS_CODE, profile_id)
          if result.returncode != 0:
              return ""
          return result.stdout.strip()


      def main() -> int:
          profile_id = wait_for_profile()
          if profile_id is None:
              print("Changedetection profile is not present yet; skipping keepalive.")
              return 0

          if not wait_for_manager():
              print("CloakBrowser manager is not ready; skipping keepalive.")
              return 0

          if profile_status(profile_id) == "running":
              return 0

          launch = podman_exec(PROFILE_LAUNCH_CODE, profile_id)
          if launch.returncode != 0:
              time.sleep(2)
              if profile_status(profile_id) == "running":
                  return 0
              stderr = launch.stderr.strip() or launch.stdout.strip()
              if stderr:
                  print(stderr)
              return 1

          return 0


      if __name__ == "__main__":
          raise SystemExit(main())
    '';
  };
in
{
  virtualisation.oci-containers.containers."cloakbrowser" = {
    image = "docker.io/cloakhq/cloakbrowser-manager:latest";
    pull = "always";
    labels = {
      "io.containers.autoupdate" = "registry";
    };
    entrypoint = "/usr/local/bin/python3";
    cmd = [ "/cloakbrowser-startup.py" ];
    extraOptions = [
      "--network=ghostship_net"
      "--health-cmd=/usr/local/bin/python3 -c 'import urllib.request; urllib.request.urlopen(\"http://127.0.0.1:8080/\", timeout=5).read(1)' || exit 1"
      "--health-interval=30s"
      "--health-timeout=10s"
      "--health-retries=5"
      "--health-start-period=1m"
      "--health-on-failure=kill"
    ];

    volumes = [
      "/srv/apps/cloakbrowser/data:/data"
      "${cloakbrowser-startup}:/cloakbrowser-startup.py:ro"
    ];
  };

  systemd.tmpfiles.rules = [
    "d /srv/apps/cloakbrowser 0755 apps apps -"
    "d /srv/apps/cloakbrowser/data 0755 apps apps -"
  ];

  systemd.services.cloakbrowser-keep-changedetection = {
    description = "Keep the Changedetection CloakBrowser profile running";
    after = [ "podman-cloakbrowser.service" ];
    requires = [ "podman-cloakbrowser.service" ];
    serviceConfig = {
      Type = "oneshot";
      ExecStart = "${cloakbrowser-keep-changedetection}";
    };
    wantedBy = [ "multi-user.target" ];
  };

  systemd.timers.cloakbrowser-keep-changedetection = {
    description = "Recheck the Changedetection CloakBrowser profile";
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnBootSec = "2m";
      OnUnitActiveSec = "2m";
      Persistent = true;
      Unit = "cloakbrowser-keep-changedetection.service";
    };
  };
}
