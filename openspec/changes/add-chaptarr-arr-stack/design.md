## Context

`chill-penguin` runs self-hosted applications as repo-managed Podman containers declared under `modules/self-hosted/`. The existing arr stack already covers TV, movies, indexers, subtitles, and download plumbing, but there is no equivalent service for ebooks and audiobooks. Grimmory is already present as the primary reader and library UI, and it currently mounts only the books library root.

The user wants Chaptarr added as an arr-style manager for books and audiobooks, with the same shared downloads exposure used by the other arr services. They also want Grimmory to become the first-class consumption surface for both books and audiobooks, which means both services must see the same durable library roots. Public browser access for Chaptarr follows the same Cloudflare/tunnel pattern as the rest of the stack, while encrypted secret material remains operator-managed outside this change.

## Goals / Non-Goals

**Goals:**
- Add a self-hosted `chaptarr` service to `chill-penguin` with persisted config under `/srv/apps/chaptarr`.
- Mount `/mnt/share/Downloads` into Chaptarr using the same `/downloads` path used by the other arr services so both `Torrent` and `Usenet` content remain visible.
- Mount `/mnt/share/Library/Books` and `/mnt/share/Library/Audiobooks` into Chaptarr as separate library roots.
- Extend Grimmory so it mounts both library roots and remains the primary UI for consuming books and audiobooks.
- Add Chaptarr to Homepage and Muximux with the rest of the arr stack.
- Seed plaintext Chaptarr secret stubs in `secrets.dec.yaml` while leaving encrypted `secrets.yaml` management to the operator.

**Non-Goals:**
- Build direct Grimmory-to-Chaptarr API integration, sync logic, or metadata exchange in this change.
- Move Cloudflare route ownership for `chaptarr.ghostship.io` into the repo.
- Redesign Grimmory storage semantics beyond mounting the additional audiobook library root.
- Introduce separate download paths or a custom acquisition pipeline distinct from the existing shared arr downloads model.

## Decisions

### Decision: Treat Chaptarr as a standard arr-style Podman service
Chaptarr will follow the same broad shape as Sonarr, Radarr, and Prowlarr: a single container on `ghostship_net`, host-backed config under `/srv/apps/chaptarr`, shared `/downloads` access, and activation-time configuration shaping for API/auth defaults. This keeps the service legible within the current stack and avoids inventing a Chaptarr-specific runtime pattern.

Alternatives considered:
- Run Chaptarr with a custom pod, sidecar, or special storage contract. Rejected because the container already behaves like an arr-style app with a `config.xml`, health endpoint, and PUID/PGID support.
- Keep Chaptarr ephemeral and rely on upstream defaults. Rejected because the API key and runtime state would drift across container replacement.

### Decision: Use separate books and audiobooks library roots shared by Chaptarr and Grimmory
Chaptarr will mount `/mnt/share/Library/Books` and `/mnt/share/Library/Audiobooks`, and Grimmory will mount those same roots so the acquisition service and the consumption UI see the same durable content. This respects the user's stated consumption model while keeping media type boundaries explicit instead of collapsing everything into one mixed tree.

Alternatives considered:
- Mount only `Books` and defer audiobooks. Rejected because the user explicitly created `/mnt/share/Library/Audiobooks` and wants audiobooks consumed through Grimmory as well.
- Give Grimmory different library paths from Chaptarr. Rejected because it would require manual copy/sync steps and break the shared-library intent.

### Decision: Keep shared downloads aligned with the existing arr stack
Chaptarr will mount `/mnt/share/Downloads:/downloads` exactly like the other arr services rather than exposing separate `Torrent` or `Usenet` submounts. This preserves the current download layout and allows Chaptarr to process both sources without introducing a divergent path contract.

Alternatives considered:
- Mount only selected download subdirectories. Rejected because the user asked for the same mount model as the other arr services and wants both `Torrent` and `Usenet` visible.
- Give Chaptarr dedicated download roots. Rejected because it would fragment the current acquisition flow and require extra downloader coordination.

### Decision: Make Grimmory-first consumption a shared-storage relationship, not an app integration
The change will stop at shared library visibility: Grimmory gets books and audiobooks mounted, and Chaptarr writes into those same roots. No repo-managed API bridge, import hook, or metadata sync will be added between the two applications. This keeps the change within the current operational model and avoids coupling two upstream apps that do not already have a clear integration contract in the repo.

Alternatives considered:
- Build a Grimmory import or webhook integration. Rejected because there is no existing integration surface in this repo and it would add new behavioral assumptions beyond simple stack composition.
- Use Chaptarr as the primary consumption UI and leave Grimmory unchanged. Rejected because the user explicitly wants Grimmory first.

### Decision: Place Chaptarr in Muximux with the rest of the arr stack ahead of non-arr utilities
The declarative Muximux layout will treat Chaptarr as part of the arr block rather than a general utility. The intended ordering is that Chaptarr appears with Sonarr, Radarr, Prowlarr, and Bazarr before entries like `n8n` and PriceBuddy, while still acknowledging that the live host may need manual cleanup after deployment.

Alternatives considered:
- Place Chaptarr near Grimmory because both touch book media. Rejected because Chaptarr is operationally an arr-style manager, not the reading surface.
- Append Chaptarr at the end of the dropdown. Rejected because it weakens discoverability and breaks the user's request to keep it with the arr stack.

## Risks / Trade-offs

- [Grimmory and Chaptarr both see the same writable library trees] → Keep this change limited to shared mounts and avoid adding extra automation that could create conflicting file operations; if Grimmory's network-storage mode becomes necessary later, capture that as a follow-up.
- [Public access for `chaptarr.ghostship.io` may require external tunnel work] → Treat Cloudflare/tunnel routing as an explicit rollout dependency outside the repo-managed Nix activation.
- [Homepage may not have a Chaptarr-native widget type] → Use the closest supported arr-style widget contract during implementation and verify against the generated API/auth shape.
- [Muximux live ordering can drift from declarative intent] → Document the desired order in spec/design and verify the live host after deployment, with manual reorder if needed.
- [Shared downloads can expose more than Chaptarr strictly needs] → Accept this to preserve path consistency with the existing arr stack and reduce downloader configuration complexity.

## Migration Plan

1. Add the new `chaptarr` self-hosted module, import it into the stack, and wire a new `chaptarr-secrets` secret bundle.
2. Add plaintext secret stubs to `secrets.dec.yaml` for operator-filled Chaptarr values.
3. Update Grimmory so both `/mnt/share/Library/Books` and `/mnt/share/Library/Audiobooks` are mounted into the reader service.
4. Add Homepage and Muximux entries for Chaptarr using the repo-managed dashboard generation flow.
5. Deploy the updated host configuration to `chill-penguin`.
6. Verify Chaptarr health, config persistence, shared library visibility, Grimmory visibility of both roots, and dashboard placement.
7. Perform any required manual Muximux reorder or external Cloudflare/tunnel route work on the live host.

Rollback: remove the Chaptarr module import and dashboard entries, revert the Grimmory audiobook mount if needed, redeploy the previous host generation, and leave `/srv/apps/chaptarr` in place unless the user explicitly wants state cleanup.

## Open Questions

- Whether the Cloudflare route for `chaptarr.ghostship.io` already exists or must be added during rollout.
- Whether Grimmory should eventually switch to a stricter shared-storage mode if writable access on network-backed library mounts causes operational issues.
- Whether Chaptarr should reuse a Homepage widget contract intended for Readarr or fall back to a generic service tile during implementation.
