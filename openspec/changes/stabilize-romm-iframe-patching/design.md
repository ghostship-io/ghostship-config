## Context

`modules/self-hosted/romm.nix` currently patches the active RomM frontend
bundle in `postStart` by replacing one exact minified router hook string. The
April 1, 2026 `rommapp/romm:latest` image updated RomM to 4.8.0 and changed the
bundle shape enough that the patch no longer matches. That leaves
`podman-romm.service` failed in `ExecStartPost` before the repo can even answer
whether the upstream image still needs the iframe workaround.

This change affects the server-host RomM service on `chill-penguin`. It needs a
host-side validation path, because the regression only exists in the live
containerized app and Cloudflare-fronted iframe context.

## Goals / Non-Goals

**Goals:**
- Verify the current RomM image behavior without the repo patch and determine
  whether iframe navigation still crashes or otherwise fails.
- Ensure RomM startup does not fail merely because a frontend bundle hash or
  minified string changed upstream.
- If the iframe regression still exists, replace the current bundle rewrite
  with a mitigation that survives routine upstream asset renames and minor
  frontend rebuilds.
- Keep the mitigation and validation flow declarative in the NixOS module and
  documented for future RomM upgrades.

**Non-Goals:**
- Rework unrelated RomM configuration, secrets, or database wiring.
- Introduce a permanent fork of the RomM image or maintain a custom upstream
  frontend build.
- Solve broader Cloudflare Access iframe policy problems that occur before the
  RomM app loads.

## Decisions

### 1. Validate the live image without the patch before changing mitigation
The first step is to disable or bypass the current `postStart` patch on the
host, restart RomM, and reproduce the iframe flow against the unmodified 4.8.0
image.

Why:
- The current service failure proves only that the patch is stale, not that the
  upstream image still has the original iframe regression.
- If upstream already fixed the bug, the durable solution is to remove the
  patch entirely.

Alternatives considered:
- Keep updating the old string replacement immediately. Rejected because it
  does not establish whether the workaround is still needed.

### 2. Prefer a runtime shim over hashed-bundle rewrites if the regression remains
If the unpatched image still fails in iframe contexts, the preferred mitigation
is to inject a stable runtime shim before the main RomM bundle loads, rather
than editing the hashed bundle contents. The shim should target the browser
behavior the app relies on in iframe mode, such as view-transition support, so
the mitigation keys off stable runtime APIs instead of minified symbol names.

Why:
- `index.html` and static preload hooks are materially more stable than the
  hashed `assets/index-*.js` bundle contents.
- A runtime shim can survive routine upstream rebuilds where the asset hash,
  symbol names, and minified control flow all change.
- The service should be able to no-op cleanly when the shim is unnecessary,
  rather than failing startup on an unmatched text replacement.

Alternatives considered:
- Continue patching the active JS bundle with broader regexes. Rejected because
  it still depends on minified implementation details and remains fragile.
- Pin RomM to an older image. Rejected because it avoids the regression only by
  freezing upgrades and does not solve future update durability.
- Maintain a custom RomM image. Rejected because it adds unnecessary packaging
  and upgrade overhead for a single frontend mitigation.

### 3. Make startup tolerant when the mitigation is not needed
The host-side startup logic should distinguish between:
- startup preparation failures
- validation results that show no iframe mitigation is necessary
- mitigation application failures

If the runtime validation shows no regression, the service should start cleanly
without a patch. If a mitigation is needed but cannot be applied, the failure
should explain which stage failed and why.

Why:
- The current failure mode collapses “patch target changed” into a hard service
  startup failure.
- Separating validation from mitigation makes future RomM upgrades debuggable.

## Risks / Trade-offs

- [The iframe crash may no longer reproduce on 4.8.0] -> Make patch removal the
  preferred outcome and avoid carrying dead mitigation code.
- [A runtime shim may miss the actual upstream failure mechanism] -> Reproduce
  the unpatched iframe flow first and only target the stable browser/runtime
  behavior observed during that test.
- [Cloudflare Access may obscure origin-side iframe behavior] -> Validate both
  the live served bundle and the effective iframe path so public-access issues
  are kept separate from RomM origin regressions.
- [A shim inserted through `index.html` may still need upkeep if upstream HTML
  changes significantly] -> Patch a stable insertion point and make the helper
  tolerate already-patched or no-op states.

## Migration Plan

1. Temporarily bypass the existing RomM `postStart` patch on `chill-penguin`.
2. Restart RomM on the host and verify whether the unpatched 4.8.0 image still
   fails in iframe mode.
3. If the regression is gone, remove the old patch logic from the module and
   document the result.
4. If the regression remains, implement the runtime-shim approach in
   `modules/self-hosted/romm.nix`, rebuild the host, and verify startup,
   service health, and iframe behavior.
5. Roll back by switching to the prior NixOS generation if the new startup or
   shim logic regresses service availability.

## Open Questions

- Which exact runtime API path in RomM 4.8.0 triggers the iframe failure once
  the stale bundle patch is removed?
- Can the iframe regression be neutralized entirely by disabling view
  transitions in iframe contexts, or is a different runtime guard required?
