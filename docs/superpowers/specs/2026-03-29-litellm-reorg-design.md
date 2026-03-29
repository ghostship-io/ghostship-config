# Design: LiteLLM Integration and Service Reorganization

**Goal:** Add LiteLLM to the self-hosted stack and reorganize the "Services" layout in Homepage and Muximux. Ensure no host ports are exposed and fix icons/widgets for CloakBrowser.

## Proposed Architecture

### 1. LiteLLM Service
- **Module:** `modules/self-hosted/litellm.nix`
- **Container:** `ghcr.io/berriai/litellm:main-latest`
- **Network:** `ghostship_net` (no host port exposure)
- **Port:** 4000 (internal)
- **Config:** Minimal initial setup, to be expanded later.

### 2. Homepage Reorganization
- **Group:** `Services`
- **New Order:**
  1. **CloakBrowser**: Fix icon to `sh-googlechrome` (or `mdi-ghost`), remove custom widget.
  2. **LiteLLM**: Add with `mdi-train` icon.
  3. **SearXNG**: Move from current position to follow LiteLLM.
- **Automation:** Use `ghostship-config delete` to remove the old `Infrastructure.CloakBrowser` entry and re-add in the `Services` group in the correct order.

### 3. Muximux Reorganization
- **New Order in `settings.ini.php`:**
  - `CloakBrowser`
  - `LiteLLM`
  - `SearXNG`
- **LiteLLM Settings:** `dd=true`, `icon=mdi-train`.
- **CloakBrowser Settings:** Fix icon.

### 4. Manual Verification & Cleanup
- Use SSH to `chill-penguin` to verify `services.yaml` and `settings.ini.php` updates.
- Manually move/cleanup if the automation needs assistance (as hinted by the user).

## Components to Modify

1.  **New File:** `modules/self-hosted/litellm.nix`
2.  **Update:** `modules/self-hosted/default.nix` (import new module)
3.  **Update:** `modules/self-hosted/homepage.nix` (update activation script)
4.  **Update:** `modules/self-hosted/muximux.nix` (update activation script and order)
5.  **Update:** `modules/self-hosted/cloakbrowser.nix` (remove firewall ports if they should be internal-only)

## Discussion Points

- **CloakBrowser Ports:** The user said "make sure no ports are listening directly on the host". `cloakbrowser.nix` currently has `ports = [ "8080:8080" ];` and `networking.firewall.allowedTCPPorts = [ 8080 ];`. Should I remove these to make it internal-only?
- **LiteLLM Secrets:** Should I add a `litellm-secrets` sops entry now, or wait for the "config options" phase?

Does this design look right so far?
