{ pkgs, inputs, ... }:

let
  agentTooling = import ./agent-tooling.nix {
    inherit pkgs inputs;
  };

  opencode-config = builtins.toJSON {
    "$schema" = "https://opencode.ai/config.json";
    provider = {
      openrouter = {
        models = {
          "minimax/minimax-m2.5:free" = { };
          "nvidia/nemotron-3-super-120b-a12b:free" = { };
          "arcee-ai/trinity-large-preview:free" = { };
          "nvidia/nemotron-3-nano-30b-a3b:free" = { };
          "qwen/qwen3-coder:free" = { };
          "qwen/qwen3-next-80b-a3b-instruct:free" = { };
          "openai/gpt-oss-120b:free" = { };
        };
      };
    };
  };

  opencode-script = pkgs.writeShellScriptBin "opencode" ''
    set -euo pipefail
    PATH=${agentTooling.runtimeBinPath}:$PATH
    export SSH_AUTH_SOCK="/run/user/1000/ssh-agent"
    export NODE_NO_WARNINGS=1

    exec ${pkgs.nodejs}/bin/npx -y opencode-ai "$@"
  '';
in
{
  home.file.".config/opencode/opencode.json" = {
    text = opencode-config;
    force = true;
  };

  home.packages = [
    opencode-script
  ];
}
