## 1. Add the BookStack stack modules

- [x] 1.1 Add a `bookstack-secrets` declaration in `modules/self-hosted/secrets.nix` for the new service credential bundle.
- [x] 1.2 Add a `modules/self-hosted/bookstack-db.nix` module that declares the managed database container, durable state path, and generated DB env file using `BOOKSTACK_DB_DATABASE`, `BOOKSTACK_DB_USER`, `BOOKSTACK_DB_PASS`, and `BOOKSTACK_DB_ROOT_PASS`.
- [x] 1.3 Add a `modules/self-hosted/bookstack.nix` module that declares the BookStack container, durable app state, generated runtime env, healthcheck, and dependency on the managed database service, using `BOOKSTACK_APP_KEY` and external `BOOKSTACK_APP_URL`.
- [x] 1.4 Import the new BookStack modules from `modules/self-hosted/default.nix`.

## 2. Wire Hermes and surface BookStack

- [x] 2.1 Update `modules/self-hosted/homepage.nix` so Homepage emits a BookStack entry under the `Services` group.
- [x] 2.2 Update `modules/self-hosted/hermes.nix` so Hermes receives `BOOKSTACK_URL`, `BOOKSTACK_TOKEN_ID`, and `BOOKSTACK_TOKEN_SECRET` through the managed utility env projection.
- [x] 2.3 Update `README.md`, `CHANGELOG.md`, and any affected repo guidance to describe the new BookStack service, its external URL, the Hermes env contract, and the required manual BookStack bootstrap/API-token setup.
- [x] 2.4 Update `AGENTS.md` only if the final implementation adds durable repo-specific operator guidance worth reloading later.

## 3. Verify the host configuration

- [x] 3.1 Run `nix eval .#nixosConfigurations.chill-penguin.config.system.build.toplevel` to confirm the host configuration evaluates with the new BookStack modules and Hermes env projection.
- [ ] 3.2 Run `nixos-rebuild build -L --flake .#chill-penguin` or an equivalently scoped build to verify the BookStack stack composes successfully before deployment.
- [x] 3.3 Confirm the apply notes cover activation, persistent state paths, Homepage visibility, Hermes runtime env projection, manual BookStack setup, and any required external ingress follow-up.
