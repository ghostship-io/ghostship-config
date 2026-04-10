## Why

Develop hosts now ship a Gemini system configuration that still declares the deprecated `experimental.plan` setting, so every Gemini invocation warns before it starts. The same maintenance flow that installs and refreshes agent CLIs also shows repeated npm `spawn sh ENOENT` failures, which leaves scheduled upkeep partially broken and makes agent update behavior harder to trust.

## What Changes

- Remove the deprecated Gemini `experimental.plan` setting from the develop-host system config and keep the remaining Gemini defaults schema-valid for current releases.
- Define the expected develop-host maintenance runtime so `ghostship-agent-maintenance` can run npm and npx subprocesses reliably under systemd.
- Verify and document how Gemini updates are expected to land through the scheduled maintenance timer, including any rebuild or switch requirements.
- Update active documentation for the Gemini config change and the maintenance/runtime implications on develop hosts.

## Capabilities

### New Capabilities
- `agent-maintenance-runtime`: Define the runtime guarantees that `ghostship-agent-maintenance` needs in order to refresh CLI tools and related assets reliably on develop hosts.

### Modified Capabilities
- `agent-launcher-defaults`: Update the Gemini launcher and config requirements so develop hosts no longer ship deprecated Gemini system settings while keeping the documented default behavior intact.

## Impact

- Affects develop hosts and repo-managed workflow documentation, not server hosts.
- Expected code touch points include `modules/develop/gemini.nix`, `modules/develop/agent-tooling.nix`, and active docs such as `README.md`, `CHANGELOG.md`, and `AGENTS.md`.
- Requires a NixOS rebuild or switch on develop hosts for the Gemini system config change to take effect.
- May require host-side maintenance verification or manual rerun of `ghostship-agent-maintenance` after deployment to confirm the repaired runtime behavior.
