#!/bin/bash
set -e

# Cleanup old containers if they exist
podman rm -f cloakbrowser-manager cloakbrowser-proxy 2>/dev/null || true

# Ensure data dir exists
mkdir -p /srv/apps/cloakbrowser/data

# Create network if it doesn't exist
podman network create ghostship_net 2>/dev/null || true

# We need to find exactly where the policies should go. Let's mount them to multiple possible locations.
EXT_JSON="$(pwd)/extensions.json"
UBO_JSON="$(pwd)/ublock-origin.json"

echo "Starting Manager..."
podman run -d \
  --name cloakbrowser-manager \
  --network ghostship_net \
  -v /srv/apps/cloakbrowser/data:/data \
  -v "$EXT_JSON":/etc/chromium/policies/managed/extensions.json:ro \
  -v "$UBO_JSON":/etc/chromium/policies/managed/ublock-origin.json:ro \
  -v "$EXT_JSON":/etc/opt/chrome/policies/managed/extensions.json:ro \
  -v "$UBO_JSON":/etc/opt/chrome/policies/managed/ublock-origin.json:ro \
  -v "$EXT_JSON":/root/.cloakbrowser/chromium-145.0.7632.159.7/policies/managed/extensions.json:ro \
  -v "$UBO_JSON":/root/.cloakbrowser/chromium-145.0.7632.159.7/policies/managed/ublock-origin.json:ro \
  cloakhq/cloakbrowser-manager:latest

echo "Starting Proxy (mitmproxy)..."
# We mount the python script and tell mitmproxy to run it.
podman run -d \
  --name cloakbrowser-proxy \
  --network ghostship_net \
  -p 8080:8080 \
  -v "$(pwd)/strip-origin.py":/strip-origin.py:ro \
  mitmproxy/mitmproxy:latest \
  mitmdump -s /strip-origin.py --mode reverse:http://cloakbrowser-manager:8080 --listen-port 8080 --set termlog_level=error

echo "Wait for Manager to be ready..."
until curl -s http://localhost:8080/api/status > /dev/null; do
  sleep 2
done

echo "Creating profiles..."
EXISTS_VPN=$(curl -s http://localhost:8080/api/profiles | jq -r ".[] | select(.name==\"VPN\") | .id")
if [ -z "$EXISTS_VPN" ]; then
  curl -s -X POST http://localhost:8080/api/profiles -H "Content-Type: application/json" \
    -d '{"name": "VPN", "proxy": "http://gluetun:8888", "humanize": true, "geoip": true, "platform": "windows"}'
fi

EXISTS_DIR=$(curl -s http://localhost:8080/api/profiles | jq -r ".[] | select(.name==\"Direct\") | .id")
if [ -z "$EXISTS_DIR" ]; then
  curl -s -X POST http://localhost:8080/api/profiles -H "Content-Type: application/json" \
    -d '{"name": "Direct", "proxy": null, "humanize": true, "geoip": true, "platform": "windows"}'
fi

echo "Done."
