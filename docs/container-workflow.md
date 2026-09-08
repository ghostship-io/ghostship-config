# Development from the T3 Code container

Work in `/workspace/nixos-config` as the existing `t3code` user. This is a
Linux development container with a Nix daemon, not one of the fleet's NixOS
hosts. T3 Code, Codex, OpenCode, and Antigravity are maintained by the container
environment. Keep their existing launchers, credentials, and configuration.
Do not apply `home/profiles/develop.nix` or run
`ghostship-agent-maintenance` here; those target the NixOS develop hosts.

## Project tools and validation

Use the repository's pinned tools from any agent terminal:

```sh
cd /workspace/nixos-config
nix develop -c scripts/check
```

The default shell supplies Git, GitHub CLI, SSH, Nix, formatting and shell
validation tools, Node.js, Python, Age, and SSH-to-Age. It inherits
the container's agent launchers and authentication environment. It does not
require a login shell, Home Manager, Windows paths, or local root access.

For automatic shell activation, copy `.envrc.example` to `.envrc` if no local
file exists, then run `direnv allow`. `.envrc` stays ignored so existing local
environment settings and secrets are preserved. Non-interactive agent commands
can always use `nix develop -c` without direnv shell integration.

Use `nix develop .#browser` when a test needs local Playwright browser binaries
and `PLAYWRIGHT_BROWSERS_PATH`. Ordinary Nix work does not download those
browsers. The browser shell inherits the default tools. Browser tests still
need the relevant project's JavaScript dependencies and any site credentials.

Use `nix develop .#secrets` for `ragenix`. This shell also inherits the default
tools and may build the pinned Rust application on first use; ordinary
validation does not need that build.

`scripts/check` parses all tracked Nix files, runs ShellCheck on the workflow
script, checks patch whitespace, and evaluates default/browser/secrets shells for
`x86_64-linux` and `aarch64-linux` plus every host's full system derivation.
It uses the checked-in lock file without updating it. Stage new Nix files
before running checks. These checks validate module assertions and derivation
construction; target-host builds and live verification remain necessary for
deployment.

GitHub Actions runs this same command for PRs and pushes to `main`. A single
Linux job evaluates both architectures without building their systems, and
new pushes cancel superseded runs. Review CI and any Codex review comments
before marking a draft PR ready. Leave merging to the user.

## Git access

The container may provide GitHub token authentication without an SSH key.
Check access with `gh auth status`. For this checkout, HTTPS can use that
authentication without storing the token in the repository or changing global
Git configuration:

```sh
git remote set-url origin https://github.com/ghostship-io/ghostship-config.git
git config --local credential.https://github.com.helper '!gh auth git-credential'
git ls-remote origin HEAD
```

Keep an existing SSH remote if its key is available. Use a named branch or
worktree, verify and commit changes, push, and open a draft PR. The repo's
`VERSION` and `CHANGELOG.md` track workflow changes as patch releases.

## Remote deployment

The container hostname identifies the coding environment. Always select the
target explicitly instead of using `.#$(hostname)` here. Host configuration
can be evaluated without root:

```sh
nix develop -c nix eval --raw \
  .#nixosConfigurations.chill-penguin.config.system.build.toplevel.drvPath
```

Provision the target's approved SSH identity and verified host key through the
container's persistent credential setup before deploying. The `chill-penguin`
SSH alias must select root on the real host. GitHub token access alone does
not provide host SSH access. Check it non-interactively:

```sh
ssh -o BatchMode=yes -o ConnectTimeout=10 chill-penguin id -u
```

The result must be `0`. If SSH access or Git push is unavailable, fix that
access before deployment. Do not substitute container-local activation or copy
uncommitted files onto the host.

After the user merges the PR, make sure the intended commit is on
`origin/main`. For an authorized deployment, use `ssh chill-penguin` and the
host checkout at `/home/nixos/nixos-config` to run these commands as root:

```sh
git -C /home/nixos/nixos-config pull --ff-only origin main
cd /home/nixos/nixos-config
nixos-rebuild build -L --impure --flake .#chill-penguin
./result/bin/switch-to-configuration switch
```

Run long or prompt-driven remote work in detached tmux, then inspect its output
with `capture-pane` and provide input with `send-keys`. The `--impure` flag on
Chill Penguin allows extraction from its local `/boot/asahi` firmware; the
container's pure evaluation cannot validate that hardware-specific step.
Verify affected live services after switching. Other hosts use their own
explicit flake target, root SSH access, and host-specific deployment procedure.
