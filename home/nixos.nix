{ config, lib, pkgs, osConfig, ... }:

{
  imports = lib.optional (osConfig.wsl.enable or false) ./wsl.nix
    ++ [ ../modules/develop/opencode.nix ../modules/develop/codex.nix ];

  home.username = lib.mkDefault "nixos";
  home.homeDirectory = lib.mkDefault "/home/${config.home.username}";

  # This value determines the Home Manager release that your configuration is
  # compatible with. This helps avoid breakage when a new Home Manager release
  # introduces backwards incompatible changes.
  #
  # You should not change this value, even if you update Home Manager. If you do
  # want to update the value, then make sure to first check the Home Manager
  # release notes.
  home.stateVersion = "25.11"; # Please read the comment before changing.

  # The home.packages option allows you to install Nix packages into your
  # environment.
  home.packages = with pkgs; [
    # Ported from old config
    p7zip
    ripgrep-all
    git-ignore
    starship
    zoxide
    fd
    bat
    cifs-utils
    fastfetch
    eza

    # Agent Browser CLI
    (pkgs.writeShellScriptBin "agent-browser" "exec ${pkgs.nodejs}/bin/npx -y agent-browser \"$@\"")

    # CloakBrowser wrappers (Manager-backed)
    (let
      wrapper = name: ''
        MANAGER="http://chill-penguin:8080"
        # Get ID
        ID=$(${pkgs.curl}/bin/curl -s $MANAGER/api/profiles | ${pkgs.jq}/bin/jq -r ".[] | select(.name==\"${name}\") | .id")
        if [ -z "$ID" ] || [ "$ID" = "null" ]; then
          echo "Error: Profile ${name} not found"
          exit 1
        fi
        # Ensure launched
        STATUS=$(${pkgs.curl}/bin/curl -s $MANAGER/api/profiles/$ID/status | ${pkgs.jq}/bin/jq -r .status)
        if [ "$STATUS" != "running" ]; then
          echo "Launching profile ${name}..."
          ${pkgs.curl}/bin/curl -s -X POST $MANAGER/api/profiles/$ID/launch > /dev/null
          sleep 3
        fi
        # Connect
        exec ${pkgs.nodejs}/bin/npx -y agent-browser --connect "$MANAGER/api/profiles/$ID/cdp" "$@"
      '';
    in pkgs.symlinkJoin {
      name = "cloak-wrappers";
      paths = [
        (pkgs.writeShellScriptBin "cloak-vpn" (wrapper "VPN"))
        (pkgs.writeShellScriptBin "cloak-direct" (wrapper "Direct"))
      ];
    })

    # Playwright for AGENT MCP (Disabled on chill-penguin for initial cross-build)
  ] ++ lib.optional (!(osConfig.networking.hostName == "chill-penguin")) playwright-driver.browsers;

  # Home Manager is pretty good at managing dotfiles. The primary way to manage
  # plain files is through 'home.file'.
  home.file = {
    ".nix-profile" = {
      source = config.lib.file.mkOutOfStoreSymlink "/etc/profiles/per-user/${config.home.username}";
    };
    ".agents/AGENTS.md" = {
      source = ./config/AGENTS.md;
      force = true;
    };
    ".agents/workflow.md" = {
      source = ./config/workflow.md;
      force = true;
    };
    ".agents/skills/nix" = { source = ./config/skills/nix; force = true; };
    ".agents/skills/wsl2" = { source = ./config/skills/wsl2; force = true; };
    ".agents/skills/python" = { source = ./config/skills/python; force = true; };
    ".agents/skills/build123d" = { source = ./config/skills/build123d; force = true; };
    ".agents/skills/ssh" = { source = ./config/skills/ssh; force = true; };
    ".agents/skills/agent-browser" = { source = ./config/skills/agent-browser; force = true; };
  };

  # You can also manage environment variables through 'home.sessionVariables'.
  # If you don't want to manage your shell through Home Manager, then you
  # have to manually source 'hm-session-vars.sh' located at
  # either
  #
  #  ~/.nix-profile/etc/profile.d/hm-session-vars.sh
  #
  # or
  #
  #  /etc/profiles/per-user/nixos/etc/profile.d/hm-session-vars.sh
  #
  home.sessionVariables = {
    EDITOR = "nvim";
    PLAYWRIGHT_BROWSERS_PATH = "${pkgs.playwright-driver.browsers}";
    PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD = "1";
  };

  # Shell Configuration
  programs.bat.enable = true;
  programs.fd.enable = true;
  programs.ripgrep.enable = true;

  programs.eza = {
    enable = true;
    enableFishIntegration = true;
    icons = "auto";
  };

  programs.fish = {
    enable = true;
    shellAliases = {
      # Core Aliases
      cat = "bat --style plain --paging never";
      fd = "fd --follow";
      gi = "git-ignore";
      ll = "eza -lha --group-directories-first";
      ls = "eza --group-directories-first";
      rg = "rga";
      tree = "eza --group-directories-first --tree";
      reload = "clear; exec fish";
      vissh = "nvim ~/.ssh/config";
      j = "z";
      run = ",";
    };
    interactiveShellInit = lib.mkBefore ''
      # Set sponge plugin delay as universal variable if not already set
      if not set -q sponge_delay
        set -U sponge_delay 10
      end
    '';
    functions = {
      agent-root = {
        description = "Launch tmux with root access for agent";
        body = ''
          tmux new-session -s agent-root 'sudo -i'
        '';
      };
      cd = {
        description = "Change directory and auto-ls";
        body = ''
          builtin cd $argv
          if status is-interactive
            eza --group-directories-first --icons=auto
          end
        '';
      };
      fish_greeting = {
        description = "Ghostship Welcome Banner";
        body = ''
          if type -q fastfetch
            fastfetch --structure "Title:Separator:OS:Host:Kernel:Uptime:Packages:Shell:Terminal:CPU:GPU:Memory:Swap:Disk:LocalIp:Battery:Break:Colors"
          end
          set_color normal
        '';
      };
      rmssh = {
        description = "Cleanup SSH multiplexing sockets";
        body = ''
          set -l files $HOME/.ssh/+*
          if set -q files[1]
              rm $files
          end
          pkill -9 -f "$HOME/.ssh/+*" || true
        '';
      };
    };
    plugins = [
      # Plugins from old config
      { name = "autopair"; src = pkgs.fishPlugins.autopair.src; }
      { name = "sponge"; src = pkgs.fishPlugins.sponge.src; }
      { name = "puffer"; src = pkgs.fishPlugins.puffer.src; }
      { name = "colored-man-pages"; src = pkgs.fishPlugins.colored-man-pages.src; }
    ];
  };

  programs.starship = {
    enable = true;
    enableFishIntegration = true;
    settings = builtins.fromTOML (builtins.readFile ./config/starship.toml);
  };

  programs.zoxide = {
    enable = true;
    enableFishIntegration = true;
  };

  programs.nix-index.enable = true;

  programs.fzf = {
    enable = true;
    enableFishIntegration = true;
  };

  # Let Home Manager install and manage itself.
  programs.home-manager.enable = true;

  home.activation = {
    sshConfigD = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
      $DRY_RUN_CMD mkdir -p $VERBOSE_ARG $HOME/.ssh/conf.d
      $DRY_RUN_CMD chmod $VERBOSE_ARG 0700 $HOME/.ssh/conf.d
    '';
  };

  # SSH Client Configuration
  programs.ssh = {
    enable = true;
    enableDefaultConfig = false;
    includes = [ "conf.d/*" ];
    matchBlocks = {
      "*" = {
        user = "nixos";
        identityFile = "~/.ssh/id_ed25519";
        forwardAgent = true;
        compression = true;
        serverAliveInterval = 60;
        serverAliveCountMax = 30;
        addKeysToAgent = "yes";
        controlMaster = "auto";
        controlPath = "~/.ssh/+%h-%p-%r";
        controlPersist = "5m";
        hashKnownHosts = false;
        userKnownHostsFile = "~/.ssh/known_hosts";
        extraOptions = {
          "StrictHostKeyChecking" = "accept-new";
        };
      };
    };
  };

  # Git configuration
  programs.git = {
    enable = true;
    lfs.enable = (osConfig.networking.hostName != "chill-penguin");
    settings = {
      init.defaultBranch = "main";
    };
  };
}
