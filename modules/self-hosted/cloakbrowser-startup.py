import os
from pathlib import Path

APP_DIR = Path("/app")
MAIN_PATH = APP_DIR / "backend" / "main.py"
MODELS_PATH = APP_DIR / "backend" / "models.py"
DATABASE_PATH = APP_DIR / "backend" / "database.py"
FRONTEND_ASSETS = APP_DIR / "frontend" / "dist" / "assets"
CONFIG_PATH = Path("/usr/local/lib/python3.12/site-packages/cloakbrowser/config.py")

EXTENSION_PATHS = (
    "/data/extensions/ublock-origin-lite",
    "/data/extensions/i-still-dont-care-about-cookies",
    "/data/extensions/bypass-paywalls-chrome-clean",
)
EXTENSIONS_ARG = ",".join(EXTENSION_PATHS)
DEFAULT_LAUNCH_ARGS = [
    f"--disable-extensions-except={EXTENSIONS_ARG}",
    f"--load-extension={EXTENSIONS_ARG}",
]
DEFAULT_GPU_VENDOR = "Google Inc. (Apple)"
DEFAULT_GPU_RENDERER = "ANGLE (Apple, ANGLE Metal Renderer: Apple M3, Unspecified Version)"

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


def patch_profile_defaults() -> None:
    print("Patching CloakBrowser API and database profile defaults...")
    patch_models_defaults()
    patch_database_defaults()
    patch_main_profile_defaults()
    patch_frontend_profile_defaults()


def patch_models_defaults() -> None:
    text = MODELS_PATH.read_text()
    if "GHOSTSHIP_DEFAULT_LAUNCH_ARGS" not in text:
        anchor = "from pydantic import BaseModel, Field, field_validator\n"
        if anchor not in text:
            raise RuntimeError("CloakBrowser patch anchor missing: pydantic imports")
        text = text.replace(
            anchor,
            anchor
            + "\n"
            + "GHOSTSHIP_DEFAULT_LAUNCH_ARGS = [\n"
            + f"    {DEFAULT_LAUNCH_ARGS[0]!r},\n"
            + f"    {DEFAULT_LAUNCH_ARGS[1]!r},\n"
            + "]\n",
            1,
        )

    replacements = {
        "fingerprint_seed: int | None = None  # random if not set":
            "fingerprint_seed: int | None = 9999",
        "timezone: str | None = None  # \"America/New_York\"":
            'timezone: str | None = "Pacific/Honolulu"',
        "locale: str | None = None  # \"en-US\"":
            'locale: str | None = "en-US"',
        'platform: Literal["windows", "macos", "linux"] = "windows"':
            'platform: Literal["windows", "macos", "linux"] = "macos"',
        "gpu_vendor: str | None = None":
            f'gpu_vendor: str | None = "{DEFAULT_GPU_VENDOR}"',
        "gpu_renderer: str | None = None":
            f'gpu_renderer: str | None = "{DEFAULT_GPU_RENDERER}"',
        "humanize: bool = False":
            "humanize: bool = True",
        "launch_args: list[str] = Field(default_factory=list)":
            "launch_args: list[str] = Field(default_factory=lambda: GHOSTSHIP_DEFAULT_LAUNCH_ARGS.copy())",
    }
    for original, patched in replacements.items():
        if patched in text:
            continue
        if original not in text:
            raise RuntimeError(f"CloakBrowser patch anchor missing in models.py: {original}")
        text = text.replace(original, patched, 1)

    MODELS_PATH.write_text(text)
    print("CloakBrowser API profile defaults patched.")


def patch_database_defaults() -> None:
    text = DATABASE_PATH.read_text()
    if "GHOSTSHIP_DEFAULT_LAUNCH_ARGS" not in text:
        anchor = 'DB_PATH = DATA_DIR / "profiles.db"\n'
        if anchor not in text:
            raise RuntimeError("CloakBrowser patch anchor missing: DB_PATH")
        text = text.replace(
            anchor,
            anchor
            + "\n"
            + "GHOSTSHIP_DEFAULT_LAUNCH_ARGS = [\n"
            + f"    {DEFAULT_LAUNCH_ARGS[0]!r},\n"
            + f"    {DEFAULT_LAUNCH_ARGS[1]!r},\n"
            + "]\n",
            1,
        )

    replacements = {
        "seed = fingerprint_seed if fingerprint_seed is not None else random.randint(10000, 99999)":
            "seed = fingerprint_seed if fingerprint_seed is not None else 9999",
        'fields.get("timezone")':
            'fields.get("timezone", "Pacific/Honolulu")',
        'fields.get("locale")':
            'fields.get("locale", "en-US")',
        'fields.get("platform", "windows")':
            'fields.get("platform", "macos")',
        'fields.get("gpu_vendor")':
            f'fields.get("gpu_vendor", "{DEFAULT_GPU_VENDOR}")',
        'fields.get("gpu_renderer")':
            f'fields.get("gpu_renderer", "{DEFAULT_GPU_RENDERER}")',
        'fields.get("humanize", False)':
            'fields.get("humanize", True)',
        'json.dumps(fields.get("launch_args") or [])':
            'json.dumps(fields.get("launch_args") or GHOSTSHIP_DEFAULT_LAUNCH_ARGS)',
    }
    for original, patched in replacements.items():
        if patched in text:
            continue
        if original not in text:
            raise RuntimeError(f"CloakBrowser patch anchor missing in database.py: {original}")
        text = text.replace(original, patched, 1)

    DATABASE_PATH.write_text(text)
    print("CloakBrowser database profile defaults patched.")


