## Migration Plan

### Goal
Move the repo and live hosts from the old `sops-nix` plus `secrets.yaml` workflow to the new `ragenix` plus logical-unit `.age` files, while keeping `secrets.dec.yaml` as the ignored plaintext mirror and minimizing service risk on `chill-penguin`.

### Phase 1: Review And Finalize Repo State
- Review the branch diff before merge.
- Confirm the operator edit key in `~/.ssh/id_ed25519_ragenix.pub` is the one that should remain in `secrets/recipients.nix`.
- Confirm the tracked recipient groups match the intended initial rollout scope.

### Phase 2: Validate Secret Data Shape
- Treat `secrets.dec.yaml` as the human edit surface.
- For each logical unit in `secrets/catalog.nix`, verify the plaintext mirror entry exists and matches the expected env-style content.
- Run `secrets-reencrypt` after any mirror edits so the tracked `.age` files stay current.
- Use `secret-list` and `secrets-list-keys` to spot missing or stale logical units before host rollout.

### Phase 3: Roll Out A Develop Host First
- Merge the branch into `main`.
- Apply the merged config on `launch-octopus` first.
- Verify the dedicated edit-key flow with `secret-edit-keygen`, `secrets-edit`, and `secrets-reencrypt`.
- Confirm activation prints the SSH host `ed25519` public key and that the develop host behaves normally after the rebuild.

### Phase 4: Validate Server Wiring Before Switching
- On `chill-penguin`, pull the merged repo and run `nix eval` or `nixos-rebuild build` against `.#chill-penguin`.
- Inspect the projected secret surfaces for the highest-risk consumers: Homepage, Hermes, Bazarr, Recyclarr, Tautulli, and Cloudflared.
- Confirm the generated runtime env files contain only the expected keys.

### Phase 5: Cut Over `chill-penguin`
- Apply the built generation on `chill-penguin`.
- Check service startup and auth-dependent behavior for Homepage, Cloudflared, Hermes, the arr stack, and Tautulli/Plex integration.
- Keep the branch history available until the server rollout is confirmed stable.

### Phase 6: Start Using The New Intake Flow
- Use `sudo ./bootstrap.sh <hostname> [output-dir]` for new-host capture.
- On WSL2, confirm the bootstrap flow generated or validated `/etc/ssh/ssh_host_ed25519_key.pub`.
- Copy the capture bundle into `references/host-intake/<hostname>/`, ask Codex to integrate it, review the resulting changes, then remove the temporary staged intake directory.

### Rollback Posture
- Treat `launch-octopus` as the first live checkpoint.
- Treat `chill-penguin` as the real migration gate.
- If server rollout finds a regression, stop at the repo level and fix forward from the merged `main` state or temporarily reapply the previous generation on the host.
