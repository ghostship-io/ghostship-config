{
  pkgs,
  lib ? pkgs.lib,
  ...
}:

let
  openspecPackage = "@fission-ai/openspec@latest";
  defaultOpenspecTools = "codex,gemini,opencode";
  defaultOpenspecProfile = "core";
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
    pkgs.coreutils
    pkgs.curl
    pkgs.gawk
    pkgs.git
    pkgs.gnugrep
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
    export LD_LIBRARY_PATH="${browserRuntimeLdLibraryPath}${
      if browserRuntimeLdLibraryPath != "" then ":" else ""
    }''${LD_LIBRARY_PATH:-}"

    exec ${pkgs.nodejs}/bin/npx -y agent-browser "$@"
  '';

  openspecCli = pkgs.writeShellScriptBin "openspec" ''
    set -euo pipefail

    PATH=${baseRuntimeBinPath}:$PATH
    export NODE_NO_WARNINGS=1

    strip_marked_block() {
      file="$1"
      begin="$2"
      end="$3"
      tmp="$(${pkgs.coreutils}/bin/mktemp)"

      ${pkgs.gawk}/bin/awk -v begin="$begin" -v end="$end" '
        $0 == begin { skipping = 1; next }
        $0 == end { skipping = 0; next }
        !skipping { print }
      ' "$file" > "$tmp"

      ${pkgs.coreutils}/bin/mv "$tmp" "$file"
    }

    append_markdown_override() {
      src="$1"
      dest="$2"
      block_id="$3"

      if [ ! -f "$src" ] || [ ! -f "$dest" ]; then
        return 0
      fi

      begin="<!-- ghostship:$block_id:begin -->"
      end="<!-- ghostship:$block_id:end -->"

      strip_marked_block "$dest" "$begin" "$end"

      tmp="$(${pkgs.coreutils}/bin/mktemp)"
      {
        ${pkgs.coreutils}/bin/cat "$dest"
        printf '\n%s\n' "$begin"
        ${pkgs.coreutils}/bin/cat "$src"
        printf '%s\n' "$end"
      } > "$tmp"

      ${pkgs.coreutils}/bin/mv "$tmp" "$dest"
    }

    insert_toml_prompt_override() {
      src="$1"
      dest="$2"
      block_id="$3"

      if [ ! -f "$src" ] || [ ! -f "$dest" ]; then
        return 0
      fi

      begin="<!-- ghostship:$block_id:begin -->"
      end="<!-- ghostship:$block_id:end -->"

      strip_marked_block "$dest" "$begin" "$end"

      tmp="$(${pkgs.coreutils}/bin/mktemp)"
      ${pkgs.gawk}/bin/awk -v begin="$begin" -v end="$end" -v src="$src" '
        { lines[++n] = $0 }
        END {
          if (n == 0) {
            exit 0
          }

          inserted = 0

          for (i = 1; i <= n; i++) {
            if (!inserted && i == n && lines[i] == "\"\"\"") {
              print ""
              print begin
              while ((getline line < src) > 0) print line
              close(src)
              print end
              print lines[i]
              inserted = 1
            } else {
              print lines[i]
            }
          }

          if (!inserted) {
            print ""
            print begin
            while ((getline line < src) > 0) print line
            close(src)
            print end
          }
        }
      ' "$dest" > "$tmp"

      ${pkgs.coreutils}/bin/mv "$tmp" "$dest"
    }

    create_override_file() {
      key="$1"
      tmp="$(${pkgs.coreutils}/bin/mktemp)"

      case "$key" in
        propose)
          ${pkgs.coreutils}/bin/cat > "$tmp" <<'EOF'
## Ghostship Override

- Create and refine the proposal, design, and tasks on `main`.
EOF
          ;;
        apply)
          ${pkgs.coreutils}/bin/cat > "$tmp" <<'EOF'
## Ghostship Override

- Before implementation, commit the proposal, design, and tasks changes for the change on `main`.
- Then use `using-git-worktrees` if it is available.
- Create or reuse `.worktrees/<name>/` from that committed `main` state.
- Start implementation from the change worktree itself, not from `main`.
- If implementation gets stuck on a bug, failing test, or unexpected behavior, use `systematic-debugging` if it is available.
- Do root-cause-first debugging before proposing or applying fixes.
EOF
          ;;
        archive)
          ${pkgs.coreutils}/bin/cat > "$tmp" <<'EOF'
## Ghostship Override

