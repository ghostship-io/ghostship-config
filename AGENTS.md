# Project Agent Memory

- `powershell.exe -File` needs a Windows path such as `C:\...`, not a WSL
  `/mnt/c/...` path.
- WSL `hardware-configuration.nix` files should stay minimal and omit
  generated pseudo-filesystems such as `/mnt/wsl*`, `/usr/lib/wsl/*`,
  `/mnt/c`, and `/tmp/.X11-unix`.
- `.envrc` uses `use flake`, so the root `flake.nix` must expose either
  `devShells.<system>.default` or `packages.<system>.default`.
- `nix eval .#...` reads tracked flake content, not arbitrary untracked files.
  Stage or track new files before relying on flake evaluation.
- If generated config depends on secrets, render it in the relevant service
  `preStart`, not in `system.activationScripts`.
- Do not expose container ports on the host except where the repo already does
  so intentionally.
- Preferred `chill-penguin` deploy flow is local `git push origin main`, then
  remote `git -C /home/nixos/nixos-config pull --ff-only origin main`, remote
  `nixos-rebuild build --flake .#chill-penguin`, and remote
  `./result/bin/switch-to-configuration switch`.
- If `git push` is unavailable or fails, stop and ask the user to fix push
  access instead of inventing another deployment path.
