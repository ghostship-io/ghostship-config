{ pkgs, lib, inputs, ... }:

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
    { name = "build123d"; }
    { name = "ssh"; }
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
    ''check_for_update_on_startup = true''
    ''project_doc_fallback_filenames = ${toTomlArray [ ".agents.md" ]}''
    ''skills.config = [''
    (lib.concatStringsSep "\n" (map (entry: ''  { path = "${entry.path}", enabled = true },'') skillConfig))
    '']''
    notifyConfig
  ];

  codex-script = pkgs.writeShellScriptBin "codex" ''
    set -euo pipefail

    PATH=${agentTooling.runtimeBinPath}:$PATH
    export SSH_AUTH_SOCK="/run/user/1000/ssh-agent"
    export NODE_NO_WARNINGS=1

    exec ${pkgs.nodejs}/bin/npx -y @openai/codex "$@"
  '';

  codex-cli = pkgs.symlinkJoin {
    name = "codex";
    paths = [ codex-script ];
    nativeBuildInputs = [ pkgs.makeWrapper ];
    postBuild = ''
      wrapProgram $out/bin/codex \
        --prefix PATH : ${agentTooling.runtimeBinPath} \
        --set NODE_NO_WARNINGS 1
    '';
  };
in
{
  environment.etc."codex/config.toml".text = codexConfig;

  environment.systemPackages = [ codex-cli ];
}
