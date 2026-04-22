#!/usr/bin/env python3
from pathlib import Path

article_path = Path('/SeleniumBase/api/endpoints/article.py')
text = article_path.read_text()

import_anchor = "from bs4 import BeautifulSoup\nfrom urllib.parse import urlparse\nfrom datetime import datetime\nimport logging\nimport hashlib\nimport time\nimport os\n"
import_replacement = "from bs4 import BeautifulSoup\nfrom urllib.parse import urlparse\nfrom datetime import datetime\nimport logging\nimport hashlib\nimport time\nimport os\n\nfrom cloakbrowser.config import get_default_stealth_args\n"
if import_anchor not in text:
    raise SystemExit('pricebuddy article import anchor not found')
text = text.replace(import_anchor, import_replacement, 1)

start_marker = "            # Detect browser type: Chromium vs Chrome (Chromium is used for arm64 arch)\n"
end_marker = "            # Note: SeleniumBase Driver may not support all these options directly\n"
start = text.find(start_marker)
end = text.find(end_marker)
if start == -1 or end == -1 or end <= start:
    raise SystemExit('pricebuddy driver block markers not found')
replacement = """            cloakbrowser_binary = os.environ.get('CLOAKBROWSER_BINARY_PATH', '/opt/cloakbrowser/chrome')\n            if not os.path.exists(cloakbrowser_binary):\n                raise FileNotFoundError(f'CloakBrowser binary not found at {cloakbrowser_binary}')\n\n            stealth_args = get_default_stealth_args()\n            logger.info(f\"Launching CloakBrowser from {cloakbrowser_binary}\")\n\n            driver_kwargs = {\n                'browser': 'chrome',\n                'headless': True,\n                'uc': False,\n                'incognito': incognito,\n                'binary_location': cloakbrowser_binary,\n                'chromium_arg': ','.join(stealth_args),\n            }\n\n"""
text = text[:start] + replacement + text[end:]

article_path.write_text(text)
print(f'Patched {article_path}')
