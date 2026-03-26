{ ... }:

{
  imports = [
    ./wsl.nix
    ./wsl-mounts.nix
    ./secrets.nix
    ./gemini-wrapper.nix
    ./gemini.nix
    ./opencode-wrapper.nix
    ./codex-wrapper.nix
  ];
}
