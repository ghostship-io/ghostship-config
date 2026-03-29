# CloakBrowser Manager Integration Status

## Current Status Overview

We are working on integrating `cloakbrowser-manager` with two persistent profiles (Direct and VPN) and ensuring `agent-browser` can automate these profiles remotely.

### What is Working Successfully

1. **Proxy Routing:** 
   - The VPN profile successfully routes its traffic through the `gluetun` container. We verified this by retrieving the IP address (`212.56.52.46`) from the VPN profile, which differs from the Direct profile's IP (`72.235.23.120`).
   - *Fix applied:* We enabled `HTTPPROXY="on"` in the `gluetun` NixOS configuration.

2. **CSWSH Proxy Bypass:**
   - The Manager's built-in CDP proxy on port 8080 blocks WebSocket connections that have mismatched `Origin` headers (preventing Cross-Site WebSocket Hijacking). 
   - *Fix applied:* We deployed a lightweight `mitmproxy` sidecar on port 8080 that strips the `Origin` header from incoming requests before forwarding them to the Manager on internal port 8081. This successfully allows `agent-browser` to connect.

3. **Playwright Extension Unblocking:**
   - By default, Playwright launches Chromium with the `--disable-extensions` flag, which breaks our setup.
   - *Fix applied:* We used a runtime script to patch `cloakbrowser/config.py` to remove this flag.

---

## Remaining Roadblocks & Root Causes

The primary remaining task is ensuring the entrypoint reliably handles profile generation and manager initialization.

### Problem 1: Profile Generation Reliability
* **Root Cause:** The current entrypoint script attempts to create profiles via the API while the manager is starting up. If the manager is not fully ready or if the script exits prematurely, the profiles might not be created correctly.

### Problem 2: VPN Proxy Stability
* **Root Cause:** Occasional `net::ERR_TUNNEL_CONNECTION_FAILED` errors indicate that the proxy connection to Gluetun might need more robust handling or specific Chromium flags.

---

## Systematic Solution Approach

### 1. Robust Entrypoint Logic
Update the `entrypoint-override.sh` to:
1.  Initialize the environment (install dependencies like `mitmproxy`).
2.  Start `mitmproxy` as a persistent sidecar.
3.  Patch and start the Manager.
4.  Poll the Manager API until it's fully ready.
5.  Check for the existence of "Direct" and "VPN" profiles and create them if missing.
6.  Ensure the script continues to run and monitors the Manager process.

### 2. Network Stability
1. **VPN Proxy Flags:** Refine the proxy arguments passed by the Manager to include `--proxy-bypass-list=<-loopback>` if needed.

### Next Steps for Implementation
1. Finalize the `cloakbrowser-patch.sh` script in the Nix configuration.
2. Validate profile creation and connectivity.
3. Verify `agent-browser` can successfully connect to both profiles.
