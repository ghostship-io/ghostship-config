#!/usr/bin/env python3
from pathlib import Path


def patch_file(path_str: str, anchor: str, replacement: str) -> None:
    path = Path(path_str)
    text = path.read_text()
    if anchor not in text:
        raise SystemExit(f'anchor not found in {path}: {anchor!r}')
    path.write_text(text.replace(anchor, replacement, 1))
    print(f'Patched {path}')


patch_file(
    '/app/changedetectionio/content_fetchers/__init__.py',
    "use_playwright_as_chrome_fetcher = os.getenv('PLAYWRIGHT_DRIVER_URL', False)\n",
    "use_playwright_as_chrome_fetcher = os.getenv('PLAYWRIGHT_DRIVER_URL', False) or os.getenv('CLOAKBROWSER_WRAPPER', False)\n",
)

patch_file(
    '/app/changedetectionio/content_fetchers/__init__.py',
    "        from .playwright import fetcher as html_webdriver\n",
    "        if os.getenv('CLOAKBROWSER_WRAPPER', False):\n            logger.debug('Using embedded CloakBrowser wrapper as fetcher')\n            from .ghostship_cloakbrowser import fetcher as html_webdriver\n        else:\n            from .playwright import fetcher as html_webdriver\n",
)

patch_file(
    '/app/changedetectionio/blueprint/ui/edit.py',
    "                'playwright_enabled': os.getenv('PLAYWRIGHT_DRIVER_URL', False),\n",
    "                'playwright_enabled': os.getenv('PLAYWRIGHT_DRIVER_URL', False) or os.getenv('CLOAKBROWSER_WRAPPER', False),\n",
)

patch_file(
    '/app/changedetectionio/forms.py',
    '    if os.getenv("PLAYWRIGHT_DRIVER_URL") or os.getenv("WEBDRIVER_URL"):\n',
    '    if os.getenv("PLAYWRIGHT_DRIVER_URL") or os.getenv("WEBDRIVER_URL") or os.getenv("CLOAKBROWSER_WRAPPER"):\n',
)