def patch_main_profile_defaults() -> None:
    text = MAIN_PATH.read_text()
    if "def _apply_ghostship_create_defaults" not in text:
        anchor = "\n\n@app.get(\"/api/profiles\", response_model=list[ProfileResponse])\n"
        if anchor not in text:
            raise RuntimeError("CloakBrowser patch anchor missing: profiles route")
        helper = f'''

def _apply_ghostship_create_defaults(data: dict) -> None:
    stale_frontend_defaults = (
        data.get("platform") == "windows"
        and data.get("fingerprint_seed") == 9999
        and data.get("screen_width") == 1920
        and data.get("screen_height") == 1080
        and data.get("humanize") is False
        and data.get("human_preset") == "default"
        and data.get("launch_args") == []
    )
    if not stale_frontend_defaults:
        return

    data["platform"] = "macos"
    data["timezone"] = "Pacific/Honolulu"
    data["locale"] = "en-US"
    data["gpu_vendor"] = {DEFAULT_GPU_VENDOR!r}
    data["gpu_renderer"] = {DEFAULT_GPU_RENDERER!r}
    data["humanize"] = True
    data["human_preset"] = "default"
    data["launch_args"] = [
        {DEFAULT_LAUNCH_ARGS[0]!r},
        {DEFAULT_LAUNCH_ARGS[1]!r},
    ]
'''
        text = text.replace(anchor, helper + anchor, 1)

    original = """async def create_profile(req: ProfileCreate):
    data = req.model_dump()
    tags = data.pop("tags", None)
"""
    patched = """async def create_profile(req: ProfileCreate):
    data = req.model_dump()
    _apply_ghostship_create_defaults(data)
    tags = data.pop("tags", None)
"""
    if patched not in text:
        if original not in text:
            raise RuntimeError("CloakBrowser patch anchor missing: create_profile route")
        text = text.replace(original, patched, 1)

    MAIN_PATH.write_text(text)
    print("CloakBrowser create-profile route defaults patched.")


def patch_frontend_profile_defaults() -> None:
    bundles = sorted(FRONTEND_ASSETS.glob("index-*.js"))
    if not bundles:
        raise RuntimeError("CloakBrowser frontend bundle not found")

    original_state = (
        '{name:"",platform:"windows",screen_width:1920,screen_height:1080,'
        'humanize:!1,human_preset:"default",headless:!1,geoip:!1,'
        'clipboard_sync:!0,auto_launch:!1,launch_args:[],tags:[]}'
    )
    patched_state = (
        '{name:"",fingerprint_seed:9999,timezone:"Pacific/Honolulu",locale:"en-US",'
        'platform:"macos",screen_width:1920,screen_height:1080,'
        f'gpu_vendor:{DEFAULT_GPU_VENDOR!r},gpu_renderer:{DEFAULT_GPU_RENDERER!r},'
        'humanize:!0,human_preset:"default",headless:!1,geoip:!1,'
        'clipboard_sync:!0,auto_launch:!1,'
        f'launch_args:[{DEFAULT_LAUNCH_ARGS[0]!r},{DEFAULT_LAUNCH_ARGS[1]!r}],tags:[]}}'
    )
    original_gpu_select = 'className:"input",value:"",onChange:T=>{T.target.value&&cl(T.target.value)},children:'
    patched_gpu_select = (
        'className:"input",value:_.gpu_vendor==='
        f'{DEFAULT_GPU_VENDOR!r}&&_.gpu_renderer==={DEFAULT_GPU_RENDERER!r}?"Apple M3 (macOS)":"",'
        'onChange:T=>{T.target.value&&cl(T.target.value)},children:'
    )

    changed = False
    for bundle in bundles:
        text = bundle.read_text()
        next_text = text
        if original_state in next_text:
            next_text = next_text.replace(original_state, patched_state, 1)
        if original_gpu_select in next_text:
            next_text = next_text.replace(original_gpu_select, patched_gpu_select, 1)
        if next_text != text:
            bundle.write_text(next_text)
            changed = True

    if changed:
        print("CloakBrowser frontend profile defaults patched.")
    else:
        joined = ", ".join(str(path) for path in bundles)
        print(f"CloakBrowser frontend profile defaults already applied or anchors absent: {joined}")


def main() -> None:
    patch_manager()
    patch_extension_launch()
    patch_profile_defaults()
    os.execv("/entrypoint.sh", ["/entrypoint.sh"])


if __name__ == "__main__":
    main()
