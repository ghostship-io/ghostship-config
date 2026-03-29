# Nix Command Reference

| Task | Command |
| :--- | :--- |
| **Apply OS Config** | `sudo nixos-rebuild switch --flake .#(hostname)` |
| **Boot OS Config** | `sudo nixos-rebuild boot --flake .#(hostname)` |
| **Build OS Config** | `sudo nixos-rebuild build --flake .#(hostname)` |
| **Search Packages** | `nix search nixpkgs <pkg>` |
| **System Clean** | `sudo nix-collect-garbage -d` |
| **Update Flake** | `nix flake update` |
