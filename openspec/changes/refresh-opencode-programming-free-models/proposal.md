## Why

The repo currently hard-codes OpenRouter models into both OpenCode config paths, and the two lists have already drifted. The desired behavior is to load the current programming-category free models automatically at OpenCode launch, without requiring repo edits whenever OpenRouter's weekly-ranked free set changes.

## What Changes

- Add OpenCode launcher behavior that fetches the OpenRouter frontend models endpoint for `categories=programming`, `max_price=0`, and `order=top-weekly` and derives the allowed model list from the returned free-priced results.
- Cache the generated OpenCode config once per day so launches refresh the model list automatically without fetching on every invocation.
- Export the generated config to OpenCode at launch so the runtime-generated model list is loaded automatically.
- Remove the static OpenRouter model definitions from the existing Nix-managed OpenCode config files and rely on the generated runtime config as the only source of configured OpenRouter models.
- Preserve existing explicit OpenCode permission defaults and warning-only launcher behavior if refresh fails.

## Capabilities

### New Capabilities
- `opencode-programming-free-model-refresh`: Keep OpenCode's configured OpenRouter model list aligned with the current programming-category free models from OpenRouter's ranked frontend endpoint.

### Modified Capabilities
- `agent-launcher-defaults`: OpenCode launcher configuration will stop embedding a static model list and will instead delegate model selection to a wrapper-managed generated config while preserving the explicit allow-all permission default.

## Impact

- Affects develop-host OpenCode launcher behavior, the shared agent wrapper, and the Home Manager OpenCode config path.
- Touches `modules/develop/opencode-wrapper.nix`, `modules/develop/opencode.nix`, and shared launcher logic in `modules/develop/agent-tooling.nix`.
- Requires a develop-host NixOS rebuild for the system wrapper/config path and a Home Manager switch where the Home Manager OpenCode config path is active.
- No manual cleanup should be required beyond replacing the previous static model definitions with the generated runtime config flow.
