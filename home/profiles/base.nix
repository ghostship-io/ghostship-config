{
  config,
  lib,
  pkgs,
  ...
}:

{
  home.username = lib.mkDefault "nixos";
  home.homeDirectory = lib.mkDefault "/home/${config.home.username}";

  home.file = {
    ".nix-profile" = {
      source = config.lib.file.mkOutOfStoreSymlink "/etc/profiles/per-user/${config.home.username}";
    };
  };

  home.sessionVariables = {
    EDITOR = "nvim";
  };

  programs.home-manager.enable = true;

  programs.git = {
    enable = true;
    settings = {
      core.sshCommand = "ssh -i ~/.ssh/id_ed25519_dev -o IdentitiesOnly=yes";
      init.defaultBranch = "main";
    };
  };

  programs.ssh = {
    enable = true;
    enableDefaultConfig = false;
    includes = [ "conf.d/*" ];
    settings = {
      "*" = {
        User = "nixos";
        IdentityFile = "~/.ssh/id_ed25519";
        ForwardAgent = true;
        Compression = true;
        ServerAliveInterval = 60;
        ServerAliveCountMax = 30;
        AddKeysToAgent = "yes";
        ControlMaster = "auto";
        ControlPath = "~/.ssh/+%h-%p-%r";
        ControlPersist = "5m";
        HashKnownHosts = false;
        UserKnownHostsFile = "~/.ssh/known_hosts";
        StrictHostKeyChecking = "accept-new";
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
