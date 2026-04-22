FROM docker.io/jez500/seleniumbase-scrapper:latest

ENV CLOAKBROWSER_BINARY_PATH=/opt/cloakbrowser/chrome

COPY cloakbrowser/common/install_cloakbrowser.py /tmp/install_cloakbrowser.py
COPY pricebuddy-scraper-cloakbrowser/patch_pricebuddy.py /tmp/patch_pricebuddy.py

RUN pip install --no-cache-dir cloakbrowser         && python3 /tmp/install_cloakbrowser.py         && python3 /tmp/patch_pricebuddy.py         && browser_major="$(${CLOAKBROWSER_BINARY_PATH} --version | sed -E 's/[^0-9]*([0-9]+).*//')"         && seleniumbase get chromedriver "$browser_major" --path         && python3 - <<'PY'
import os
import re
import subprocess

browser_version = subprocess.check_output(
    [os.environ['CLOAKBROWSER_BINARY_PATH'], '--version'],
    text=True,
).strip()
driver_version = subprocess.check_output(
    ['chromedriver', '--version'],
    text=True,
).strip()

browser_major = re.search(r'(\d+)', browser_version)
driver_major = re.search(r'(\d+)', driver_version)
if not browser_major or not driver_major:
    raise SystemExit(f'Unable to parse versions: browser={browser_version!r} driver={driver_version!r}')
if browser_major.group(1) != driver_major.group(1):
    raise SystemExit(
        f'Chromedriver mismatch: browser={browser_version} driver={driver_version}'
    )
print(f'Validated browser/driver compatibility: {browser_version} / {driver_version}')
PY
