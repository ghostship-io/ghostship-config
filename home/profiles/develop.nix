{ lib, pkgs, ... }:

let
  sshAgentSock = "/run/user/1000/ssh-agent";
in
{
  imports = [
    ../../modules/develop/opencode.nix
    ../../modules/develop/codex.nix
  ];

  home.sessionVariables = {
    SSH_AUTH_SOCK = sshAgentSock;
  };

  home.activation.removeLegacySuperpowers = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    $DRY_RUN_CMD ${pkgs.coreutils}/bin/rm -rf \
      "$HOME/.agents/skills/superpowers" \
      "$HOME/.config/opencode/plugins/superpowers" \
      "$HOME/.gemini/extensions/superpowers"

    enablement_file="$HOME/.gemini/extensions/extension-enablement.json"
    if test -f "$enablement_file"; then
      tmp_file="$(${pkgs.coreutils}/bin/mktemp)"
      ${pkgs.jq}/bin/jq 'del(.superpowers)' "$enablement_file" > "$tmp_file"
      $DRY_RUN_CMD ${pkgs.coreutils}/bin/mv "$tmp_file" "$enablement_file"
    fi
  '';

  home.activation.overrideCodexSkillCreator = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    codex_system_skills_dir="$HOME/.codex/skills/.system"
    codex_skill_creator_path="$codex_system_skills_dir/skill-creator"
    shared_skill_creator_path="$HOME/.agents/skills/skill-creator"

    $DRY_RUN_CMD ${pkgs.coreutils}/bin/mkdir -p "$codex_system_skills_dir"
    $DRY_RUN_CMD ${pkgs.coreutils}/bin/rm -rf "$codex_skill_creator_path"
    $DRY_RUN_CMD ${pkgs.coreutils}/bin/ln -sfn "$shared_skill_creator_path" "$codex_skill_creator_path"
  '';

  home.activation.removeWorkmuxArtifacts = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    $DRY_RUN_CMD ${pkgs.coreutils}/bin/rm -rf       "$HOME/.cache/workmux"       "$HOME/.config/workmux"       "$HOME/.local/state/workmux"       "$HOME/.config/opencode/plugin/workmux-status.ts"       "$HOME/.config/opencode/skills/workmux"
  '';



  home.file = {
    ".agents/skills/nix" = {
      source = ../config/skills/nix;
      force = true;
    };
    ".agents/skills/wsl2" = {
      source = ../config/skills/wsl2;
      force = true;
    };
    ".agents/skills/python" = {
      source = ../config/skills/python;
      force = true;
    };
    ".agents/skills/ssh" = {
      source = ../config/skills/ssh;
      force = true;
    };
    ".agents/skills/skill-creator" = {
      source = ../config/skills/skill-creator;
      force = true;
    };
  };

  home.packages = with pkgs; [
    p7zip
    ripgrep-all
    git-ignore
    gh
    agent-deck
    starship
    zoxide
    fd
    bat
    cifs-utils
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
        name = "sponge";
        src = pkgs.fishPlugins.sponge.src;
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
