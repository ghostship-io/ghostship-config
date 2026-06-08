#!/usr/bin/env sh
set -eu

export NODE_NO_WARNINGS=1
export HOME=/home/codex
export USER=codex
export XDG_CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
export XDG_STATE_HOME="${XDG_STATE_HOME:-$HOME/.local/state}"
export NPM_CONFIG_PREFIX="$HOME/.local/share/ghostship-agent-tools/npm"
export npm_config_prefix="$NPM_CONFIG_PREFIX"
export PATH="$NPM_CONFIG_PREFIX/bin:$PATH"

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

  if ! install_output="$(npm install -g --no-fund --no-audit "$package@latest" 2>&1)"; then
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

opencode_loader_name() {
  case "$(uname -m)" in
    aarch64|arm64)
      printf '%s\n' "ld-linux-aarch64.so.1"
      ;;
    x86_64|amd64)
      printf '%s\n' "ld-linux-x86-64.so.2"
      ;;
    *)
      return 1
      ;;
  esac
}

find_nix_glibc_loader() {
  loader_name="$(opencode_loader_name)" || return 1

  for store_dir in /nix/store "$HOME/.local/share/nix/root/nix/store"; do
    if [ ! -d "$store_dir" ]; then
      continue
    fi

    for candidate in "$store_dir"/*-glibc-*/lib/"$loader_name"; do
      if [ -x "$candidate" ]; then
        printf '%s\n' "$candidate"
        return 0
      fi
    done
  done

  return 1
}

install_opencode_platform_wrapper() {
  platform_package="$1"
  fallback_bin="$NPM_CONFIG_PREFIX/lib/node_modules/$platform_package/bin/opencode"

  if [ ! -x "$fallback_bin" ]; then
    log_warn "$platform_package binary is missing, continuing"
    return 0
  fi

  loader="$(find_nix_glibc_loader || true)"

  rm -f "$NPM_CONFIG_PREFIX/bin/opencode"
  cat > "$NPM_CONFIG_PREFIX/bin/opencode" <<EOF
#!/usr/bin/env sh
set -eu
fallback_bin='$fallback_bin'
loader='$loader'
if [ -n "\$loader" ]; then
  exec "\$loader" --library-path "\${loader%/*}" "\$fallback_bin" "\$@"
fi
exec "\$fallback_bin" "\$@"
EOF
  chmod 0755 "$NPM_CONFIG_PREFIX/bin/opencode"
}

install_opencode_cli() {
  log_info "installing or upgrading opencode"

  rm -f "$NPM_CONFIG_PREFIX/bin/opencode"

  if install_output="$(npm install -g --no-fund --no-audit opencode-ai@latest 2>&1)"; then
    if [ -n "$install_output" ]; then
      printf '%s\n' "$install_output" >&2
    fi
    return 0
  fi

  log_warn "opencode install failed, trying platform package"
  if [ -n "$install_output" ]; then
    printf '%s\n' "$install_output" >&2
  fi

  case "$(uname -m)" in
    aarch64|arm64)
      platform_package="opencode-linux-arm64"
      ;;
    x86_64|amd64)
      platform_package="opencode-linux-x64"
      ;;
    *)
      log_warn "unsupported opencode fallback architecture: $(uname -m)"
      return 0
      ;;
  esac

  if ! platform_output="$(npm install -g --no-fund --no-audit "$platform_package@latest" 2>&1)"; then
    log_warn "$platform_package install failed, continuing"
    if [ -n "$platform_output" ]; then
      printf '%s\n' "$platform_output" >&2
    fi
    return 0
  fi

  if [ -n "$platform_output" ]; then
    printf '%s\n' "$platform_output" >&2
  fi

  install_opencode_platform_wrapper "$platform_package"
}

remove_stale_openspec_cli() {
  log_info "removing stale openspec CLI"
  rm -f "$NPM_CONFIG_PREFIX/bin/openspec"
  rm -rf "$NPM_CONFIG_PREFIX/lib/node_modules/@fission-ai/openspec"
  rmdir "$NPM_CONFIG_PREFIX/lib/node_modules/@fission-ai" 2>/dev/null || true
}

refresh_global_skills() {
  if [ ! -x "$NPM_CONFIG_PREFIX/bin/skills" ]; then
    log_warn "skills is not installed yet, skipping global skill refresh"
    return 0
  fi

  if ! skills_json="$("$NPM_CONFIG_PREFIX/bin/skills" list -g --json 2>&1)"; then
    log_warn "global skills discovery failed, continuing"
    if [ -n "$skills_json" ]; then
      printf '%s\n' "$skills_json" >&2
    fi
    return 0
  fi

  if printf '%s\n' "$skills_json" | grep -Eq '^[[:space:]]*\[[[:space:]]*\][[:space:]]*$'; then
    return 0
  fi

  log_info "refreshing global skills"

  if ! skills_output="$("$NPM_CONFIG_PREFIX/bin/skills" update -g 2>&1)"; then
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

  if ! browser_output="$(agent-browser install 2>&1)"; then
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

  if [ ! -x "$NPM_CONFIG_PREFIX/bin/gemini" ]; then
    log_warn "gemini is not installed yet, skipping extension refresh"
    return 0
  fi

  if [ -d "$dir" ] && [ ! -d "$dir/.git" ]; then
    return 0
  fi

  if [ -d "$dir/.git" ]; then
    log_info "refreshing $name"
    if ! extension_output="$("$NPM_CONFIG_PREFIX/bin/gemini" extensions update "$name" 2>&1)"; then
      log_warn "$name refresh failed, continuing"
      if [ -n "$extension_output" ]; then
        printf '%s\n' "$extension_output" >&2
      fi
      return 0
    fi
  else
    log_info "installing $name"
    if ! extension_output="$("$NPM_CONFIG_PREFIX/bin/gemini" extensions install "$repo" --auto-update --consent 2>&1)"; then
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
  opencode_generated_config="$opencode_config_dir/opencode.json"

  mkdir -p "$NPM_CONFIG_PREFIX/bin" "$NPM_CONFIG_PREFIX/lib" "$opencode_state_dir" "$opencode_config_dir"

  log_info "refreshing opencode programming free models"

  response_file="$(mktemp "$opencode_state_dir/openrouter-models.XXXXXX.json")"
  config_file="$(mktemp "$opencode_state_dir/opencode-config.XXXXXX.json")"

  if ! curl --fail --silent --show-error --location "$opencode_models_url" > "$response_file"; then
    log_warn "opencode model refresh fetch failed, continuing"
    rm -f "$response_file" "$config_file"
    return 0
  fi

  if ! jq -ce '
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
install_opencode_cli
install_agent_cli "skills" "skills"
remove_stale_openspec_cli
refresh_global_skills
ensure_agent_browser_runtime
refresh_gemini_extension "gemini-cli-security" "https://github.com/gemini-cli-extensions/security"
refresh_opencode_programming_free_models