- If the user does not specify a change, assume `archive` applies to the change currently being worked on.
- Before archiving, check whether the change has a matching worktree.
- If it does, explicitly use `$using-git-worktrees` to work from that isolated checkout while reconciling and cleaning up the change.
- If it does, commit all pending work in the worktree.
- Merge `main` into the worktree and resolve any issues there.
- Merge the worktree back into `main`.
- Run the archive flow on `main` and commit the resulting archive move there.
- After the archive commit succeeds, delete the change worktree with `git worktree remove <worktree-path>`.
EOF
          ;;
        *)
          rm -f "$tmp"
          return 1
          ;;
      esac

      printf '%s\n' "$tmp"
    }

    apply_personal_openspec_overrides() {
      project_root="$1"

      if [ ! -d "$project_root/openspec" ]; then
        return 0
      fi

      propose_override="$(create_override_file propose)"
      apply_override="$(create_override_file apply)"
      archive_override="$(create_override_file archive)"

      for tool_dir in .codex .gemini .opencode; do
        append_markdown_override \
          "$propose_override" \
          "$project_root/$tool_dir/skills/openspec-propose/SKILL.md" \
          "$tool_dir-openspec-propose"
        append_markdown_override \
          "$apply_override" \
          "$project_root/$tool_dir/skills/openspec-apply-change/SKILL.md" \
          "$tool_dir-openspec-apply-change"
        append_markdown_override \
          "$archive_override" \
          "$project_root/$tool_dir/skills/openspec-archive-change/SKILL.md" \
          "$tool_dir-openspec-archive-change"
      done

      if [ -d "$project_root/.gemini/commands/opsx" ]; then
        insert_toml_prompt_override \
          "$propose_override" \
          "$project_root/.gemini/commands/opsx/propose.toml" \
          "gemini-opsx-propose"
        insert_toml_prompt_override \
          "$apply_override" \
          "$project_root/.gemini/commands/opsx/apply.toml" \
          "gemini-opsx-apply"
        insert_toml_prompt_override \
          "$archive_override" \
          "$project_root/.gemini/commands/opsx/archive.toml" \
          "gemini-opsx-archive"
      fi

      if [ -d "$project_root/.opencode/command" ]; then
        append_markdown_override \
          "$propose_override" \
          "$project_root/.opencode/command/opsx-propose.md" \
          "opencode-opsx-propose"
        append_markdown_override \
          "$apply_override" \
          "$project_root/.opencode/command/opsx-apply.md" \
          "opencode-opsx-apply"
        append_markdown_override \
          "$archive_override" \
          "$project_root/.opencode/command/opsx-archive.md" \
          "opencode-opsx-archive"
      fi

      rm -f "$propose_override" "$apply_override" "$archive_override"
    }

    resolve_command_target() {
      shift || true
      target=""

      while [ "$#" -gt 0 ]; do
        case "$1" in
          --tools|--profile)
            shift 2
            ;;
          --description|--schema)
            shift 2
            ;;
          --tools=*|--profile=*|--description=*|--schema=*|--force|-h|--help)
            shift
            ;;
          --*)
            shift
            ;;
          *)
            target="$1"
            shift
            ;;
        esac
      done

      if [ -n "$target" ]; then
        ${pkgs.coreutils}/bin/realpath -m "$target"
      else
        ${pkgs.coreutils}/bin/pwd -P
      fi
    }

    run_upstream_openspec() {
      ${pkgs.nodejs}/bin/npx -y ${openspecPackage} "$@"
    }

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

      init_args=("init")

      if [ "$has_tools_arg" -eq 0 ]; then
        init_args+=(--tools ${defaultOpenspecTools})
      fi

      if [ "$has_profile_arg" -eq 0 ]; then
        init_args+=(--profile ${defaultOpenspecProfile})
      fi

      init_args+=("''${@:2}")
      init_target="$(resolve_command_target "''${init_args[@]}")"

      if run_upstream_openspec "''${init_args[@]}"; then
        apply_personal_openspec_overrides "$init_target"
        exit 0
      fi

      exit "$?"
    fi

    if [ "$#" -gt 0 ] && [ "$1" = "update" ]; then
      update_target="$(resolve_command_target "$@")"

      if run_upstream_openspec "$@"; then
        apply_personal_openspec_overrides "$update_target"
        exit 0
      fi

      exit "$?"
    fi

    exec ${pkgs.nodejs}/bin/npx -y ${openspecPackage} "$@"
  '';

  runtimeInputs = baseRuntimeInputs ++ [
    agentBrowser
    openspecCli
  ];

  runtimeBinPath = lib.makeBinPath runtimeInputs;

  geminiExtensions = [
    {
      name = "gemini-cli-security";
      repo = "https://github.com/gemini-cli-extensions/security";
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

      log_info "installing agent-browser runtime"

      if ! browser_output="$(${agentBrowser}/bin/agent-browser install --with-deps 2>&1)"; then
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
  inherit openspecCli;
  inherit runtimeBinPath;
  inherit runtimeInputs;
}
