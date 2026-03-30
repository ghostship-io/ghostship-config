{ config, lib, pkgs, ... }:

{
  home.username = lib.mkDefault "nixos";
  home.homeDirectory = lib.mkDefault "/home/${config.home.username}";

  home.file = {
    ".nix-profile" = {
      source = config.lib.file.mkOutOfStoreSymlink "/etc/profiles/per-user/${config.home.username}";
    };
    ".agents/AGENTS.md" = {
      source = ../config/AGENTS.md;
      force = true;
    };
    ".agents/workflow.md" = {
      source = ../config/workflow.md;
      force = true;
    };
  };

  home.sessionVariables = {
    EDITOR = "nvim";
  };

  programs.home-manager.enable = true;

  programs.git = {
    enable = true;
    settings = {
      init.defaultBranch = "main";
    };
  };

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

  home.activation = {
    sshConfigD = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
      $DRY_RUN_CMD mkdir -p $VERBOSE_ARG $HOME/.ssh/conf.d
      $DRY_RUN_CMD chmod $VERBOSE_ARG 0700 $HOME/.ssh/conf.d
    '';
  };
}
