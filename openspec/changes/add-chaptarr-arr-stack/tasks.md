## 1. Service and secret scaffolding

- [ ] 1.1 Add a new `modules/self-hosted/chaptarr.nix` module and import it from `modules/self-hosted/default.nix`.
- [ ] 1.2 Register `chaptarr-secrets` in `modules/self-hosted/secrets.nix` and add plaintext Chaptarr stubs to `secrets.dec.yaml` for operator-filled values.
- [ ] 1.3 Configure the Chaptarr container with persisted config under `/srv/apps/chaptarr`, healthchecks, `ghostship_net`, and arr-style runtime defaults backed by activation-time config shaping.

## 2. Shared storage and dashboard integration

- [ ] 2.1 Mount `/mnt/share/Downloads:/downloads`, `/mnt/share/Library/Books`, and `/mnt/share/Library/Audiobooks` into Chaptarr.
- [ ] 2.2 Update `modules/self-hosted/grimmory.nix` so Grimmory mounts both `/mnt/share/Library/Books` and `/mnt/share/Library/Audiobooks` while keeping its existing data and bookdrop mounts intact.
- [ ] 2.3 Add Chaptarr to `modules/self-hosted/homepage.nix` under the `Automation` group using the appropriate service tile or widget contract.
- [ ] 2.4 Update `modules/self-hosted/muximux.nix` so Chaptarr appears after Bazarr and before `n8n`, with rollout notes for any required manual host-side reorder.

## 3. Verification and rollout readiness

- [ ] 3.1 Run `nix-instantiate --parse modules/self-hosted/chaptarr.nix` and any touched module files to catch syntax errors before a host build.
- [ ] 3.2 Run `nixos-rebuild build --flake .#chill-penguin -L` to verify the host configuration evaluates and builds with the new Chaptarr and Grimmory mount changes.
- [ ] 3.3 Verify the generated dashboard and service config outputs reflect the intended Chaptarr placement, shared library mounts, and secret references.
- [ ] 3.4 Document any required external Cloudflare/tunnel route setup for `chaptarr.ghostship.io` and any manual post-deploy Muximux ordering cleanup.

## 4. Documentation and handoff

- [ ] 4.1 Update `README.md` with the new Chaptarr service, shared books/audiobooks library model, and Grimmory-first consumption notes.
- [ ] 4.2 Update `CHANGELOG.md` with the Chaptarr stack addition and Grimmory library mount expansion.
- [ ] 4.3 Update `AGENTS.md` with any durable operational notes that future agents need for Chaptarr, Grimmory shared storage, or post-deploy cleanup.
