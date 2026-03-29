{ pkgs, lib, ... }:

let
  agentTooling = import ./agent-tooling.nix { inherit pkgs; };

  opencode-superpowers-plugin = builtins.head agentTooling.opencodePlugins;

   opencode-config = builtins.toJSON {
     "$schema" = "https://opencode.ai/config.json";
     plugin = [
       "superpowers@git+https://github.com/obra/superpowers.git"
     ];
   };

  opencode-script = pkgs.writeShellScriptBin "opencode" ''
    set -euo pipefail

    check_plugin() {
      name="$1"
      repo="$2"
      dir="$HOME/.config/opencode/plugins/$name"
      remote_head="$(${pkgs.git}/bin/git ls-remote "$repo" HEAD | cut -f1)"
      local_head=""

      if [ -z "$remote_head" ]; then
        return 0
      fi

      if [ -d "$dir/.git" ]; then
        local_head="$(${pkgs.git}/bin/git -C "$dir" rev-parse HEAD 2>/dev/null || true)"
      fi

      if [ -z "$local_head" ]; then
        rm -rf "$dir"
      elif [ "$local_head" != "$remote_head" ]; then
        rm -rf "$dir"
      fi
    }

    check_plugin "${opencode-superpowers-plugin.name}" "${opencode-superpowers-plugin.repo}"
    exec ${pkgs.nodejs}/bin/npx -y opencode-ai "$@"
  '';

  opencode-cli = pkgs.symlinkJoin {
    name = "opencode";
    paths = [ opencode-script ];
    nativeBuildInputs = [ pkgs.makeWrapper ];
    postBuild = ''
      wrapProgram $out/bin/opencode \
        --prefix PATH : ${agentTooling.runtimeBinPath} \
        --set SSH_AUTH_SOCK "/run/user/1000/ssh-agent" \
        --set NODE_NO_WARNINGS 1
    '';
  };
in
{
  environment = {
    etc."opencode/opencode.json".text = opencode-config;
    systemPackages = [
      opencode-cli
    ];
  };
}
