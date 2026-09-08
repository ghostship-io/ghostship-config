{
  description = "Unified NixOS Configuration Repository";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

    home-manager = {
      url = "github:nix-community/home-manager/master";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    nixos-hardware = {
      url = "github:NixOS/nixos-hardware/master";
      inputs.nixpkgs.follows = "nixpkgs";
    };

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
      checks = forAllSystems (
        system:
        import ./checks.nix {
          pkgs = pkgsFor system;
          inherit self;
        }
      );

      packages = forAllSystems (
        system:
        let
          pkgs = pkgsFor system;
        in
        {
          ghostship-config = (pkgs.extend (import ./modules/common/ghostship-pkg.nix)).ghostship-config;
          codex-desktop-web = pkgs.callPackage ./packages/codex-desktop-web/package.nix { };
        }
      );

      devShells = forAllSystems (
        system:
        let
          pkgs = pkgsFor system;
        in
        {
          # CI needs no downloaded browsers or agent-maintenance tools.
          ci = pkgs.mkShellNoCC {
            packages = with pkgs; [
              git
              actionlint
              shellcheck
              gitleaks
              python3
              ripgrep
              jq
              nodejs_24
              util-linux
              iproute2
            ];
          };
          default = pkgs.mkShellNoCC {
            packages = with pkgs; [
              git
              age
              gnugrep
              ripgrep
              gnused
              jq
              nixfmt
              shellcheck
              actionlint
              gitleaks
              ruff
              (python3.withPackages (ps: [
                ps.lxml
                ps.ruamel-yaml
                ps.bcrypt
                ps.python-socketio
                ps.requests
                ps.websocket-client
              ]))
              nodejs_24
              util-linux
              iproute2
              gnupg
              espeak-ng
              playwright-driver.browsers
              prefetch-npm-deps
              pkgs.ragenix
              ssh-to-age
            ];
            PLAYWRIGHT_BROWSERS_PATH = "${pkgs.playwright-driver.browsers}";
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
