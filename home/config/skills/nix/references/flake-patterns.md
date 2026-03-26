# Flake Patterns

## Standard NixOS Configuration Flake
```nix
{
  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";
  };
  outputs = { self, nixpkgs, ... }@inputs: {
    nixosConfigurations.host = nixpkgs.lib.nixosSystem {
      specialArgs = { inherit inputs self; };
      modules = [ ./configuration.nix ];
    };
  };
}
```

## Standard Development Shell Flake
```nix
{
  inputs.nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";
  outputs = { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${system};
    in {
      devShells.${system}.default = pkgs.mkShell {
        buildInputs = [ pkgs.git pkgs.neovim ];
      };
    };
}
```
