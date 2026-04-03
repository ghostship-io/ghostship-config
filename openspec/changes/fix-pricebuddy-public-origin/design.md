## Context

PriceBuddy on `chill-penguin` is deployed from
`modules/self-hosted/pricebuddy.nix`, which generates `/srv/apps/pricebuddy/pricebuddy.env`
at service start and bind-mounts it into the app container as `/app/.env`.
The live investigation found that this generated env omitted both `APP_URL` and
`ASSET_URL`, so Laravel fell back to `http://localhost` for app URLs and
Filament dynamically imported some frontend modules from
`http://pricebuddy.ghostship.io/...` on an HTTPS page. Chrome blocked those
imports as mixed content, which prevented Livewire actions like `Add URL` from
mounting their modal even though the backend route itself was healthy.

The user already applied a live-only host patch by editing
`/srv/apps/pricebuddy/pricebuddy.env` and refreshing Laravel's config cache in
the running container. That patch restored the UI but is not durable because
the repo-managed env generation will overwrite it on the next managed
PriceBuddy restart.

## Goals / Non-Goals

**Goals:**
- Make the generated PriceBuddy env declare the canonical public HTTPS origin
  for `pricebuddy.ghostship.io`.
- Keep frontend module imports and generated URLs on the same public HTTPS
  origin so Cloudflare Access does not surface mixed-content failures.
- Verify the managed runtime emits the expected public URLs after activation.

**Non-Goals:**
- Change Cloudflare Access policy or CSP behavior.
- Patch upstream PriceBuddy or Filament source code.
- Fix unrelated upstream PriceBuddy issues such as vague Livewire error
  handling or non-origin-specific auth problems.

## Decisions

### Decision: Set both `APP_URL` and `ASSET_URL` in the managed PriceBuddy env

The durable fix belongs in `pricebuddy-env-sync`, which already owns the
generated application env file. It should write:

- `APP_URL=https://pricebuddy.ghostship.io`
- `ASSET_URL=https://pricebuddy.ghostship.io`

That keeps Laravel URL generation and Filament asset/module URLs aligned on the
same HTTPS origin without relying on ad hoc live edits.

Alternative considered: setting only `APP_URL`.
Rejected because the live browser failure was a blocked Filament module import,
so asset generation must also be pinned explicitly rather than assuming every
consumer derives it safely from `APP_URL`.

### Decision: Extend PriceBuddy runtime verification to assert the public origin

`pricebuddy-runtime-verify` currently checks env files, scraper reachability,
and bearer-token shape. It should also evaluate Laravel config inside the app
container and confirm that generated app and asset URLs resolve to the expected
`https://pricebuddy.ghostship.io` origin.

Alternative considered: verify only the raw env file contents.
Rejected because the incident was visible in rendered behavior. Verifying the
effective Laravel config catches stale config-cache state as well as missing env
keys.

### Decision: Keep the fix repo-managed and host-local

The problem is deployment-specific runtime wiring, not a general upstream code
defect. The repo should fix it where this stack already owns PriceBuddy env
generation and verification.

Alternative considered: maintain the live host patch manually.
Rejected because it will be overwritten by the next managed restart and is not
auditable in the repo.

## Risks / Trade-offs

- [Risk] The public hostname could change later while the env remains pinned to
  `pricebuddy.ghostship.io`. → Mitigation: keep the hostname explicit in the
  module and document the dependency in repo docs and agent memory.
- [Risk] Laravel config cache could remain stale after env updates if
  deployment flow changes. → Mitigation: keep verification focused on effective
  generated URLs inside the running container, not only the env file.
- [Risk] The `/manifest.json` Cloudflare Access redirect noise may still appear
  in browsers even after the mixed-content failure is fixed. → Mitigation:
  treat manifest login redirects as secondary unless they block a required app
  action.

## Migration Plan

1. Update `modules/self-hosted/pricebuddy.nix` so the generated env includes
   `APP_URL` and `ASSET_URL` for `https://pricebuddy.ghostship.io`.
2. Extend `pricebuddy-runtime-verify` to confirm Laravel emits the expected
   public origin for app and asset URLs.
3. Rebuild and activate `chill-penguin` through the normal Git-based deployment
   flow.
4. Verify the live app no longer emits mixed-content `http://` Filament module
   imports and that `Add URL` works from the public hostname.

Rollback: revert the module change, redeploy, and if needed restore the prior
generated env behavior by restarting the managed PriceBuddy service.

## Open Questions

- None. The public hostname, affected host, and live failure mode were all
  confirmed during the incident investigation.
