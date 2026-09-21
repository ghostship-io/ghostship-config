{
  config,
  lib,
  osConfig,
  pkgs,
  inputs,
  ...
}:

let
  sshAgentSock = "/run/user/1000/ssh-agent";
  # A T3 worker host gets the same workflows from the shared ghostship-agent
  # catalog, which owns ~/.agents/skills. Keep the repo-local copies on ordinary
  # develop hosts so the two owners never race for the same skill path.
  t3worker = osConfig.ghostship.t3Worker.enable or false;
  repoSkillLink = name: {
    ".agents/skills/${name}" = {
      source = ../config/skills/${name};
      force = true;
    };
  };
in
{
  imports = [
    ./cleanup.nix
    ../../modules/develop/opencode.nix
    ../../modules/develop/codex.nix
  ];

  home.sessionVariables = {
    SSH_AUTH_SOCK = sshAgentSock;
  };

  home.file = lib.mkMerge [
    (lib.mkIf (!t3worker) (lib.mkMerge (map repoSkillLink [
      "ghostship-audit-worktree"
      "ghostship-merge-worktree"
      "ghostship-pull-worktree"
      "grill-me"
    ])))
    {
      ".ssh/id_ed25519_dev.pub" = {
        text = ''
          ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIMeeTWD0303kIaPcdYjWUGmGYh65TO9wd0kzayjaELhJ owner@dev
        '';
        force = true;
      };
      ".gemini/GEMINI.md" = {
        source = ../config/AGENTS.md;
        force = true;
      };
      ".config/opencode/AGENTS.md" = {
        source = ../config/AGENTS.md;
        force = true;
      };
      ".local/bin/xdg-open" = {
        text = ''
          #!/bin/sh
          exit 0
        '';
        executable = true;
        force = true;
      };
      ".local/bin/xdg-debug" = {
        text = ''
          #!/bin/sh
          exit 0
        '';
        executable = true;
        force = true;
      };
    }
  ];

  home.packages = with pkgs; [
    p7zip
    ripgrep-all
    git-ignore
    gh
    starship
    zoxide
    fd
    bat
    fastfetch
    eza
    playwright-driver.browsers
  ];

  programs.bat.enable = true;
  programs.fd.enable = true;
  programs.ripgrep.enable = true;

  services.ssh-agent.enable = true;

  systemd.user.services.ssh-agent.Service = {
    ExecStart = lib.mkForce "${pkgs.openssh}/bin/ssh-agent -D -a ${sshAgentSock} -t 12h";
    ExecStartPre = "-${pkgs.coreutils}/bin/rm -f ${sshAgentSock}";
  };

  programs.eza = {
    enable = true;
    enableFishIntegration = true;
    icons = "auto";
  };

  programs.fzf = {
    enable = true;
    enableFishIntegration = true;
  };

  programs.starship = {
    enable = true;
    enableFishIntegration = true;
    settings = builtins.fromTOML (builtins.readFile ../config/starship.toml);
  };

  programs.zoxide = {
    enable = true;
    enableFishIntegration = true;
  };

  programs.git.lfs.enable = true;

  programs.fish = {
    enable = true;
    shellAliases = {
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
    shellInit = lib.mkBefore ''
      if test "$CODEX_INTERNAL_ORIGINATOR_OVERRIDE" = "Codex Desktop"
        set -gx CODEX_HOME "$HOME/.codex-desktop"
        set -gx CODEX_SQLITE_HOME "$HOME/.codex-desktop/sqlite"
      end
    '';
    interactiveShellInit = lib.mkBefore ''
      if not set -q sponge_delay
        set -U sponge_delay 10
      end
    '';
    functions = {
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
      {
        name = "autopair";
        src = pkgs.fishPlugins.autopair.src;
      }
      {
        name = "puffer";
        src = pkgs.fishPlugins.puffer.src;
      }
      {
        name = "colored-man-pages";
        src = pkgs.fishPlugins.colored-man-pages.src;
      }
    ];
  };

}
