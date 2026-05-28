import os
from pathlib import Path

APP_DIR = Path("/app")
MAIN_PATH = APP_DIR / "backend" / "main.py"
CONFIG_PATH = Path("/usr/local/lib/python3.12/site-packages/cloakbrowser/config.py")

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
        if scope[\"type\"] in (\"http\", \"websocket\"):
            _strip_origin_header(scope)

        # Pass through if auth disabled, or non-HTTP/WS scope (e.g. lifespan)
        if not AUTH_TOKEN or scope[\"type\"] not in (\"http\", \"websocket\"):
            await self.app(scope, receive, send)
            return
"""


def patch_manager() -> None:
    print(f"Patching {MAIN_PATH} to strip Origin in AuthMiddleware...")
    text = MAIN_PATH.read_text()

    if PATCHED_CLASS in text and PATCHED_CALL in text:
        print("CloakBrowser origin patch already applied.")
        return

    if ORIGINAL_CLASS not in text:
        raise RuntimeError("CloakBrowser patch anchor missing: AuthMiddleware class")

    if ORIGINAL_CALL not in text:
        raise RuntimeError("CloakBrowser patch anchor missing: AuthMiddleware.__call__")

    text = text.replace(ORIGINAL_CLASS, PATCHED_CLASS, 1)
    text = text.replace(ORIGINAL_CALL, PATCHED_CALL, 1)
    MAIN_PATH.write_text(text)
    print("CloakBrowser origin patch applied.")


def patch_extension_launch() -> None:
    print(f"Patching {CONFIG_PATH} to allow unpacked Chrome extensions...")
    text = CONFIG_PATH.read_text()
    patched = (
        'IGNORE_DEFAULT_ARGS = ["--enable-automation", '
        '"--enable-unsafe-swiftshader", "--disable-extensions"]'
    )
    if patched in text:
        print("CloakBrowser extension launch patch already applied.")
        return

    original = (
        'IGNORE_DEFAULT_ARGS = ["--enable-automation", '
        '"--enable-unsafe-swiftshader"]'
    )
    if original not in text:
        raise RuntimeError("CloakBrowser patch anchor missing: IGNORE_DEFAULT_ARGS")

    CONFIG_PATH.write_text(text.replace(original, patched, 1))
    print("CloakBrowser extension launch patch applied.")


def main() -> None:
    patch_manager()
    patch_extension_launch()
    os.execv("/entrypoint.sh", ["/entrypoint.sh"])


if __name__ == "__main__":
    main()
