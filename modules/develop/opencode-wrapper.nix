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
          "z-ai/glm-4.5-air:free" = { };
        };
      };
    };
  };

  opencode-cli = agentTooling.mkNpxAgentWrapper {
    name = "opencode";
    npmPackage = "opencode-ai";
    extraEnvironment = ''
      export SSH_AUTH_SOCK="/run/user/1000/ssh-agent"
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
