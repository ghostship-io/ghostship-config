# Nix Command Reference

## Principles
- Prefer native `nix`, `nixos-rebuild`, and `switch-to-configuration` commands.
- Build first, then apply. Do not collapse validation and deployment into one step unless there is a specific reason.
- If a command needs elevated privileges, run it from a root shell or a direct root SSH session.
- Prefer `nix shell` over `nix-shell`.
- Use `-L` when you want build logs; omit extra output flags unless they are known to work in the current environment.

## Day-to-Day Commands

### Inspect a flake
```bash
nix flake show
nix flake metadata
```

### Enter a development shell
```bash
nix develop
```

### Run a one-off tool
```bash
nix shell nixpkgs#jq -c jq --version
```

### Build a package or app from the flake
```bash
nix build .#package-name -L
nix run .#app-name -- --help
```

### Evaluate configuration values
```bash
nix eval .#nixosConfigurations.chill-penguin.config.networking.hostName
```

## NixOS Validation

### Build a host configuration
```bash
nixos-rebuild build --flake .#chill-penguin
```

### Inspect the built system closure
```bash
readlink -f ./result
```

### Apply a built system
Run this from the repo root after a successful build:
```bash
./result/bin/switch-to-configuration switch
```

## Remote Deployment

### Update the host checkout
```bash
ssh chill-penguin-root 'git -C /home/nixos/nixos-config pull --ff-only origin main'
```

### Build on the host
```bash
ssh chill-penguin-root 'cd /home/nixos/nixos-config && nixos-rebuild build --flake .#chill-penguin'
```

### Apply on the host
```bash
ssh chill-penguin-root 'cd /home/nixos/nixos-config && ./result/bin/switch-to-configuration switch'
```

## Maintenance

### Garbage-collect old store paths
```bash
nix-collect-garbage -d
```

### Check active and linked system generations
```bash
readlink -f /run/current-system
readlink -f /nix/var/nix/profiles/system
```

## Repo Conventions
- Use `ssh chill-penguin-root` for live work on `chill-penguin`.
- Push local commits to `main`, then pull on the host, then build and apply there.
- If a build succeeds but an apply step returns nonzero, verify `/run/current-system`, `systemctl --failed`, and the relevant service logs before treating it as a bad deployment.
