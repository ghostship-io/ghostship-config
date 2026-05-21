{
  pkgs,
  lib ? pkgs.lib,
  ...
}:

let
  userHome = "/home/nixos";
  agentToolsRoot = "${userHome}/.local/share/ghostship-agent-tools";
  agentNpmPrefix = "${agentToolsRoot}/npm";
  agentBinDir = "${agentNpmPrefix}/bin";
  codexSystemSkillsDir = "${userHome}/.codex/skills/.system";
  codexSkillCreatorPath = "${codexSystemSkillsDir}/skill-creator";
  sharedSkillCreatorPath = "${userHome}/.agents/skills/skill-creator";
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
      source = "obra/superpowers";
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

    reassert_codex_skill_creator_override() {
      mkdir -p "${codexSystemSkillsDir}"

      if [ ! -e "${sharedSkillCreatorPath}" ]; then
        log_warn "shared skill-creator path is missing, skipping Codex override"
        return 0
      fi

      rm -rf "${codexSkillCreatorPath}"
      ln -sfn "${sharedSkillCreatorPath}" "${codexSkillCreatorPath}"
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

    ensure_managed_global_skill() {
      name="$1"
      source="$2"
      skill_dir="$HOME/.agents/skills/$name"

      if [ -f "$skill_dir/SKILL.md" ]; then
        return 0
      fi

      if skills_json="$(${agentBinDir}/skills list -g --json 2>/dev/null)"; then
        if printf '%s\n' "$skills_json" | ${pkgs.jq}/bin/jq -e --arg name "$name" 'map(select(.scope == "global" and .name == $name)) | length > 0' >/dev/null; then
          if [ -f "$skill_dir/SKILL.md" ]; then
            return 0
          fi
        fi
      else
        log_warn "global skills discovery failed before managed install, continuing"
      fi

      log_info "installing managed skill $name"

      if ! skills_output="$(${agentBinDir}/skills add "$source" --skill "$name" --global --yes 2>&1)"; then
        log_warn "managed skill $name install failed, continuing"
        if [ -n "$skills_output" ]; then
          printf '%s\n' "$skills_output" >&2
        fi
        return 0
      fi

      if [ -n "$skills_output" ]; then
        printf '%s\n' "$skills_output" >&2
      fi

      if [ ! -f "$skill_dir/SKILL.md" ]; then
        log_warn "managed skill $name did not create $skill_dir/SKILL.md"
      fi
    }

    refresh_global_skills() {
      if ! skills_json="$(${agentBinDir}/skills list -g --json 2>&1)"; then
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

      if ! skills_output="$(${agentBinDir}/skills update -g 2>&1)"; then
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

    install_agent_cli "@openai/codex" "codex"
    install_agent_cli "@google/gemini-cli" "gemini"
    install_agent_cli "opencode-ai" "opencode"
    install_agent_cli "skills" "skills"
    remove_stale_openspec_cli
    reassert_codex_skill_creator_override
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
