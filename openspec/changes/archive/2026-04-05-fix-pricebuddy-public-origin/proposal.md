## Why

PriceBuddy currently generates public app and asset URLs without a canonical
HTTPS origin in its managed env file. On `chill-penguin`, that lets the app
emit `http://pricebuddy.ghostship.io/...` Filament module imports behind
Cloudflare Access, which Chrome blocks as mixed content and leaves UI actions
like `Add URL` appearing inert.

## What Changes

- Add the canonical public `APP_URL` and `ASSET_URL` values to the managed
  PriceBuddy app env file for `https://pricebuddy.ghostship.io`.
- Extend PriceBuddy runtime verification so generated public URLs resolve to
  the expected HTTPS origin, not `http://localhost` or `http://...` mixed
  content paths.
- Document that the live-only host patch is not durable and that host
  activation is required for the repo-managed fix to persist across restarts.

## Capabilities

### New Capabilities
- None.

### Modified Capabilities
- `pricebuddy-runtime-reliability`: PriceBuddy runtime wiring must also include
  a stable public HTTPS origin for generated app and asset URLs so the web UI
  can load its frontend modules correctly behind Cloudflare Access.

## Impact

- Affects the server-host NixOS module
  `modules/self-hosted/pricebuddy.nix`.
- Affects generated runtime state under `/srv/apps/pricebuddy/pricebuddy.env`
  on `chill-penguin`.
- Requires host activation or a managed PriceBuddy restart to replace the
  current live-only env patch with the durable repo-managed configuration.
