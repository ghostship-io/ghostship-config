## Context

OpenCode is exposed in this repo through a shared `npx` launcher wrapper plus two Nix-managed config paths: a system config for develop hosts and a Home Manager config for user-managed installs. Both config paths currently embed a static OpenRouter model map, and those lists have already drifted. The desired behavior is different: OpenCode should load the current programming-category free models automatically, based on OpenRouter's ranked models page, without requiring a repo edit whenever OpenRouter's weekly ranking changes.

The repo already has the right integration point for runtime refresh logic. `modules/develop/agent-tooling.nix` supports a launcher-specific `preLaunchHook`, and OpenCode supports loading a wrapper-selected custom config through `OPENCODE_CONFIG`. That allows the repo to keep permission defaults in declarative Nix-managed config while moving the model list into a generated runtime config that can refresh independently.

## Goals / Non-Goals

**Goals:**
- Preserve the exact programming-category, free-only, top-weekly selection semantics exposed by OpenRouter's frontend models page.
- Refresh OpenCode's configured OpenRouter model list automatically on launch no more than once per day.
- Make the generated runtime config the only configured OpenRouter model source for OpenCode.
- Remove the existing static model maps from both Nix-managed OpenCode config paths while preserving explicit `permission = "allow"` defaults.
- Continue launching OpenCode when refresh fails by reusing the last good generated config and emitting a warning.

**Non-Goals:**
- Changing Codex or Gemini launcher behavior.
- Creating a background timer or systemd unit for model refresh outside the wrapper launch path.
- Supporting non-programming categories or paid-model selection in this change.
- Reworking unrelated OpenCode settings, plugins, or instructions.

## Decisions

### Use the frontend models endpoint as the ranking source

The wrapper will query `https://openrouter.ai/api/frontend/models/find?categories=programming&fmt=cards&max_price=0&order=top-weekly` rather than the documented public models API.

Rationale:
- The public `api/v1/models` endpoint supports `category=programming`, but it does not expose the same documented query surface for `max_price=0` and `order=top-weekly`.
- The frontend endpoint matches the exact page semantics the user asked for.

Alternatives considered:
- Use `api/v1/models?category=programming` and infer free models locally: rejected because it would not preserve the requested weekly-ranked page behavior.
- Scrape rendered HTML cards: rejected because the frontend endpoint already exposes structured JSON for the same page.

### Still validate free status from returned pricing data

The launcher will not trust the query parameters alone. It will derive the configured model list from models returned by the endpoint whose endpoint pricing is free, using the returned pricing payload as the source of truth.

Rationale:
- The user explicitly wanted to go back to checking price rather than matching `(free)` in the name.
- This guards against naming drift while still honoring the frontend page selection.

Alternatives considered:
- Match only `:free` or `(free)` in returned ids or names: rejected because that is less robust than price-derived filtering.

### Generate a wrapper-managed custom OpenCode config

The launcher will write a generated JSON config file under the user's writable config/cache space and export `OPENCODE_CONFIG` to that file before execing `opencode-ai`.

Rationale:
- Nix-managed system and Home Manager config files are declarative and not appropriate for mutable daily refresh state.
- `OPENCODE_CONFIG` is an OpenCode-supported native config surface and keeps the model list override explicit.
- This avoids mutating global config in place while allowing repo-managed wrapper behavior.

Alternatives considered:
- Rewrite the Nix-managed global config file in place: rejected because it fights the declarative source of truth.
- Keep the static Nix config and inject hidden `--model` flags: rejected because it only sets one model and is less transparent than config-based loading.

### Remove static OpenRouter model maps from the Nix-managed OpenCode configs

Both existing Nix-generated OpenCode config paths will stop declaring `provider.openrouter.models`. They will retain explicit permission behavior while the wrapper-managed generated config becomes the only configured source of OpenRouter models.

Rationale:
- This eliminates the current duplicate model list drift.
- It makes the source of truth singular and runtime-refreshable.

Alternatives considered:
- Keep a static fallback model list in Nix alongside the generated config: rejected because the user wants to rely on the generated list only.

### Cache refreshes once per day and fall back to the last good config

The wrapper will refresh at most once per UTC day using a timestamp marker or file mtime check. If fetch, parse, or write fails, the launcher will warn and continue with the previously generated config when available.

Rationale:
- Daily refresh matches the requested cadence while avoiding network work on every launch.
- Warning-only failure behavior is already consistent with the shared launcher preflight design.

Alternatives considered:
- Always fetch on launch: rejected because it adds avoidable latency and fragility.
- Fail closed when refresh fails: rejected because the repo's launcher policy already prefers warn-and-continue behavior for preflight steps.

## Risks / Trade-offs

- [Risk] The frontend endpoint is less stable than a documented public API. → Mitigation: isolate the fetch/parse logic in the wrapper preflight, validate the returned shape defensively, and fall back to the last good generated config on change or outage.
- [Risk] Daily caching can leave OpenCode up to a day behind OpenRouter's live ranking changes. → Mitigation: this is intentional to match the requested once-per-day refresh cadence.
- [Risk] No cached config exists on a first-launch refresh failure. → Mitigation: emit a clear warning and allow OpenCode to start with its remaining config surfaces, while documenting the initial refresh dependency.
- [Risk] System and Home Manager OpenCode config paths could still drift in unrelated settings later. → Mitigation: remove model-list ownership from both paths in the same change so only permission behavior remains duplicated.

## Migration Plan

1. Add wrapper prelaunch logic that fetches the frontend endpoint, filters free-priced programming models, and writes a generated OpenCode config.
2. Export `OPENCODE_CONFIG` from the OpenCode wrapper so the generated config is loaded on launch.
3. Remove `provider.openrouter.models` from both existing Nix-managed OpenCode config definitions while leaving explicit `permission = "allow"` defaults intact.
4. Update README, CHANGELOG, and AGENTS documentation to describe the dynamic refresh behavior, the once-per-day cadence, and the activation scope.
5. Verify the generated launcher config paths no longer embed static model lists and confirm the wrapper points OpenCode at the generated config.

Rollback:
- Revert the wrapper refresh logic and restore the previous static model lists in the Nix-managed OpenCode configs.

## Open Questions

- Whether the cached refresh boundary should use UTC day rollover or a rolling 24-hour age check. The default assumption for implementation is UTC day rollover because it matches the user's "once per day" wording cleanly.
