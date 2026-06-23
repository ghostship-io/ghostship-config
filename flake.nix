{
  description = "Unified NixOS Configuration Repository";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

    home-manager = {
      url = "github:nix-community/home-manager/master";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    nixos-hardware.url = "github:NixOS/nixos-hardware/master";

    ragenix = {
      url = "github:yaxitech/ragenix";
      inputs.nixpkgs.follows = "nixpkgs";
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

  outputs =
    {
      self,
      nixpkgs,
      home-manager,
      nixos-wsl,
      nix-index-database,
      apple-silicon,
      ragenix,
      ...
    }@inputs:
    let
      supportedSystems = [
        "x86_64-linux"
        "aarch64-linux"
      ];
      forAllSystems = nixpkgs.lib.genAttrs supportedSystems;
      pkgsFor = system: nixpkgs.legacyPackages.${system};

      mkHost =
        modules:
        nixpkgs.lib.nixosSystem {
          specialArgs = { inherit inputs self; };
          modules = modules ++ [
            inputs.ragenix.nixosModules.default
            home-manager.nixosModules.home-manager
            {
              home-manager.useGlobalPkgs = true;
              home-manager.useUserPackages = true;
              home-manager.extraSpecialArgs = { inherit inputs self; };
              home-manager.users.nixos = ./home/nixos.nix;
              home-manager.sharedModules = [
                nix-index-database.homeModules.nix-index
              ];
            }
          ];
        };
    in
    {
      devShells = forAllSystems (
        system:
        let
          pkgs = pkgsFor system;
        in
        {
          default = pkgs.mkShellNoCC {
            packages = with pkgs; [
              git
              age
              gnugrep
              gnused
              jq
              nixfmt
              ragenix.packages.${system}.default
              ssh-to-age
            ];
          };
        }
      );

      nixosConfigurations = {
        launch-octopus = mkHost [
          nixos-wsl.nixosModules.default
          ./hosts/launch-octopus/default.nix
        ];

        armored-armadillo = mkHost [
          nixos-wsl.nixosModules.default
          ./hosts/armored-armadillo/default.nix
        ];

        # chill-penguin: Mac Studio M1 Ultra - fresh install using
        # nixos-apple-silicon
        chill-penguin = mkHost [
          apple-silicon.nixosModules.apple-silicon-support
          ./hosts/chill-penguin/default.nix
        ];

        boomer-kuwanger = mkHost [
          inputs.nixos-hardware.nixosModules.common-cpu-amd
          inputs.nixos-hardware.nixosModules.common-gpu-amd
          inputs.nixos-hardware.nixosModules.common-pc-ssd
          ./hosts/boomer-kuwanger/default.nix
        ];
      };
    };
}
