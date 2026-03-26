{ pkgs, lib, ... }:

let
  agentTooling = import ./agent-tooling.nix { inherit pkgs; };
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
    { name = "superpowers"; pathSuffix = "/skills"; }
  ];

  skillConfig = map (skill: {
    path = "${homeDirectory}/.agents/skills/${skill.name}${skill.pathSuffix or ""}";
    enabled = true;
  }) skills;

  toTomlArray = values: "[ " + lib.concatStringsSep ", " (map (value: "\"${value}\"") values) + " ]";

  tomlTableName = name:
    if builtins.match "^[A-Za-z0-9_]+$" name != null then name else ''"${name}"'';

  mcpConfig = lib.concatStringsSep "\n" (lib.mapAttrsToList (name: server: ''
    [mcp_servers.${tomlTableName name}]
    command = "${server.command}"
    args = ${toTomlArray server.args}${lib.optionalString (server ? timeout) "\n    tool_timeout_sec = ${toString (builtins.div server.timeout 1000)}"}
  '') agentTooling.mcpServers);

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
    mcpConfig
  ];

  codex-script = pkgs.writeShellScriptBin "codex" ''
    set -euo pipefail

    sync_checkout() {
      name="$1"
      repo="$2"
      dir="$3"
      remote_head="$(${pkgs.git}/bin/git ls-remote "$repo" HEAD | cut -f1)"
      local_head=""

      if [ -z "$remote_head" ]; then
        return 0
      fi

      if [ -d "$dir/.git" ]; then
        local_head="$(${pkgs.git}/bin/git -C "$dir" rev-parse HEAD 2>/dev/null || true)"
      fi

      if [ -z "$local_head" ] || [ "$local_head" != "$remote_head" ]; then
        rm -rf "$dir"
        mkdir -p "$(dirname "$dir")"
        ${pkgs.git}/bin/git clone --depth 1 "$repo" "$dir" >/dev/null 2>&1 || true
      fi
    }

    sync_checkout "${agentTooling.superpowers.name}" "${agentTooling.superpowers.repo}" "$HOME/.agents/skills/${agentTooling.superpowers.name}"

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
