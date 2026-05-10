{
  config,
  lib,
  pkgs,
  inputs,
  ...
}:

let
  sshAgentSock = "/run/user/1000/ssh-agent";
  agentTooling = import ../../modules/develop/agent-tooling.nix {
    inherit pkgs inputs;
  };
  agentDeckCli = agentTooling.mkInstalledAgentWrapper {
    name = "agent-deck";
    binaryName = "agent-deck";
  };
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

  home.activation.removeManagedCavemanState = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
        $DRY_RUN_CMD ${pkgs.coreutils}/bin/rm -rf \
          "$HOME/.agents/skills/caveman" \
          "$HOME/.gemini/extensions/caveman"

        enablement_file="$HOME/.gemini/extensions/extension-enablement.json"
        if test -f "$enablement_file"; then
          tmp_file="$(${pkgs.coreutils}/bin/mktemp)"
          ${pkgs.jq}/bin/jq 'del(.caveman)' "$enablement_file" > "$tmp_file"
          $DRY_RUN_CMD ${pkgs.coreutils}/bin/mv "$tmp_file" "$enablement_file"
        fi

        codex_hooks_file="$HOME/.codex/hooks.json"
        if test -f "$codex_hooks_file"; then
          $DRY_RUN_CMD ${pkgs.python3}/bin/python - "$codex_hooks_file" <<'PY'
    import json
    import sys
    from pathlib import Path

    path = Path(sys.argv[1])
    stale_commands = {
        "echo 'CAVEMAN MODE ACTIVE. Rules: Drop articles/filler/pleasantries/hedging. Fragments OK. Short synonyms. Pattern: [thing] [action] [reason]. [next step]. Not: Sure! I would be happy to help you with that. Yes: Bug in auth middleware. Fix: Code/commits/security: write normal. User says stop caveman or normal mode to deactivate.'"
    }

    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"warning: unable to clean managed Caveman state in {path}: {exc}", file=sys.stderr)
        raise SystemExit(0)

    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        raise SystemExit(0)

    changed = False
    for event_name, event_groups in list(hooks.items()):
        if not isinstance(event_groups, list):
            continue

        cleaned_groups = []
        for group in event_groups:
            if not isinstance(group, dict):
                cleaned_groups.append(group)
                continue

            nested_hooks = group.get("hooks")
            if not isinstance(nested_hooks, list):
                cleaned_groups.append(group)
                continue

            filtered_hooks = []
            for hook in nested_hooks:
                if (
                    isinstance(hook, dict)
                    and hook.get("type") == "command"
                    and hook.get("command") in stale_commands
                ):
                    changed = True
                    continue
                filtered_hooks.append(hook)

            updated_group = dict(group)
            updated_group["hooks"] = filtered_hooks
            cleaned_groups.append(updated_group)

        hooks[event_name] = cleaned_groups

    if changed:
        path.write_text(json.dumps(data, indent=2) + "\n")
    PY
        fi
  '';

  home.activation.removeWorkmuxArtifacts = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
        $DRY_RUN_CMD ${pkgs.coreutils}/bin/rm -rf \
          "$HOME/.cache/workmux" \
          "$HOME/.config/workmux" \
          "$HOME/.local/state/workmux" \
          "$HOME/.config/opencode/plugin/workmux-status.ts" \
          "$HOME/.config/opencode/skills/workmux"

        codex_hooks_file="$HOME/.codex/hooks.json"
        if test -f "$codex_hooks_file"; then
          $DRY_RUN_CMD ${pkgs.python3}/bin/python - "$codex_hooks_file" <<'PY'
    import json
    import sys
    from pathlib import Path

    path = Path(sys.argv[1])
    stale_commands = {
        "workmux set-window-status working",
        "workmux set-window-status done",
    }

    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"warning: unable to clean stale Codex workmux hooks in {path}: {exc}", file=sys.stderr)
        raise SystemExit(0)

    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        raise SystemExit(0)

    changed = False
    for event_name, event_groups in list(hooks.items()):
        if not isinstance(event_groups, list):
            continue

        cleaned_groups = []
        for group in event_groups:
            if not isinstance(group, dict):
                cleaned_groups.append(group)
                continue

            nested_hooks = group.get("hooks")
            if not isinstance(nested_hooks, list):
                cleaned_groups.append(group)
                continue

            filtered_hooks = []
            for hook in nested_hooks:
                if (
                    isinstance(hook, dict)
                    and hook.get("type") == "command"
                    and hook.get("command") in stale_commands
                ):
                    changed = True
                    continue
                filtered_hooks.append(hook)

            updated_group = dict(group)
            updated_group["hooks"] = filtered_hooks
            cleaned_groups.append(updated_group)

        hooks[event_name] = cleaned_groups

    if changed:
        path.write_text(json.dumps(data, indent=2) + "\n")
    PY
        fi
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
    ".agents/skills/codex-queue" = {
      source = ../config/skills/codex-queue;
      force = true;
    };
    ".agents/skills/github-pr-workflow" = {
      source = ../config/skills/github-pr-workflow;
      force = true;
    };
    ".agents/skills/skill-creator" = {
      source = ../config/skills/skill-creator;
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
  };

  home.packages = with pkgs; [
    p7zip
    ripgrep-all
    git-ignore
    gh
    agentDeckCli
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
