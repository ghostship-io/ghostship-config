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
        ".agents/skills/caveman-compress"
        ".agents/skills/caveman-commit"
        ".agents/skills/caveman-help"
        ".agents/skills/caveman-review"
        ".agents/skills/compress"
        ".gemini/extensions/caveman"
      ];
      pathGlobs = [
        ".agents/skills/caveman-*"
      ];
      geminiExtensionKeys = [ "caveman" ];
      skillLockNames = [
        "caveman"
        "caveman-compress"
        "caveman-commit"
        "caveman-help"
        "caveman-review"
        "compress"
      ];
      codexHookCommands = [
        "echo 'CAVEMAN MODE ACTIVE. Rules: Drop articles/filler/pleasantries/hedging. Fragments OK. Short synonyms. Pattern: [thing] [action] [reason]. [next step]. Not: Sure! I would be happy to help you with that. Yes: Bug in auth middleware. Fix: Code/commits/security: write normal. User says stop caveman or normal mode to deactivate.'"
      ];
    }
    {
      name = "brainstorming";
      paths = [
        ".agents/skills/brainstorming"
      ];
      pathGlobs = [ ];
      geminiExtensionKeys = [ ];
      skillLockNames = [
        "brainstorming"
      ];
      codexHookCommands = [ ];
    }
    {
      name = "browser-use";
      paths = [
        ".config/browseruse"
      ];
      pathGlobs = [ ];
      geminiExtensionKeys = [ ];
      skillLockNames = [ ];
      codexHookCommands = [ ];
    }
    {
      name = "paseo";
      paths = [
        ".paseo"
        ".local/share/ghostship-agent-tools/npm/bin/paseo"
        ".local/share/ghostship-agent-tools/npm/lib/node_modules/@getpaseo"
        ".local/share/ghostship-agent-tools/npm/lib/node_modules/@getpaseo/cli"
      ];
      pathGlobs = [ ];
      geminiExtensionKeys = [ ];
      skillLockNames = [ ];
      codexHookCommands = [ ];
    }
    {
      name = "agent-deck";
      paths = [
        ".agent-deck"
        ".local/share/ghostship-agent-tools/npm/bin/agent-deck"
      ];
      pathGlobs = [ ];
      geminiExtensionKeys = [ ];
      skillLockNames = [ ];
      codexHookCommands = [ ];
    }
    {
      name = "opencode-server";
      paths = [
        ".config/systemd/user/opencode-server.service"
        ".config/systemd/user/default.target.wants/opencode-server.service"
      ];
      pathGlobs = [ ];
      geminiExtensionKeys = [ ];
      skillLockNames = [ ];
      codexHookCommands = [ ];
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
      pathGlobs = [ ];
      geminiExtensionKeys = [ ];
      skillLockNames = [ ];
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
      pathGlobs = [ ];
      geminiExtensionKeys = [ ];
      skillLockNames = [ ];
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
        ".agents/skills/github-pr-workflow"
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
    skill_lock_names = {
        name
        for entry in inventory
        for name in entry.get("skillLockNames", [])
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

    def clean_skill_lock() -> None:
        if not skill_lock_names:
            return

        path = home / ".agents/.skill-lock.json"
        if not path.is_file():
            return

        data = read_json(path, "global skill lock")
        if not isinstance(data, dict):
            return

        skills = data.get("skills")
        if not isinstance(skills, dict):
            return

        changed = False
        for name in skill_lock_names:
            if name in skills:
                del skills[name]
                changed = True

        if changed:
            write_json(path, data)

    clean_gemini_enablement()
    clean_codex_hooks()
    clean_skill_lock()
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

  renderGlobCleanup =
    entry:
    lib.concatMapStringsSep "\n" (
      pattern:
      let
        relativePattern = lib.escapeShellArg pattern;
      in
      ''
        cleanup_home_glob ${relativePattern}
      ''
    ) (entry.pathGlobs or [ ]);
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

    cleanup_home_glob() {
      relative_pattern="$1"

      case "$relative_pattern" in
        /*|..|../*|*/../*)
          printf 'warning: refusing retired artifact cleanup glob outside HOME: %s\n' "$relative_pattern" >&2
          return 0
          ;;
      esac

      relative_dir="$(${pkgs.coreutils}/bin/dirname "$relative_pattern")"
      relative_name="$(${pkgs.coreutils}/bin/basename "$relative_pattern")"

      if [ ! -d "$HOME/$relative_dir" ]; then
        return 0
      fi

      ${pkgs.findutils}/bin/find "$HOME/$relative_dir" \
        -maxdepth 1 -name "$relative_name" \
        -exec $DRY_RUN_CMD ${pkgs.coreutils}/bin/rm -rf -- {} +
    }

    ${lib.concatMapStringsSep "\n" (entry: ''
      ${renderPathCleanup entry}
      ${renderGlobCleanup entry}
    '') retiredArtifacts}

    $DRY_RUN_CMD ${pkgs.python3}/bin/python ${cleanupJsonState} ${cleanupInventory}
  '';
}
