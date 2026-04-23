#!/usr/bin/env python3
from pathlib import Path


def patch_file(path_str: str, replacements: list[tuple[str, str]]) -> None:
    path = Path(path_str)
    text = path.read_text()
    for anchor, replacement in replacements:
        if anchor not in text:
            raise SystemExit(f"anchor not found in {path}: {anchor!r}")
        text = text.replace(anchor, replacement, 1)
    path.write_text(text)
    print(f"Patched {path}")


patch_file(
    "/usr/src/app/api.ts",
    [
        (
            "import { chromium, Browser, BrowserContext, Route, Request as PlaywrightRequest, Page } from 'playwright';\n",
            "import { launch as launchCloak } from 'cloakbrowser';\n"
            "import { chromium, Browser, BrowserContext, Route, Request as PlaywrightRequest, Page } from 'playwright';\n",
        ),
        (
            "const PROXY_SERVER = process.env.PROXY_SERVER || null;\n"
            "const PROXY_USERNAME = process.env.PROXY_USERNAME || null;\n"
            "const PROXY_PASSWORD = process.env.PROXY_PASSWORD || null;\n",
            "const PROXY_SERVER = process.env.PROXY_SERVER || null;\n"
            "const PROXY_USERNAME = process.env.PROXY_USERNAME || null;\n"
            "const PROXY_PASSWORD = process.env.PROXY_PASSWORD || null;\n"
            "const USE_CLOAKBROWSER = (process.env.USE_CLOAKBROWSER ?? 'true').toUpperCase() === 'TRUE';\n"
            "const CLOAKBROWSER_HUMANIZE = (process.env.CLOAKBROWSER_HUMANIZE ?? 'true').toUpperCase() === 'TRUE';\n",
        ),
        (
            "let browser: Browser;\n\n"
            "const initializeBrowser = async () => {\n"
            "  browser = await chromium.launch({\n"
            "    headless: true,\n"
            "    args: [\n"
            "      '--no-sandbox',\n"
            "      '--disable-setuid-sandbox',\n"
            "      '--disable-dev-shm-usage',\n"
            "      '--disable-accelerated-2d-canvas',\n"
            "      '--no-first-run',\n"
            "      '--no-zygote',\n"
            "      '--disable-gpu'\n"
            "    ]\n"
            "  });\n"
            "};\n",
            "let browser: Browser;\n\n"
            "const launchArgs = [\n"
            "  '--no-sandbox',\n"
            "  '--disable-setuid-sandbox',\n"
            "  '--disable-dev-shm-usage',\n"
            "  '--disable-accelerated-2d-canvas',\n"
            "  '--no-first-run',\n"
            "  '--no-zygote',\n"
            "  '--disable-gpu'\n"
            "];\n\n"
            "const launchProxy = PROXY_SERVER\n"
            "  ? {\n"
            "      server: PROXY_SERVER,\n"
            "      ...(PROXY_USERNAME ? { username: PROXY_USERNAME } : {}),\n"
            "      ...(PROXY_PASSWORD ? { password: PROXY_PASSWORD } : {}),\n"
            "    }\n"
            "  : undefined;\n\n"
            "const initializeBrowser = async () => {\n"
            "  if (USE_CLOAKBROWSER) {\n"
            "    browser = await launchCloak({\n"
            "      headless: true,\n"
            "      humanize: CLOAKBROWSER_HUMANIZE,\n"
            "      stealthArgs: true,\n"
            "      args: launchArgs,\n"
            "      ...(launchProxy ? { proxy: launchProxy } : {}),\n"
            "    });\n"
            "    return;\n"
            "  }\n\n"
            "  browser = await chromium.launch({\n"
            "    headless: true,\n"
            "    args: launchArgs,\n"
            "    ...(launchProxy ? { proxy: launchProxy } : {}),\n"
            "  });\n"
            "};\n",
        ),
        (
            "  if (PROXY_SERVER && PROXY_USERNAME && PROXY_PASSWORD) {\n"
            "    contextOptions.proxy = {\n"
            "      server: PROXY_SERVER,\n"
            "      username: PROXY_USERNAME,\n"
            "      password: PROXY_PASSWORD,\n"
            "    };\n"
            "  } else if (PROXY_SERVER) {\n"
            "    contextOptions.proxy = {\n"
            "      server: PROXY_SERVER,\n"
            "    };\n"
            "  }\n\n",
            "",
        ),
    ],
)
