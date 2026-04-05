{
  pkgs,
  lib,
  inputs,
  ...
}:

let
  agentTooling = import ./agent-tooling.nix {
    inherit pkgs inputs;
  };
  homeDirectory = "/home/nixos";

  codex-notify = pkgs.writeShellScriptBin "codex-notify" ''
        set -euo pipefail

        ${pkgs.python3}/bin/python - "$1" <<'PY'
    import json
    import subprocess
    import sys

    notification = json.loads(sys.argv[1])
    if notification.get("type") != "agent-turn-complete":
        raise SystemExit(0)

    title = f"Codex: {notification.get('last-assistant-message', 'Turn Complete!')}"
    message = " ".join(notification.get("input-messages", []))
    subprocess.run(["notify-send", title, message, "-u", "critical"], check=False)
    PY
  '';

  skills = [
    { name = "nix"; }
    { name = "wsl2"; }
    { name = "python"; }
    { name = "ssh"; }
    { name = "skills-creator"; }
  ];

  skillConfig = map (skill: {
    path = "${homeDirectory}/.agents/skills/${skill.name}${skill.pathSuffix or ""}";
    enabled = true;
  }) skills;

  toTomlArray = values: "[ " + lib.concatStringsSep ", " (map (value: "\"${value}\"") values) + " ]";

  notifyConfig = ''
    notify = ["${codex-notify}/bin/codex-notify"]

    [tui]
    notifications = ["approval-requested"]
    notification_method = "auto"
  '';

  codexConfig = builtins.concatStringsSep "\n" [
    "check_for_update_on_startup = false"
    "project_doc_fallback_filenames = ${toTomlArray [ ".agents.md" ]}"
    "skills.config = ["
    (lib.concatStringsSep "\n" (
      map (entry: ''{ path = "${entry.path}", enabled = true },'') skillConfig
    ))
    "]"
    notifyConfig
  ];

  codex-cli = agentTooling.mkInstalledAgentWrapper {
    name = "codex";
    binaryName = "codex";
    extraEnvironment = ''
      export SSH_AUTH_SOCK="/run/user/1000/ssh-agent"
    '';
    preExecHook = ''
      codex_default_yolo=1
      codex_waiting_for_value=0
      for arg in "$@"; do
        if [ "$codex_waiting_for_value" -eq 1 ]; then
          codex_default_yolo=0
          codex_waiting_for_value=0
          continue
        fi

        case "$arg" in
          -a|--ask-for-approval|-s|--sandbox)
            codex_default_yolo=0
            codex_waiting_for_value=1
            ;;
          -a=*|--ask-for-approval=*|-s=*|--sandbox=*|--full-auto|--dangerously-bypass-approvals-and-sandbox)
            codex_default_yolo=0
            ;;
        esac
      done

      if [ "$codex_default_yolo" -eq 1 ]; then
        set -- --dangerously-bypass-approvals-and-sandbox "$@"
      fi
    '';
  };
in
{
  environment.etc."codex/config.toml".text = codexConfig;

  environment.systemPackages = [ codex-cli ];
}
