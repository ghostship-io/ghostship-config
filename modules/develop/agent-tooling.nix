{
  pkgs,
  lib ? pkgs.lib,
  ...
}:

let
  paseoPackage = "@getpaseo/cli";
  userHome = "/home/nixos";
  agentToolsRoot = "${userHome}/.local/share/ghostship-agent-tools";
  agentNpmPrefix = "${agentToolsRoot}/npm";
  agentBinDir = "${agentNpmPrefix}/bin";
  opencodeUserConfigPath = "${userHome}/.config/opencode/opencode.json";

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

  browserRuntimeLdLibraryPath = lib.makeLibraryPath browserRuntimeLibs;

  baseRuntimeInputs = [
    pkgs.bash
    pkgs.coreutils
    pkgs.curl
    pkgs.gawk
    pkgs.gcc
    pkgs.git
    pkgs.go
    pkgs.gnutar
    pkgs.gnugrep
    pkgs.gzip
    pkgs.jq
    pkgs.nodejs
    pkgs.openssh
    pkgs.playwright-driver.browsers
    pkgs.uv
    pkgs.xdg-utils
  ];

  baseRuntimeBinPath = lib.makeBinPath baseRuntimeInputs;

  agentBrowser = pkgs.writeShellScriptBin "agent-browser" ''
    set -euo pipefail

    PATH=${baseRuntimeBinPath}:$PATH
    export AGENT_BROWSER_ENGINE="''${AGENT_BROWSER_ENGINE:-chrome}"
    export LD_LIBRARY_PATH="${browserRuntimeLdLibraryPath}${
      if browserRuntimeLdLibraryPath != "" then ":" else ""
    }''${LD_LIBRARY_PATH:-}"

    exec ${pkgs.nodejs}/bin/npx -y agent-browser "$@"
  '';

  runtimeInputs = baseRuntimeInputs ++ [
    agentBrowser
  ];

  runtimeBinPath = lib.makeBinPath runtimeInputs;

  geminiExtensions = [
    {
      name = "gemini-cli-security";
      repo = "https://github.com/gemini-cli-extensions/security";
    }
  ];

  managedGlobalSkills = [
    {
      name = "brainstorming";
      source = "obra/superpowers/brainstorming";
    }
  ];

  agentMaintenance = pkgs.writeShellScriptBin "ghostship-agent-maintenance" ''
    set -euo pipefail

    PATH=${runtimeBinPath}:$PATH
    export NODE_NO_WARNINGS=1
    export HOME=${userHome}
    export XDG_CONFIG_HOME="''${XDG_CONFIG_HOME:-$HOME/.config}"
    export XDG_STATE_HOME="''${XDG_STATE_HOME:-$HOME/.local/state}"
    export NPM_CONFIG_PREFIX="${agentNpmPrefix}"
    export npm_config_prefix="$NPM_CONFIG_PREFIX"
    export PATH="${agentBinDir}:$PATH"

    log_info() {
      printf 'info: %s\n' "$1" >&2
    }

    log_warn() {
      printf 'warn: %s\n' "$1" >&2
    }

    install_agent_cli() {
      package="$1"
      label="$2"

      log_info "installing or upgrading $label"

      if ! install_output="$(${pkgs.nodejs}/bin/npm install -g --no-fund --no-audit "$package@latest" 2>&1)"; then
        log_warn "$label install failed, continuing"
        if [ -n "$install_output" ]; then
          printf '%s\n' "$install_output" >&2
        fi
        return 0
      fi

      if [ -n "$install_output" ]; then
        printf '%s\n' "$install_output" >&2
      fi
    }

    remove_stale_openspec_cli() {
      log_info "removing stale openspec CLI"
      rm -f "${agentBinDir}/openspec"
      rm -rf "${agentNpmPrefix}/lib/node_modules/@fission-ai/openspec"
      rmdir "${agentNpmPrefix}/lib/node_modules/@fission-ai" 2>/dev/null || true
    }

    install_agent_deck_latest() {
      detect_agent_deck_os() {
        case "$(${pkgs.coreutils}/bin/uname -s)" in
          Linux) printf 'linux\n' ;;
          Darwin) printf 'darwin\n' ;;
          *)
            log_warn "unsupported OS for agent-deck auto-install"
            return 1
            ;;
        esac
      }

      detect_agent_deck_arch() {
        case "$(${pkgs.coreutils}/bin/uname -m)" in
          x86_64|amd64) printf 'amd64\n' ;;
          arm64|aarch64) printf 'arm64\n' ;;
          *)
            log_warn "unsupported architecture for agent-deck auto-install"
            return 1
            ;;
        esac
      }

      os="$(detect_agent_deck_os)" || return 0
      arch="$(detect_agent_deck_arch)" || return 0

      release_meta="$(mktemp)"
      source_dir="$(mktemp -d)"
      trap 'rm -f "$release_meta"; rm -rf "$source_dir"' RETURN

      if ! ${pkgs.curl}/bin/curl -fsSL "https://api.github.com/repos/asheshgoplani/agent-deck/releases/latest" > "$release_meta"; then
        log_warn "agent-deck release metadata fetch failed, continuing"
        return 0
      fi

      version="$(${pkgs.jq}/bin/jq -r '.tag_name // empty' "$release_meta")"
      if [ -z "$version" ] || [ "$version" = "null" ]; then
        log_warn "agent-deck release metadata missing tag name, continuing"
        return 0
      fi

      desired_version="''${version#v}"
      current_version=""
      if [ -x "${agentBinDir}/agent-deck" ]; then
        current_version="$(${agentBinDir}/agent-deck --version 2>/dev/null | ${pkgs.gnugrep}/bin/grep -Eo 'v?[0-9]+\.[0-9]+\.[0-9]+' | tail -n1 | sed 's/^v//')"
      fi

      if [ -n "$current_version" ] && [ "$current_version" = "$desired_version" ]; then
        log_info "agent-deck ''${version} already installed"
        return 0
      fi

      log_info "building agent-deck ''${version}"
      if ! ${pkgs.git}/bin/git clone --depth 1 --branch "$version" https://github.com/asheshgoplani/agent-deck "$source_dir/repo" >/dev/null 2>&1; then
        log_warn "agent-deck source checkout failed, continuing"
        return 0
      fi

      if ! (
        cd "$source_dir/repo"
        PATH=${lib.makeBinPath [ pkgs.go pkgs.git pkgs.coreutils ]}:$PATH
        GOCACHE="$(mktemp -d)"
        GOPATH="$(mktemp -d)"
        trap 'rm -rf "$GOCACHE" "$GOPATH"' EXIT
        ${pkgs.go}/bin/go build -ldflags "-s -w -X main.Version=$desired_version" -o agent-deck ./cmd/agent-deck
      ); then
        log_warn "agent-deck build failed, continuing"
        return 0
      fi

      if [ ! -x "$source_dir/repo/agent-deck" ]; then
        log_warn "agent-deck built binary missing, continuing"
        return 0
      fi

      install -m755 "$source_dir/repo/agent-deck" "${agentBinDir}/agent-deck"
    }

    ensure_managed_global_skill() {
      name="$1"
      source="$2"

      if skills_json="$(${pkgs.nodejs}/bin/npx -y skills list -g --json 2>/dev/null)"; then
        if printf '%s\n' "$skills_json" | ${pkgs.jq}/bin/jq -e --arg name "$name" 'map(select(.scope == "global" and .name == $name)) | length > 0' >/dev/null; then
          return 0
        fi
      else
        log_warn "global skills discovery failed before managed install, continuing"
      fi

      log_info "installing managed skill $name"

      if ! skills_output="$(${pkgs.nodejs}/bin/npx -y skills add "$source" --global --yes 2>&1)"; then
        log_warn "managed skill $name install failed, continuing"
        if [ -n "$skills_output" ]; then
          printf '%s\n' "$skills_output" >&2
        fi
        return 0
      fi

      if [ -n "$skills_output" ]; then
        printf '%s\n' "$skills_output" >&2
      fi
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

    ensure_agent_browser_runtime() {
      if [ -d "$HOME/.agent-browser" ]; then
        return 0
      fi

      log_info "installing agent-browser runtime (system deps already packaged)"

      # Nix supplies the shared libraries through the wrapper, so maintenance
      # only needs the browser runtime download on these hosts.
      if ! browser_output="$(${agentBrowser}/bin/agent-browser install 2>&1)"; then
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

    refresh_gemini_extension() {
      name="$1"
      repo="$2"
      dir="$HOME/.gemini/extensions/$name"

      if [ ! -x "${agentBinDir}/gemini" ]; then
        log_warn "gemini is not installed yet, skipping extension refresh"
        return 0
      fi

      if [ -d "$dir" ] && [ ! -d "$dir/.git" ]; then
        return 0
      fi

      if [ -d "$dir/.git" ]; then
        log_info "refreshing $name"
        if ! extension_output="$(${agentBinDir}/gemini extensions update "$name" 2>&1)"; then
          log_warn "$name refresh failed, continuing"
          if [ -n "$extension_output" ]; then
            printf '%s\n' "$extension_output" >&2
          fi
          return 0
        fi
      else
        log_info "installing $name"
        if ! extension_output="$(${agentBinDir}/gemini extensions install "$repo" --auto-update --consent 2>&1)"; then
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

    refresh_opencode_programming_free_models() {
      opencode_models_url='https://openrouter.ai/api/frontend/models/find?categories=programming&fmt=cards&max_price=0&order=top-weekly'
      opencode_state_dir="$XDG_STATE_HOME/opencode"
      opencode_config_dir="$XDG_CONFIG_HOME/opencode"
      opencode_generated_config="${opencodeUserConfigPath}"

      mkdir -p "$NPM_CONFIG_PREFIX/bin" "$NPM_CONFIG_PREFIX/lib" "$opencode_state_dir" "$opencode_config_dir"

      log_info "refreshing opencode programming free models"

      response_file="$(mktemp "$opencode_state_dir/openrouter-models.XXXXXX.json")"
      config_file="$(mktemp "$opencode_state_dir/opencode-config.XXXXXX.json")"

      if ! ${pkgs.curl}/bin/curl --fail --silent --show-error --location \
        "$opencode_models_url" > "$response_file"; then
        log_warn "opencode model refresh fetch failed, continuing"
        rm -f "$response_file" "$config_file"
        return 0
      fi

      if ! ${pkgs.jq}/bin/jq -ce '
        def ghostship_name:
          if (. // "") | length == 0 then .
          elif test("\\(free\\)$") then sub("\\(free\\)$"; "(ghostship-free)")
          else . + " (ghostship-free)"
          end;

        .data.models
        | map(
            select((.endpoint.pricing.prompt // "") == "0")
            | select((.endpoint.pricing.completion // "") == "0")
            | {
                id: (.endpoint.model_variant_slug // ""),
                name: ((.name // "") | ghostship_name)
              }
          )
        | map(select(.id | length > 0))
        | if length == 0 then error("no free programming models returned") else . end
        | {
            "$schema": "https://opencode.ai/config.json",
            permission: "allow",
            provider: {
              openrouter: {
                models: (
                  reduce .[] as $model (
                    {};
                    .[$model.id] = (
                      if ($model.name | length) > 0
                      then { name: $model.name }
                      else {}
                      end
                    )
                  )
                )
              }
            }
          }
      ' "$response_file" > "$config_file"; then
        log_warn "opencode model refresh parse failed, continuing"
        rm -f "$response_file" "$config_file"
        return 0
      fi

      mv "$config_file" "$opencode_generated_config"
      rm -f "$response_file"
    }

    mkdir -p "$NPM_CONFIG_PREFIX/bin" "$NPM_CONFIG_PREFIX/lib"

    install_agent_deck_latest
    install_agent_cli "@openai/codex" "codex"
    install_agent_cli "@google/gemini-cli" "gemini"
    install_agent_cli "opencode-ai" "opencode"
    install_agent_cli "${paseoPackage}" "paseo"
    remove_stale_openspec_cli
    ${lib.concatMapStrings (skill: ''
      ensure_managed_global_skill "${skill.name}" "${skill.source}"
    '') managedGlobalSkills}
    refresh_global_skills
    ensure_agent_browser_runtime
    ${lib.concatMapStrings (extension: ''
      refresh_gemini_extension "${extension.name}" "${extension.repo}"
    '') geminiExtensions}
    refresh_opencode_programming_free_models
  '';

  mkInstalledAgentWrapper =
    {
      name,
      binaryName,
      extraEnvironment ? "",
      preExecHook ? "",
    }:
    pkgs.writeShellScriptBin name ''
      set -euo pipefail

      ${extraEnvironment}

      if [ ! -x "${agentBinDir}/${binaryName}" ]; then
        printf 'error: %s is not installed yet; run `ghostship-agent-maintenance` or wait for the boot timer\n' "${name}" >&2
        exit 1
      fi

      ${preExecHook}

      exec "${agentBinDir}/${binaryName}" "$@"
    '';
in
{
  inherit agentBinDir;
  inherit agentBrowser;
  inherit agentMaintenance;
  inherit browserRuntimeLdLibraryPath;
  inherit geminiExtensions;
  inherit mkInstalledAgentWrapper;
  inherit runtimeBinPath;
  inherit runtimeInputs;
}
