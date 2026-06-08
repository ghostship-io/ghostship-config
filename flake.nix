{
  description = "Unified NixOS Configuration Repository";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

    codex-web.url = "github:0xcaff/codex-web";

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

      codexManagedSkills = [
        "autoreview"
        "ghostship-audit-worktree"
        "ghostship-merge-worktree"
        "ghostship-pull-worktree"
        "grill-me"
      ];

      mkCodexAgentToolingInstaller =
        pkgs:
        pkgs.writeShellApplication {
          name = "install-codex-agent-tooling";
          runtimeInputs = with pkgs; [
            coreutils
            gnugrep
          ];
          text = ''
            set -eu

            run_maintenance=1
            target_home="''${CODEX_TOOLING_HOME:-''${HOME:-}}"

            while [ "$#" -gt 0 ]; do
              case "$1" in
                --home)
                  if [ "$#" -lt 2 ]; then
                    printf 'error: --home requires a path\n' >&2
                    exit 2
                  fi
                  target_home="$2"
                  shift 2
                  ;;
                --no-maintenance)
                  run_maintenance=0
                  shift
                  ;;
                -h|--help)
                  cat <<'EOF'
            Usage: install-codex-agent-tooling [--home PATH] [--no-maintenance]

            Installs this repo's Codex agent tooling into a user home:
              .local/bin/ghostship-agent-maintenance
              .codex/AGENTS.md
              .gemini/GEMINI.md
              .config/opencode/AGENTS.md
              .agents/skills/*

            By default it runs ghostship-agent-maintenance after copying files.
            EOF
                  exit 0
                  ;;
                *)
                  printf 'error: unknown argument: %s\n' "$1" >&2
                  exit 2
                  ;;
              esac
            done

            if [ -z "$target_home" ]; then
              printf 'error: HOME is not set; pass --home PATH\n' >&2
              exit 2
            fi

            resolve_store_path() {
              path="$1"
              if [ -e "$path" ]; then
                printf '%s\n' "$path"
                return 0
              fi

              case "$path" in
                /nix/store/*)
                  root_home="''${HOME:-$target_home}"
                  root="''${NIX_STORE_ROOT:-$root_home/.local/share/nix/root}"
                  if [ -e "$root$path" ]; then
                    printf '%s\n' "$root$path"
                    return 0
                  fi
                  ;;
              esac

              printf 'error: required installer source is missing: %s\n' "$path" >&2
              exit 1
            }

            install -d \
              "$target_home/.local/bin" \
              "$target_home/.codex" \
              "$target_home/.gemini" \
              "$target_home/.config/opencode" \
              "$target_home/.agents/skills"

            maintenance_src="$(resolve_store_path ${./modules/self-hosted/codex-agent-maintenance.sh})"
            agents_src="$(resolve_store_path ${./home/config/AGENTS.md})"

            install -m0755 "$maintenance_src" "$target_home/.local/bin/ghostship-agent-maintenance"
            install -m0644 "$agents_src" "$target_home/.codex/AGENTS.md"
            install -m0644 "$agents_src" "$target_home/.gemini/GEMINI.md"
            install -m0644 "$agents_src" "$target_home/.config/opencode/AGENTS.md"

            install_agent_wrapper() {
              name="$1"
              binary="$2"
              cat > "$target_home/.local/bin/$name" <<EOF
            #!/usr/bin/env sh
            set -eu
            find_nix_glibc_loader() {
              case "\$(uname -m)" in
                aarch64|arm64)
                  loader_name="ld-linux-aarch64.so.1"
                  ;;
                x86_64|amd64)
                  loader_name="ld-linux-x86-64.so.2"
                  ;;
                *)
                  return 1
                  ;;
              esac

              for store_dir in /nix/store "$target_home/.local/share/nix/root/nix/store"; do
                if [ ! -d "\$store_dir" ]; then
                  continue
                fi

                for candidate in "\$store_dir"/*-glibc-*/lib/"\$loader_name"; do
                  if [ -x "\$candidate" ]; then
                    printf '%s\n' "\$candidate"
                    return 0
                  fi
                done
              done

              return 1
            }

            agent_bin="$target_home/.local/share/ghostship-agent-tools/npm/bin/$binary"
            if [ "$name" = "opencode" ]; then
              for candidate in "$target_home"/.local/share/ghostship-agent-tools/npm/lib/node_modules/opencode-linux-*/bin/opencode; do
                if [ -x "\$candidate" ]; then
                  agent_bin="\$candidate"
                  break
                fi
              done
            fi
            if [ ! -x "\$agent_bin" ]; then
              printf 'error: %s is not installed yet; run ghostship-agent-maintenance\n' "$name" >&2
              exit 1
            fi
            case "\$agent_bin" in
              */opencode-linux-*/bin/opencode)
                if loader="\$(find_nix_glibc_loader)"; then
                  exec "\$loader" --library-path "\''${loader%/*}" "\$agent_bin" "\$@"
                fi
                ;;
            esac
            exec "\$agent_bin" "\$@"
            EOF
              chmod 0755 "$target_home/.local/bin/$name"
            }

            install_agent_wrapper codex codex
            install_agent_wrapper gemini gemini
            install_agent_wrapper gemini-cli gemini
            install_agent_wrapper opencode opencode
            install_agent_wrapper skills skills

            ${nixpkgs.lib.concatMapStrings (skill: ''
              skill_src="$(resolve_store_path ${./home/config/skills/${skill}})"
              rm -rf "$target_home/.agents/skills/${skill}"
              cp -R --no-preserve=ownership,mode "$skill_src" "$target_home/.agents/skills/${skill}"
              chmod -R u+rwX,go+rX "$target_home/.agents/skills/${skill}"
            '') codexManagedSkills}

            printf 'installed Codex agent tooling into %s\n' "$target_home"

            if [ "$run_maintenance" -eq 1 ]; then
              HOME="$target_home" "$target_home/.local/bin/ghostship-agent-maintenance"
            fi
          '';
        };

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

      packages = forAllSystems (
        system:
        let
          pkgs = pkgsFor system;
        in
        {
          install-codex-agent-tooling = mkCodexAgentToolingInstaller pkgs;
          default = mkCodexAgentToolingInstaller pkgs;
        }
      );

      apps = forAllSystems (
        system:
        {
          install-codex-agent-tooling = {
            type = "app";
            program = "${self.packages.${system}.install-codex-agent-tooling}/bin/install-codex-agent-tooling";
          };
          default = self.apps.${system}.install-codex-agent-tooling;
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
