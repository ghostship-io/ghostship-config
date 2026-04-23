FROM ghcr.io/firecrawl/playwright-service:latest

ENV CLOAKBROWSER_BINARY_PATH=/opt/cloakbrowser/chrome

COPY cloakbrowser/common/install_cloakbrowser.py /tmp/install_cloakbrowser.py
COPY firecrawl-playwright-cloakbrowser/patch_playwright_service.py /tmp/patch_playwright_service.py

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m pip install --break-system-packages --no-cache-dir cloakbrowser \
    && npm install --no-save cloakbrowser \
    && python3 /tmp/install_cloakbrowser.py \
    && python3 /tmp/patch_playwright_service.py \
    && npm run build \
    && node -c /usr/src/app/dist/api.js
