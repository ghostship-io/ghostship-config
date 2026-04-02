{
  pkgs,
  lib ? pkgs.lib,
  ...
}:

let
  openspecPackage = "@fission-ai/openspec@latest";
  defaultOpenspecTools = "codex,gemini,opencode";
  defaultOpenspecProfile = "core";

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

  browserRuntimeLdLibraryPath = pkgs.lib.makeLibraryPath browserRuntimeLibs;

  baseRuntimeInputs = [
    pkgs.coreutils
    pkgs.git
    pkgs.gnugrep
    pkgs.nodejs
    pkgs.openssh
    pkgs.playwright-driver.browsers
    pkgs.uv
    pkgs.xdg-utils
  ];

  baseRuntimeBinPath = pkgs.lib.makeBinPath baseRuntimeInputs;

  agentBrowser = pkgs.writeShellScriptBin "agent-browser" ''
    set -euo pipefail

    PATH=${baseRuntimeBinPath}:$PATH
    export LD_LIBRARY_PATH="${browserRuntimeLdLibraryPath}${
      if browserRuntimeLdLibraryPath != "" then ":" else ""
    }''${LD_LIBRARY_PATH:-}"

    exec ${pkgs.nodejs}/bin/npx -y agent-browser "$@"
  '';

  openspecCli = pkgs.writeShellScriptBin "openspec" ''
    set -euo pipefail

    PATH=${baseRuntimeBinPath}:$PATH
    export NODE_NO_WARNINGS=1

    if [ "$#" -gt 0 ] && [ "$1" = "init" ]; then
      has_tools_arg=0
      has_profile_arg=0

      for arg in "$@"; do
        case "$arg" in
          --tools|--tools=*)
            has_tools_arg=1
            ;;
          --profile|--profile=*)
            has_profile_arg=1
            ;;
        esac

        if [ "$has_tools_arg" -eq 1 ] && [ "$has_profile_arg" -eq 1 ]; then
          break
        fi
      done

      if [ "$has_tools_arg" -eq 0 ] || [ "$has_profile_arg" -eq 0 ]; then
        init_args=("$1")

        if [ "$has_tools_arg" -eq 0 ]; then
          init_args+=(--tools ${defaultOpenspecTools})
        fi

        if [ "$has_profile_arg" -eq 0 ]; then
          init_args+=(--profile ${defaultOpenspecProfile})
        fi

        init_args+=("''${@:2}")

        exec ${pkgs.nodejs}/bin/npx -y ${openspecPackage} "''${init_args[@]}"
      fi
    fi

    exec ${pkgs.nodejs}/bin/npx -y ${openspecPackage} "$@"
  '';

  runtimeInputs = baseRuntimeInputs ++ [
    agentBrowser
    openspecCli
  ];

  runtimeBinPath = pkgs.lib.makeBinPath runtimeInputs;

  sharedPreflight = pkgs.writeText "agent-launcher-preflight.sh" ''
    log_info() {
      printf 'info: %s\n' "$1" >&2
    }

    log_warn() {
      printf 'warn: %s\n' "$1" >&2
    }

    find_openspec_root() {
      search_dir="$PWD"

      while [ "$search_dir" != "/" ]; do
        if [ -f "$search_dir/openspec/config.yaml" ]; then
          printf '%s\n' "$search_dir"
          return 0
        fi

        search_dir="$(dirname "$search_dir")"
      done

      return 1
    }

    refresh_global_skills() {
      if ! skills_json="$(${pkgs.nodejs}/bin/npx -y skills list -g --json 2>&1)"; then
        log_warn "global skills discovery failed, continuing"
        if [ -n "$skills_json" ]; then
          printf '%s\n' "$skills_json" >&2
        fi
        return 0
      fi

      if printf '%s\n' "$skills_json" | ${pkgs.gnugrep}/bin/grep -Eq '^[[:space:]]*\[[[:space:]]*\][[:space:]]*$'; then
        return 0
      fi

      log_info "refreshing global skills"

      if ! skills_output="$(${pkgs.nodejs}/bin/npx -y skills update -g 2>&1)"; then
        log_warn "global skills update failed, continuing"
        if [ -n "$skills_output" ]; then
          printf '%s\n' "$skills_output" >&2
        fi
        return 0
      fi

      if [ -n "$skills_output" ]; then
        printf '%s\n' "$skills_output" >&2
      fi
    }

    refresh_openspec_if_present() {
      if ! openspec_root="$(find_openspec_root)"; then
        return 0
      fi

      log_info "refreshing openspec instructions"

      if ! openspec_output="$(
        cd "$openspec_root" &&
        ${pkgs.nodejs}/bin/npx -y ${openspecPackage} update . 2>&1
      )"; then
        log_warn "openspec refresh failed, continuing"
        if [ -n "$openspec_output" ]; then
          printf '%s\n' "$openspec_output" >&2
        fi
        return 0
      fi

      if [ -n "$openspec_output" ]; then
        printf '%s\n' "$openspec_output" >&2
      fi
    }
  '';

  mkNpxAgentWrapper =
    {
      name,
      npmPackage,
      extraEnvironment ? "",
      preLaunchHook ? "",
    }:
    pkgs.writeShellScriptBin name ''
      set -euo pipefail

      PATH=${runtimeBinPath}:$PATH
      export NODE_NO_WARNINGS=1
      ${extraEnvironment}

      . ${sharedPreflight}

      refresh_global_skills
      refresh_openspec_if_present

      ${preLaunchHook}

      exec ${pkgs.nodejs}/bin/npx -y ${npmPackage} "$@"
    '';

  geminiExtensions = [
    {
      name = "gemini-cli-security";
      repo = "https://github.com/gemini-cli-extensions/security";
    }
  ];
in
{
  inherit
    agentBrowser
    browserRuntimeLdLibraryPath
    mkNpxAgentWrapper
    openspecCli
    ;
  inherit runtimeInputs geminiExtensions;
  inherit runtimeBinPath;
}
