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
  libsecretPath = lib.makeLibraryPath [ pkgs.libsecret ];

  gemini-cli = agentTooling.mkNpxAgentWrapper {
    name = "gemini";
    npmPackage = "@google/gemini-cli";
    extraEnvironment = ''
      export LD_LIBRARY_PATH="${libsecretPath}${
        if libsecretPath != "" then ":" else ""
      }''${LD_LIBRARY_PATH:-}"
    '';
    preLaunchHook = ''
      ensure_agent_browser_runtime() {
        if [ -d "$HOME/.agent-browser" ]; then
          return 0
        fi

        log_info "installing agent-browser runtime"

        if ! browser_output="$(${pkgs.nodejs}/bin/npx -y agent-browser install --with-deps 2>&1)"; then
          log_warn "agent-browser runtime install failed, continuing"
          if [ -n "$browser_output" ]; then
            printf '%s\n' "$browser_output" >&2
          fi
          return 0
        fi

        if [ -n "$browser_output" ]; then
          printf '%s\n' "$browser_output" >&2
        fi
      }

      refresh_extension() {
        name="$1"
        repo="$2"
        dir="$HOME/.gemini/extensions/$name"

        if [ -d "$dir" ] && [ ! -d "$dir/.git" ]; then
          return 0
        fi

        if [ -d "$dir/.git" ]; then
          log_info "refreshing $name"
          if ! extension_output="$(${pkgs.nodejs}/bin/npx -y @google/gemini-cli extensions update "$name" 2>&1)"; then
            log_warn "$name refresh failed, continuing"
            if [ -n "$extension_output" ]; then
              printf '%s\n' "$extension_output" >&2
            fi
            return 0
          fi
        else
          log_info "installing $name"
          if ! extension_output="$(${pkgs.nodejs}/bin/npx -y @google/gemini-cli extensions install "$repo" --auto-update --consent 2>&1)"; then
            log_warn "$name install failed, continuing"
            if [ -n "$extension_output" ]; then
              printf '%s\n' "$extension_output" >&2
            fi
            return 0
          fi
        fi

        if [ -n "$extension_output" ]; then
          printf '%s\n' "$extension_output" >&2
        fi
      }

      ensure_agent_browser_runtime
      ${lib.concatMapStrings (extension: ''
        refresh_extension "${extension.name}" "${extension.repo}"
      '') agentTooling.geminiExtensions}
    '';
  };
in
{
  environment.systemPackages = [
    gemini-cli
  ];
}
