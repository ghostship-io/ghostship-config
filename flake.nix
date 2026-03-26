{
  description = "Unified NixOS Configuration Repository";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    nixpkgs-unstable.url = "github:NixOS/nixpkgs/nixos-unstable";

    home-manager = {
      url = "github:nix-community/home-manager/master";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    nixos-hardware.url = "github:NixOS/nixos-hardware/master";

    sops-nix = {
      url = "github:Mic92/sops-nix";
    };

    nixos-wsl = {
      url = "github:nix-community/NixOS-WSL/main";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    nix-index-database = {
      url = "github:Mic92/nix-index-database";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    apple-silicon = {
      url = "github:nix-community/nixos-apple-silicon/main";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = { self, nixpkgs, home-manager, nixos-wsl, nix-index-database, apple-silicon, ... }@inputs: 
    {
    nixosConfigurations = {
      launch-octopus = nixpkgs.lib.nixosSystem {
        specialArgs = { inherit inputs self; };
        modules = [
          nixos-wsl.nixosModules.default
          inputs.sops-nix.nixosModules.sops
          ./hosts/launch-octopus/default.nix
          home-manager.nixosModules.home-manager
          {
            home-manager.useGlobalPkgs = true;
            home-manager.useUserPackages = true;
            home-manager.users.nixos = ./home/nixos.nix;
            home-manager.sharedModules = [ nix-index-database.homeModules.nix-index ];
          }
        ];
      };

      # chill-penguin: Mac Studio M1 Ultra - fresh install using nixos-apple-silicon
      chill-penguin = nixpkgs.lib.nixosSystem {
        specialArgs = { inherit inputs self; };
        modules = [
          apple-silicon.nixosModules.apple-silicon-support
          inputs.sops-nix.nixosModules.sops
          ./hosts/chill-penguin/default.nix
          home-manager.nixosModules.home-manager
          {
            home-manager.useGlobalPkgs = true;
            home-manager.useUserPackages = true;
            home-manager.users.nixos = ./home/nixos.nix;
            home-manager.sharedModules = [ nix-index-database.homeModules.nix-index ];
          }
        ];
      };

      armored-armadillo = nixpkgs.lib.nixosSystem {
        specialArgs = { inherit inputs self; };
        modules = [
          nixos-wsl.nixosModules.default
          inputs.sops-nix.nixosModules.sops
          ./hosts/armored-armadillo/default.nix
          home-manager.nixosModules.home-manager
          {
            home-manager.useGlobalPkgs = true;
            home-manager.useUserPackages = true;
            home-manager.users.nixos = ./home/nixos.nix;
            home-manager.sharedModules = [ nix-index-database.homeModules.nix-index ];
          }
        ];
      };

      boomer-kuwanger = nixpkgs.lib.nixosSystem {
        specialArgs = { inherit inputs self; };
        modules = [
          inputs.nixos-hardware.nixosModules.common-cpu-amd
          inputs.nixos-hardware.nixosModules.common-gpu-amd
          inputs.nixos-hardware.nixosModules.common-pc-ssd
          inputs.sops-nix.nixosModules.sops
          ./hosts/boomer-kuwanger/default.nix
          home-manager.nixosModules.home-manager
          {
            home-manager.useGlobalPkgs = true;
            home-manager.useUserPackages = true;
            home-manager.users.nixos = ./home/nixos.nix;
            home-manager.sharedModules = [ nix-index-database.homeModules.nix-index ];
          }
        ];
      };
    };

  };
}
