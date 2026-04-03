## 1. Hermes Module Update

- [x] 1.1 Update `modules/self-hosted/hermes.nix` so `/srv/apps/hermes/home`
      mounts to `/opt/data` and `/srv/apps/hermes/workspace` mounts to
      `/workspace` while keeping the existing host paths unchanged.
- [x] 1.2 Reintroduce a named Hermes `/nix` volume in the container definition
      and remove any remaining module assumptions that `/home/hermes/.hermes`
      or `/home/hermes/workspace` are the contractual mount targets.

## 2. Contract And Docs Refresh

- [x] 2.1 Update the repo documentation to describe `/opt/data`,
      `/workspace`, and persisted `/nix` as the Hermes runtime contract in
      `README.md`, `CHANGELOG.md`, and `AGENTS.md`.
- [x] 2.2 Ensure any host-activation or verification notes for Hermes now refer
      to the workstation layout and no longer describe `/nix` as unnecessary or
      `/home/hermes/workspace` as the canonical path.

## 3. Verification And Rollout

- [ ] 3.1 Verify the NixOS config evaluates and builds for Hermes with
      `nixos-rebuild build --flake .#chill-penguin -L`.
- [ ] 3.2 Verify on the target host that the recreated Hermes container mounts
      `/opt/data`, `/workspace`, and the named `/nix` volume, and that the
      existing `/srv/apps/hermes/*` host data remains intact after cutover.
