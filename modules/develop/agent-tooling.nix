{ pkgs, ... }:

let
  agent-browser = pkgs.writeShellScriptBin "agent-browser" ''
    exec ${pkgs.nodejs}/bin/npx -y agent-browser "$@"
  '';

  runtimeInputs = [
    pkgs.coreutils
    pkgs.git
    pkgs.nodejs
    pkgs.openssh
    pkgs.playwright-driver.browsers
    pkgs.uv
    agent-browser
  ];

  mcpServers = {
    "Multi-CLI" = {
      command = "npx";
      args = [ "-y" "@osanoai/multicli@latest" ];
      timeout = 600000;
    };
  };

  geminiExtensions = [
    {
      name = "conductor";
      repo = "https://github.com/gemini-cli-extensions/conductor";
    }
    {
      name = "gemini-cli-security";
      repo = "https://github.com/gemini-cli-extensions/security";
    }
    {
      name = "superpowers";
      repo = "https://github.com/obra/superpowers";
    }
  ];

  opencodePlugins = [
    {
      name = "superpowers";
      repo = "https://github.com/obra/superpowers.git";
    }
  ];

  superpowers = {
    name = "superpowers";
    repo = "https://github.com/obra/superpowers.git";
  };
in
{
  inherit runtimeInputs mcpServers geminiExtensions opencodePlugins superpowers;
  runtimeBinPath = pkgs.lib.makeBinPath runtimeInputs;
}
