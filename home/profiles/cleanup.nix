{ lib, pkgs, ... }:

let
  retiredArtifacts = [
    {
      name = "superpowers";
      paths = [
        ".agents/skills/superpowers"
        ".config/opencode/plugins/superpowers"
        ".gemini/extensions/superpowers"
      ];
      geminiExtensionKeys = [ "superpowers" ];
      codexHookCommands = [ ];
    }
    {
      name = "managed-caveman";
      paths = [
        ".agents/skills/caveman"
        ".gemini/extensions/caveman"
      ];
      geminiExtensionKeys = [ "caveman" ];
      codexHookCommands = [
        "echo 'CAVEMAN MODE ACTIVE. Rules: Drop articles/filler/pleasantries/hedging. Fragments OK. Short synonyms. Pattern: [thing] [action] [reason]. [next step]. Not: Sure! I would be happy to help you with that. Yes: Bug in auth middleware. Fix: Code/commits/security: write normal. User says stop caveman or normal mode to deactivate.'"
      ];
    }
    {
      name = "workmux";
      paths = [
        ".cache/workmux"
        ".config/workmux"
        ".local/state/workmux"
        ".config/opencode/plugin/workmux-status.ts"
        ".config/opencode/skills/workmux"
      ];
      geminiExtensionKeys = [ ];
      codexHookCommands = [
        "workmux set-window-status working"
        "workmux set-window-status done"
      ];
    }
    {
      name = "renamed-worktree-workflow-skills";
      paths = [
        ".agents/skills/merge-worktree"
        ".agents/skills/local-worktree-workflow"
        ".agents/skills/merge-worktree-main"
      ];
      geminiExtensionKeys = [ ];
      codexHookCommands = [ ];
    }
    {
      name = "deprecated-shared-skills";
      paths = [
        ".agents/skills/codex-queue"
        ".agents/skills/nix"
        ".agents/skills/python"
        ".agents/skills/skill-creator"
        ".agents/skills/ssh"
        ".agents/skills/wsl2"
        ".codex/skills/.system/skill-creator"
      ];
      geminiExtensionKeys = [ ];
      codexHookCommands = [ ];
    }
  ];

  cleanupInventory = pkgs.writeText "ghostship-retired-artifacts.json" (
    builtins.toJSON retiredArtifacts
  );

  cleanupJsonState = pkgs.writeText "ghostship-clean-retired-json-state.py" ''
    import json
    import os
    import sys
    from pathlib import Path

    home = Path(os.environ["HOME"]).resolve()
    inventory = json.loads(Path(sys.argv[1]).read_text())

    gemini_keys = {
        key
        for entry in inventory
        for key in entry.get("geminiExtensionKeys", [])
    }
    codex_commands = {
        command
        for entry in inventory
        for command in entry.get("codexHookCommands", [])
    }

    def read_json(path: Path, label: str):
        try:
            return json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            print(f"warning: unable to clean retired {label} in {path}: {exc}", file=sys.stderr)
            return None

    def write_json(path: Path, data) -> None:
        path.write_text(json.dumps(data, indent=2) + "\n")

    def clean_gemini_enablement() -> None:
        if not gemini_keys:
            return

        path = home / ".gemini/extensions/extension-enablement.json"
        if not path.is_file():
            return

        data = read_json(path, "Gemini extension enablement")
        if not isinstance(data, dict):
            return

        changed = False
        for key in gemini_keys:
            if key in data:
                del data[key]
                changed = True

        if changed:
            write_json(path, data)

    def clean_codex_hooks() -> None:
        if not codex_commands:
            return

        path = home / ".codex/hooks.json"
        if not path.is_file():
            return

        data = read_json(path, "Codex hooks")
        if not isinstance(data, dict):
            return

        hooks = data.get("hooks")
        if not isinstance(hooks, dict):
            return

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
                        and hook.get("command") in codex_commands
                    ):
                        changed = True
                        continue
                    filtered_hooks.append(hook)

                updated_group = dict(group)
                updated_group["hooks"] = filtered_hooks
                cleaned_groups.append(updated_group)

            hooks[event_name] = cleaned_groups

        if changed:
            write_json(path, data)

    clean_gemini_enablement()
    clean_codex_hooks()
  '';

  renderPathCleanup =
    entry:
    lib.concatMapStringsSep "\n" (
      path:
      let
        relativePath = lib.escapeShellArg path;
      in
      ''
        cleanup_home_path ${relativePath}
      ''
    ) entry.paths;
in
{
  home.activation.ghostshipRetiredArtifactCleanup = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    cleanup_home_path() {
      relative_path="$1"

      case "$relative_path" in
        /*|..|../*|*/../*)
          printf 'warning: refusing retired artifact cleanup path outside HOME: %s\n' "$relative_path" >&2
          return 0
          ;;
      esac

      $DRY_RUN_CMD ${pkgs.coreutils}/bin/rm -rf -- "$HOME/$relative_path"
    }

    ${lib.concatMapStringsSep "\n" renderPathCleanup retiredArtifacts}

    $DRY_RUN_CMD ${pkgs.python3}/bin/python ${cleanupJsonState} ${cleanupInventory}
  '';
}
