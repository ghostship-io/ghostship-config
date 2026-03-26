# Fleet Configuration Audit Plan

**Goal:** Audit all `self-hosted` configuration files against the live running state on `chill-penguin-root` to identify missing critical settings.

### Tasks
1. Connect to `chill-penguin-root` via SSH.
2. For each service defined in `modules/self-hosted/`, extract the actual running configuration file (e.g., `/srv/apps/sonarr/config.xml`).
3. Compare the live configuration against the keys we are currently injecting via `ghostship-config`.
4. Identify any critical settings (e.g., authentication, ports, database URLs) that are present in the live config but missing from our declarative Nix configuration.
5. Formulate a follow-up plan to add these missing keys to our `ghostship-config` injection scripts.