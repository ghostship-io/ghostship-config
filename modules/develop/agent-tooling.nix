{
  pkgs,
  lib ? pkgs.lib,
  ...
}:

let
  openspecPackage = "@fission-ai/openspec";
  paseoPackage = "@getpaseo/cli";
  defaultOpenspecTools = "codex,gemini,opencode";
  defaultOpenspecProfile = "core";
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

  openspecCli = pkgs.writeShellScriptBin "openspec" ''
    set -euo pipefail

    PATH=${baseRuntimeBinPath}:$PATH
    export NODE_NO_WARNINGS=1
    export DO_NOT_TRACK="''${DO_NOT_TRACK:-1}"
    export OPENSPEC_TELEMETRY="''${OPENSPEC_TELEMETRY:-0}"

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

- Create or reuse the change worktree at the start of propose.
- Create and refine the proposal, design, and tasks from the active change worktree, not from `main`.
- When working in a worktree, use Python-based file edits instead of `apply_patch`.
- Verify the diff after each worktree file edit.
- When propose finishes, give the user a detailed overview of the full proposed change and everything it plans to do before moving on.
EOF
          ;;
        apply)
          ${pkgs.coreutils}/bin/cat > "$tmp" <<'EOF'
## Ghostship Override

- Before implementation, commit the proposal, design, and tasks changes for the change in the active worktree.
- Implement from the active change worktree, not from `main`.
- During apply, if the user changes the work, do not create a new proposal or a new worktree; update the current proposal instead.
- Keep track of issues, follow-up work, and notable problems found during apply.
- If implementation gets stuck on a bug, failing test, or unexpected behavior, use `systematic-debugging` if it is available.
- Do root-cause-first debugging before proposing or applying fixes.
- When apply finishes, give the user a detailed overview of the completed work, the changes made, any proposal updates made during apply, and any issues found during apply before moving on.
EOF
          ;;
        archive)
          ${pkgs.coreutils}/bin/cat > "$tmp" <<'EOF'
## Ghostship Override

- If the user does not specify a change, assume `archive` applies to the change currently being worked on.
- Before archiving, check whether the change has a matching worktree.
- If it does, work from that isolated checkout while reconciling and cleaning up the change.
- If it does, commit all pending work in the worktree.
- Merge `main` into the worktree and resolve any issues there.
- Merge the worktree back into `main`.
- Run the archive flow on `main` and commit the resulting archive move there.
- After the archive commit succeeds, delete the change worktree with `git worktree remove <worktree-path>`.
- After archive completes, return `main` to a clean working state if possible.
- Reconcile or remove remaining related artifacts.
- Clearly report anything that still requires manual cleanup.
- After archive finishes, give the user a list of issues or follow-up work that should be considered next.
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
      if [ -x "${agentBinDir}/openspec" ]; then
        "${agentBinDir}/openspec" "$@"
      else
        ${pkgs.nodejs}/bin/npx -y ${openspecPackage}@latest "$@"
      fi
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

    run_upstream_openspec "$@"
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

  managedGlobalSkills = [ ];

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

      log_info "building patched agent-deck ''${version}"
      if ! ${pkgs.git}/bin/git clone --depth 1 --branch "$version" https://github.com/asheshgoplani/agent-deck "$source_dir/repo" >/dev/null 2>&1; then
        log_warn "agent-deck source checkout failed, continuing"
        return 0
      fi

      ${pkgs.python3}/bin/python - "$source_dir/repo/cmd/agent-deck/web_cmd.go" "$source_dir/repo/cmd/agent-deck/main.go" <<'PY'
import pathlib
import sys

web_cmd = pathlib.Path(sys.argv[1])
main_go = pathlib.Path(sys.argv[2])

web_text = web_cmd.read_text()
old_web = """\tserver := web.NewServer(web.Config{\n\t\tListenAddr:          *listenAddr,\n\t\tProfile:             effectiveProfile,\n\t\tReadOnly:            *readOnly,\n\t\tToken:               *token,\n"""
new_web = """\tserver := web.NewServer(web.Config{\n\t\tListenAddr:          *listenAddr,\n\t\tProfile:             effectiveProfile,\n\t\tReadOnly:            *readOnly,\n\t\tWebMutations:        !*readOnly,\n\t\tToken:               *token,\n"""
if old_web not in web_text:
    raise SystemExit("expected web server config block not found")
web_cmd.write_text(web_text.replace(old_web, new_web, 1))

main_text = main_go.read_text()
old_main = """\t\tif costStore != nil {\n\t\t\tserver.SetCostStore(costStore)\n\t\t}\n"""
new_main = """\t\tif costStore != nil {\n\t\t\tserver.SetCostStore(costStore)\n\t\t}\n\t\tserver.SetMutator(ui.NewWebMutator(homeModel))\n"""
if old_main not in main_text:
    raise SystemExit("expected main web server setup block not found")
main_go.write_text(main_text.replace(old_main, new_main, 1))
PY

      if ! (
        cd "$source_dir/repo"
        PATH=${lib.makeBinPath [ pkgs.go pkgs.git pkgs.coreutils ]}:$PATH
        GOCACHE="$(mktemp -d)"
        GOPATH="$(mktemp -d)"
        trap 'rm -rf "$GOCACHE" "$GOPATH"' EXIT
        ${pkgs.go}/bin/go build -ldflags "-s -w -X main.Version=$desired_version" -o agent-deck ./cmd/agent-deck
      ); then
        log_warn "agent-deck patched build failed, continuing"
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
    install_agent_cli "${openspecPackage}" "openspec"
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
  inherit openspecCli;
  inherit runtimeBinPath;
  inherit runtimeInputs;
}
