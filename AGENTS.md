# Project Agent Memory

Use this file as the repo-specific operating memory.

Keep entries short, durable, and worth reloading. Do not turn this file into a
changelog or host incident log.

## Workflow and Scope

- `home/config/AGENTS.md` is the cross-repo preference layer. Keep this file
  repo-specific.
- Verified work should be committed before task completion.
- If a change needs planning, do it in a git worktree.
- Use the `nix` skill for Nix and NixOS work, the `python` skill for Python
  work, and `openspec-explore` for repo research when available.
- Repo-local agent assets live under `.codex/`, `.gemini/`, `.opencode/`, and
  `openspec/`.
- `.envrc` uses `use flake`, so the root `flake.nix` must expose either
  `devShells.<system>.default` or `packages.<system>.default`.
- `nix eval .#...` reads tracked flake content, not arbitrary untracked files.
  Stage or track new files before relying on flake evaluation.

## WSL and Host Basics

- Prefer `/mnt/c/...` for Windows files. Treat `/mnt/z` as optional and verify
  it before use.
- Use explicit Windows paths or repo-managed wrappers for Windows executables;
  bare imported PATH tools are unreliable on this host.
- `powershell.exe -File` needs a Windows path such as `C:\...`, not a WSL
  `/mnt/c/...` path.
- `wsl.extraBin` changes may require a full WSL restart after
  `nixos-rebuild switch`.
- On switched NixOS and NixOS-WSL systems, `/etc/hostname` and `/etc/wsl.conf`
  can be store symlinks. Keep persistent changes declarative.
- WSL `hardware-configuration.nix` files should stay minimal and omit generated
  pseudo-filesystems such as `/mnt/wsl*`, `/usr/lib/wsl/*`, `/mnt/c`, and
  `/tmp/.X11-unix`.

## Nix and Config Patterns

- Use native `nix`, `nixos-rebuild`, and `switch-to-configuration` commands in
  repo docs and operations. Prefer `-L` for build logs.
- On WSL hosts, cap both `nix.settings.max-jobs` and `nix.settings.cores`;
  `auto` and `0` have caused daemon stalls under load.
- Keep `git` before `age` in `flake.nix` dev-shell packages on this host or
  `nix print-dev-env` can fail.
- If generated config depends on secrets, render it in the relevant service
  `preStart`, not in `system.activationScripts`.
- Use `pkgs.yq-go` when rewriting INI or YAML where scalar types matter.
- The NixOS OCI container module has no generic `healthcheck` option; keep
  healthchecks in Podman `extraOptions`.
- Prefer `pull = "always";` for OCI containers in this repo.
- Do not expose container ports on the host except where the repo already does
  so intentionally.

## Remote Work and Deployment

- Do not use `sudo` in agent workflows. Use a root shell or `ssh
  chill-penguin-root`.
- For prompt-driven remote work, run the remote command in detached tmux and
  interact with it via `capture-pane` and `send-keys` instead of blocking SSH
  TTY sessions.
- This repo deploys through Git on the host. Do not ask the user to validate
  host-side changes until the repo edits are committed and available to the
  host checkout.
- Preferred `chill-penguin` deploy flow is local `git push origin main`, then
  remote `git -C /home/nixos/nixos-config pull --ff-only origin main`, remote
  `nixos-rebuild build --flake .#chill-penguin`, and remote
  `./result/bin/switch-to-configuration switch`.
- If activation fails after a successful build, apply the built generation
  directly with `/nix/store/<system>/bin/switch-to-configuration switch`.
- If `git push` is unavailable or fails, stop and ask the user to fix push
  access instead of inventing another deployment path.

## Secrets and Bootstrap

- The tracked secret model lives under `secrets/`: `recipients.nix` composes
  recipients and groups, `catalog.nix` declares logical secret files plus
  exports, and `rules.nix` feeds `ragenix`.
- Runtime decryption uses SSH host `ed25519` keys. Human edit access uses
  `~/.ssh/id_ed25519_ragenix`.
- Normal operator flow is `secret-edit <logical-secret-name>` against tracked
  `.age` files. Use `secret-rekey` only for recipient changes.
- Keep `secrets/rules.nix` paths relative to `secrets/`, not repo-root paths
  prefixed with `secrets/`.
- Prefer service-local `*-secrets` bundles and catalog-driven projections over
  shared catch-all bundles.
- `bootstrap.sh` is the installer-time host bootstrap entrypoint.
- `references/host-intake/<hostname>/` is temporary staging for host
  integration and should be removed after integration completes.
