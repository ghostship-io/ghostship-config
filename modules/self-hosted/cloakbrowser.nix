{ config, lib, pkgs, ... }:

let
  cloakbrowser-startup = pkgs.writeText "cloakbrowser-startup.py" ''
import os
import sys
from pathlib import Path

APP_DIR = Path("/app")
MAIN_PATH = APP_DIR / "backend" / "main.py"

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

        profiles = db.list_profiles()
        existing_names = {p["name"] for p in profiles}

        if "VPN" not in existing_names:
            print("Creating VPN profile...")
            db.create_profile(
                name="VPN",
                proxy="http://gluetun:8888",
                humanize=True,
                geoip=True,
                platform="windows",
            )
            print("VPN profile created.")

        if "Direct" not in existing_names:
            print("Creating Direct profile...")
            db.create_profile(
                name="Direct",
                proxy=None,
                humanize=True,
                geoip=True,
                platform="windows",
            )
            print("Direct profile created.")

        if "Changedetection" not in existing_names:
            print("Creating Changedetection profile...")
            db.create_profile(
                name="Changedetection",
                proxy=None,
                humanize=True,
                geoip=True,
                platform="windows",
            )
            print("Changedetection profile created.")
    except Exception as exc:
        print(f"Failed to initialize profiles: {exc}")

def main():
    patch_manager()
    init_profiles()
    os.execv("/entrypoint.sh", ["/entrypoint.sh"])

if __name__ == "__main__":
    main()
'';

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
}
