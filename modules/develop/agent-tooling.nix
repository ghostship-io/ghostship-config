{ pkgs, ... }:

let
  browserRuntimeLibs = [
    pkgs."alsa-lib"
    pkgs."at-spi2-atk"
    pkgs.atk
    pkgs.cairo
    pkgs.cups
    pkgs.dbus
    pkgs.expat
    pkgs.glib
    pkgs.gtk3
    pkgs.libgbm
    pkgs.libdrm
    pkgs.libxkbcommon
    pkgs.nspr
    pkgs.nss
    pkgs.pango
    pkgs.libx11
    pkgs.libxcomposite
    pkgs.libxdamage
    pkgs.libxext
    pkgs.libxfixes
    pkgs.libxrandr
    pkgs.libxcb
  ];

  browserRuntimeLdLibraryPath =
    pkgs.lib.makeLibraryPath browserRuntimeLibs;

  agentBrowser = pkgs.writeShellScriptBin "agent-browser" ''
    set -euo pipefail

    export LD_LIBRARY_PATH="${browserRuntimeLdLibraryPath}${if browserRuntimeLdLibraryPath != "" then ":" else ""}''${LD_LIBRARY_PATH:-}"

    exec ${pkgs.nodejs}/bin/npx -y agent-browser "$@"
  '';

  runtimeInputs = [
    pkgs.coreutils
    pkgs.git
    pkgs.nodejs
    pkgs.openssh
    pkgs.playwright-driver.browsers
    pkgs.xdg-utils
    pkgs.uv
    agentBrowser
  ];

  geminiExtensions = [
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
  inherit agentBrowser browserRuntimeLdLibraryPath;
  inherit runtimeInputs geminiExtensions opencodePlugins superpowers;
  runtimeBinPath = pkgs.lib.makeBinPath runtimeInputs;
}
