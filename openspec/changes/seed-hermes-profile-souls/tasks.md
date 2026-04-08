## 1. Managed persona sources

- [x] 1.1 Add tracked repo source files for the Toxic Seahorse, Volt Catfish,
      and Crush Crawfish `SOUL.md` content used by the Hermes `assistant`,
      `operations`, and `supervisor` profiles.
- [x] 1.2 Keep the source files in a Hermes-specific repo location that is easy
      to review and reference from the Nix module.

## 2. Hermes runtime seeding

- [x] 2.1 Update `modules/self-hosted/hermes.nix` so Hermes runtime
      preparation creates the per-profile seed directories under
      `/srv/apps/hermes/home/seeds/profiles/`.
- [x] 2.2 Seed each profile `SOUL.md` into
      `/srv/apps/hermes/home/seeds/profiles/<profile>/SOUL.md` only when the
      target file does not already exist.
- [x] 2.3 Verify the seeding logic is non-destructive and does not overwrite an
      existing profile `SOUL.md`.

## 3. Docs and verification

- [x] 3.1 Update `README.md`, `CHANGELOG.md`, and `AGENTS.md` to document the
      managed Hermes profile `SOUL.md` seed behavior and file locations.
- [x] 3.2 Validate the resulting host configuration with:
      `nixos-rebuild build --flake .#chill-penguin -L`
