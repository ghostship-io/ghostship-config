## 1. Add the BookStack stack modules

- [ ] 1.1 Add a `bookstack-secrets` declaration in `modules/self-hosted/secrets.nix` for the new service credential bundle.
- [ ] 1.2 Add a `modules/self-hosted/bookstack-db.nix` module that declares the managed database container, durable state path, and generated DB env file using `BOOKSTACK_DB_DATABASE`, `BOOKSTACK_DB_USER`, `BOOKSTACK_DB_PASS`, and `BOOKSTACK_DB_ROOT_PASS`.
- [ ] 1.3 Add a `modules/self-hosted/bookstack.nix` module that declares the BookStack container, durable app state, generated runtime env, healthcheck, and dependency on the managed database service, using `BOOKSTACK_APP_KEY` and external `BOOKSTACK_APP_URL`.
- [ ] 1.4 Import the new BookStack modules from `modules/self-hosted/default.nix`.

## 2. Surface BookStack and document the manual setup

- [ ] 2.1 Update `modules/self-hosted/homepage.nix` so Homepage emits a BookStack entry under the `Services` group.
- [ ] 2.2 Update `README.md`, `CHANGELOG.md`, and any affected repo guidance to describe the new BookStack service, its external URL, and the required manual BookStack bootstrap/API-key setup.
- [ ] 2.3 Update `AGENTS.md` only if the final implementation adds durable repo-specific operator guidance worth reloading later.

## 3. Verify the host configuration

- [ ] 3.1 Run `nix eval .#nixosConfigurations.chill-penguin.config.system.build.toplevel` to confirm the host configuration evaluates with the new BookStack modules.
- [ ] 3.2 Run `nixos-rebuild build -L --flake .#chill-penguin` or an equivalently scoped build to verify the BookStack stack composes successfully before deployment.
- [ ] 3.3 Confirm the apply notes cover activation, persistent state paths, Homepage visibility, manual BookStack setup, and any required external ingress follow-up.
