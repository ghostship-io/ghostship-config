## Why

Ghostship does not currently have an arr-style service for managing ebooks and audiobooks alongside the existing Sonarr, Radarr, Prowlarr, and Bazarr stack. Adding Chaptarr now closes that gap while aligning the book and audiobook acquisition flow with the shared library model you want to consume primarily through Grimmory.

## What Changes

- Add a new self-hosted `chaptarr` service to the `chill-penguin` stack with persisted config, arr-style runtime defaults, and internal network access on `ghostship_net`.
- Mount shared downloads into Chaptarr using the same `/mnt/share/Downloads:/downloads` pattern as the other arr services so it can process both `Torrent` and `Usenet` content.
- Mount both `/mnt/share/Library/Books` and `/mnt/share/Library/Audiobooks` into Chaptarr so it can manage ebook and audiobook library roots separately.
- Add plaintext secret scaffolding for Chaptarr in `secrets.dec.yaml`, and wire a new `chaptarr-secrets` bundle into the NixOS service configuration for operator-supplied values such as the API key.
- Update Grimmory so it mounts both the books and audiobooks library roots, making Grimmory the first-class consumption surface for both media types.
- Add Chaptarr to Homepage under the existing automation services and add a declarative Muximux entry with the rest of the arr stack.
- Document any host activation or public-route caveats for exposing `chaptarr.ghostship.io` through the existing Cloudflare workflow.

## Capabilities

### New Capabilities
- `chaptarr-service`: Adds a Chaptarr runtime with persisted config, shared downloads access, separate books and audiobooks library mounts, secret-backed API configuration, and Grimmory-aligned library exposure.

### Modified Capabilities
- `muximux-service-placement`: Extend the generated Muximux layout so Chaptarr appears with the rest of the arr stack, with rollout notes if the live host still needs any manual ordering cleanup after deployment.

## Impact

- Affects server-host NixOS modules under `modules/self-hosted/`, including a new `chaptarr` module plus updates to `default.nix`, `homepage.nix`, `muximux.nix`, `grimmory.nix`, and `secrets.nix`.
- Requires plaintext secret stubs in `secrets.dec.yaml`; encrypted `secrets.yaml` updates remain an operator-managed follow-up.
- Requires host activation on `chill-penguin` and likely a separate Cloudflare/tunnel route for `chaptarr.ghostship.io`, since public ingress for these services is not repo-managed.
