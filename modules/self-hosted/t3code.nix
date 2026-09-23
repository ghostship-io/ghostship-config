{
  config,
  lib,
  pkgs,
  ...
}:

let
  providerManifest = import ../../packages/t3code/provider-manifest.nix { inherit lib; };
  t3codeActivityProbe = pkgs.callPackage ../../packages/t3code/activity-probe/default.nix { };
  t3codeHome = "/srv/apps/t3code/home";
  t3codeDocker = "/srv/apps/t3code/docker";
  t3codeNixRoot = "/srv/apps/t3code/nix-root";
  t3codeWorkspace = config.ghostship.agentHost.workspacePath;
  t3codeSecrets = config.ghostship.selfHostedSecrets.projections.t3code.path;
  t3codeSecretsFile = "/run/secrets/t3code.env";
  imageName = "localhost/ghostship-t3code";
  imageTag = "t3code-runtime";

  t3codePackages = with pkgs; [
    nix
    systemd
    dbus
    pam
    docker
    cloudflared
    sudo
    git
    git-lfs
    gh
    openssh
    curl
    jq
    ripgrep
    fd
    direnv
    uv
    python3
    ruff
    basedpyright
    nil
    nixfmt
    shellcheck
    shfmt
    yq-go
    buildkit
    bubblewrap
    fuse-overlayfs
    nodejs_24
    typescript-language-server
    prettier
    stdenv.cc
    gnumake
    pkg-config
    cmake
    binutils
    coreutils
    findutils
    gnugrep
    gnused
    gnutar
    gzip
    lbzip2
    unzip
    p7zip
    procps
    iptables
    iproute2
    kmod
    su-exec
    which
    file
    bashInteractive
    cacert
    openssl
  ];

  antigravityAcp = pkgs.callPackage ../../packages/t3code/antigravity-acp.nix { };

  t3codePath = lib.makeBinPath t3codePackages;
  t3codeRuntimeEnv = ''
    if [ -f ${t3codeSecretsFile} ]; then
      set -a
      # shellcheck disable=SC1091
      . ${t3codeSecretsFile}
      set +a
    fi
    export HOME=/home/t3code
    export USER=t3code
    export XDG_CONFIG_HOME="''${XDG_CONFIG_HOME:-$HOME/.config}"
    export XDG_STATE_HOME="''${XDG_STATE_HOME:-$HOME/.local/state}"
    export XDG_CACHE_HOME="''${XDG_CACHE_HOME:-$HOME/.cache}"
    export XDG_DATA_HOME="''${XDG_DATA_HOME:-$HOME/.local/share}"
    export NPM_CONFIG_PREFIX="$HOME/.local/share/t3code-tools/npm"
    export npm_config_prefix="$NPM_CONFIG_PREFIX"
    export OPENCODE_AUTOMATION_DIR="$HOME/.automation"
    export T3CODE_HOME="$HOME/.t3"
    export T3CODE_HOST=127.0.0.1
    export T3CODE_PORT=3774
    export T3CODE_NO_BROWSER=true
    # Project-pinned Nix programs must use their own runtime libraries.
    unset LD_LIBRARY_PATH
    hm_session_vars="$HOME/.nix-profile/etc/profile.d/hm-session-vars.sh"
    if [ -f "$hm_session_vars" ]; then
      # shellcheck disable=SC1090
      case "$-" in *u*) restore_nounset=1 ;; *) restore_nounset=0 ;; esac
      set +u
      . "$hm_session_vars"
      if [ "$restore_nounset" -eq 1 ]; then
        set -u
      fi
    fi
    export PATH=${t3codePath}:$HOME/.local/bin:$NPM_CONFIG_PREFIX/bin:/bin:/usr/bin:$PATH
    export DOCKER_HOST=unix:///var/run/docker.sock
    export XDG_RUNTIME_DIR=/run/user/3000
    export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/3000/bus
    export NIX_SSL_CERT_FILE=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt
    export SSL_CERT_FILE=$NIX_SSL_CERT_FILE
    export NIX_CONFIG="experimental-features = nix-command flakes"
    export NIX_REMOTE=daemon
  '';

  sourceHmSessionVarsIfPresent = ''
    hm_session_vars="\$HOME/.nix-profile/etc/profile.d/hm-session-vars.sh"
    if [ -f "\$hm_session_vars" ]; then
      # shellcheck disable=SC1090
      case "\$-" in *u*) restore_nounset=1 ;; *) restore_nounset=0 ;; esac
      set +u
      . "\$hm_session_vars"
      if [ "\$restore_nounset" -eq 1 ]; then
        set -u
      fi
    fi
  '';

  t3codeIdleCheck = ''
    is_t3code_idle() {
      T3CODE_STATE_DB="$T3CODE_HOME/userdata/state.sqlite" ${t3codeActivityProbe}/bin/t3code-activity-probe
      return $?
    }
  '';

  # Sign-in is user-owned. Missing credentials must not restart the server.
  t3codeProviderCheck = ''
    t3code_providers_healthy() {
      for provider in codex claude cursor opencode; do
        [ -x "$HOME/.local/bin/$provider" ] || return 1
      done
      [ -x ${antigravityAcp}/bin/agy_acp_server.par ]
    }
  '';

  t3codeCodexRgRepair = pkgs.writeShellScriptBin "t3code-codex-rg-repair" ''
    set -eu

    npm_prefix="''${NPM_CONFIG_PREFIX:-/home/t3code/.local/share/t3code-tools/npm}"
    codex_root="$npm_prefix/lib/node_modules/@openai/codex"
    repaired=0

    for vendor_rg in \
      "$codex_root"/node_modules/@openai/codex-linux-*/vendor/*/codex-path/rg; do
      if [ ! -e "$vendor_rg" ] && [ ! -L "$vendor_rg" ]; then
        continue
      fi
      ln -sfn ${pkgs.ripgrep}/bin/rg "$vendor_rg"
      repaired=1
    done

    if [ "$repaired" -ne 1 ]; then
      printf 'warning: Codex bundled rg was not found; repair skipped\n' >&2
      exit 0
    fi

    ${pkgs.ripgrep}/bin/rg --version >/dev/null
  '';

  t3codeAntigravityUpdate = pkgs.writeShellScriptBin "t3code-antigravity-update" ''
    set -eu
    ${t3codeRuntimeEnv}
    exec ${pkgs.python3}/bin/python ${../../packages/t3code/update-antigravity.py} \
      --bundled-version ${antigravityAcp.version} \
      --probe ${../../tests/t3code-acp-smoke.py}
  '';

  t3codeInstallT3Shim = pkgs.writeShellScriptBin "t3code-install-t3-shim" ''
    set -eu

    target="''${1:-$HOME/.local/share/t3code-tools/t3/current/bin/t3}"
    if [ ! -x "$target" ] && [ -x "$NPM_CONFIG_PREFIX/bin/t3" ]; then
      target="$NPM_CONFIG_PREFIX/bin/t3"
    fi
    mkdir -p "$HOME/.local/bin"
    temporary="$HOME/.local/bin/.t3.tmp.$$"
    cat > "$temporary" <<EOF
    #!/usr/bin/env sh
    set -eu
    target='$target'
    if [ ! -x "\$target" ]; then
      printf 'error: t3 is not installed yet; run t3code-tool-maintenance\n' >&2
      exit 1
    fi
    export LD_LIBRARY_PATH='${lib.makeLibraryPath [ pkgs.stdenv.cc.cc.lib ]}'
    exec "\$target" "\$@"
    EOF
    chmod 0755 "$temporary"
    mv -f "$temporary" "$HOME/.local/bin/t3"
  '';

  t3codeInstallGhostshipAgent = pkgs.writeShellScriptBin "t3code-install-ghostship-agent" ''
    set -eu
    ${t3codeRuntimeEnv}
    if [ "$(id -u)" = 0 ]; then
      exec su-exec t3code:t3code "$0" "$@"
    fi
    if [ ! -f /workspace/ghostship-agent/flake.nix ]; then
      printf 'ghostship-agent project is absent; installation deferred\n'
      exit 0
    fi
    state_dir="$XDG_STATE_HOME/t3code-ghostship-agent"
    mkdir -p "$state_dir"
    exec 8>"$state_dir/install.lock"
    ${pkgs.util-linux}/bin/flock 8
    # Use the shared catalog installer so one owner manages provider skills,
    # command wrappers, the native browser, and their persistent Nix roots.
    exec ${t3codeSharedAgents}/bin/t3code-shared-agents "$@"
  '';

  t3codeToolMaintenance = pkgs.writeShellScriptBin "t3code-tool-maintenance" ''
    set -eu

    ${t3codeRuntimeEnv}
    export NODE_NO_WARNINGS=1
    export PYTHON=${pkgs.python3}/bin/python3

    log_info() {
      printf 'info: %s\n' "$1" >&2
    }

    log_warn() {
      printf 'warn: %s\n' "$1" >&2
    }

    latest_agent_version() {
      package="$1"
      lookup_cache="$(mktemp -d)"
      latest_error="$lookup_cache/stderr"

      if ! latest_output="$(npm view --cache "$lookup_cache" --prefer-online "$package@latest" version 2>"$latest_error")"; then
        log_warn "could not resolve the current $package version"
        if [ -n "$latest_output" ]; then
          printf '%s\n' "$latest_output" >&2
        fi
        if [ -s "$latest_error" ]; then
          cat "$latest_error" >&2
        fi
        rm -rf "$lookup_cache"
        return 1
      fi

      if [ -s "$latest_error" ]; then
        cat "$latest_error" >&2
      fi
      rm -rf "$lookup_cache"
      if ! latest_version="$(printf '%s' "$latest_output" | node -e '
        const input = require("fs").readFileSync(0, "utf8").trim();
        let version = input;
        try {
          const parsed = JSON.parse(input);
          if (typeof parsed === "string") version = parsed;
        } catch (_) {}
        if (!version || version.includes("\\n")) process.exit(1);
        process.stdout.write(version);
      ')"; then
        log_warn "the registry returned an invalid version for $package"
        return 1
      fi

      printf '%s\n' "$latest_version"
    }

    installed_agent_version() {
      package="$1"
      manifest="$NPM_CONFIG_PREFIX/lib/node_modules/$package/package.json"

      if [ ! -f "$manifest" ]; then
        return 1
      fi

      node -p 'require(process.argv[1]).version' "$manifest"
    }

    verify_claude_native_binary() {
      local expected_version="$1" native_manifest="$2" native_binary="$3"
      local native_version native_size native_output

      [ -f "$native_manifest" ] || return 1
      native_version="$(node -p 'require(process.argv[1]).version' "$native_manifest" 2>/dev/null)" || return 1
      [ "$native_version" = "$expected_version" ] || return 1
      [ -x "$native_binary" ] || return 1

      native_size="$(${pkgs.coreutils}/bin/stat -c %s "$native_binary")" || return 1
      case "$native_size" in
        ""|*[!0-9]*) return 1 ;;
      esac
      [ "$native_size" -gt 4096 ] || return 1

      native_output="$(${pkgs.coreutils}/bin/timeout --kill-after=3s 20s "$native_binary" --version 2>/dev/null)" || return 1
      case "$native_output" in
        "$expected_version"*) printf '%s\n' "$native_output" ;;
        *) return 1 ;;
      esac
    }

    install_claude_native_binary() {
      local expected_version="$1"
      local platform native_package native_dir native_manifest native_binary target
      local native_output temporary installed_output install_output

      platform="$(${pkgs.nodejs_24}/bin/node -e '
        const report = process.report?.getReport?.();
        const musl = process.platform === "linux" && report?.header?.glibcVersionRuntime === undefined;
        process.stdout.write(process.platform + "-" + process.arch + (musl ? "-musl" : ""));
      ')"
      case "$platform" in
        linux-x64|linux-arm64|linux-x64-musl|linux-arm64-musl) ;;
        *)
          log_warn "Claude Code has no supported native package for $platform"
          return 1
          ;;
      esac

      native_package="@anthropic-ai/claude-code-$platform"
      native_dir="$NPM_CONFIG_PREFIX/lib/node_modules/$native_package"
      native_manifest="$native_dir/package.json"
      native_binary="$native_dir/claude"
      target="$NPM_CONFIG_PREFIX/lib/node_modules/@anthropic-ai/claude-code/bin/claude.exe"

      if ! native_output="$(verify_claude_native_binary "$expected_version" "$native_manifest" "$native_binary" 2>/dev/null)"; then
        log_info "installing or repairing Claude Code's $platform native package"
        if ! install_output="$(npm install -g --force --prefer-online --no-fund --no-audit "$native_package@$expected_version" 2>&1)"; then
          log_warn "Claude Code's $platform native package install failed"
          if [ -n "$install_output" ]; then
            printf '%s\n' "$install_output" >&2
          fi
          return 1
        fi
        if ! native_output="$(verify_claude_native_binary "$expected_version" "$native_manifest" "$native_binary" 2>/dev/null)"; then
          log_warn "Claude Code's $platform native package remains missing or invalid after reinstall"
          return 1
        fi
      fi
      if [ -z "$native_output" ]; then
        log_warn "Claude Code's $platform native executable did not report its version"
        return 1
      fi

      temporary="$target.repair.$$"
      rm -f "$temporary"
      if ! ln "$native_binary" "$temporary"; then
        log_warn "could not stage Claude Code's verified native executable"
        return 1
      fi
      chmod 0755 "$temporary"
      mv -f "$temporary" "$target"

      if ! installed_output="$(${pkgs.coreutils}/bin/timeout --kill-after=3s 20s "$NPM_CONFIG_PREFIX/bin/claude" --version 2>/dev/null)"; then
        log_warn "Claude Code's installed launcher failed its bounded version check"
        return 1
      fi
      case "$installed_output" in
        "$expected_version"*) ;;
        *)
          log_warn "Claude Code's installed launcher reports an unexpected version"
          return 1
          ;;
      esac
      log_info "Claude Code $expected_version is using the verified $platform native executable"
    }

    install_agent_cli() {
      package="$1"
      label="$2"

      if ! expected_version="$(latest_agent_version "$package")"; then
        return 1
      fi

      log_info "installing or upgrading $label to $expected_version"

      if ! install_output="$(npm install -g --prefer-online --no-fund --no-audit "$package@$expected_version" 2>&1)"; then
        log_warn "$label install failed"
        if [ -n "$install_output" ]; then
          printf '%s\n' "$install_output" >&2
        fi
        return 1
      fi

      if [ -n "$install_output" ]; then
        printf '%s\n' "$install_output" >&2
      fi

      if ! installed_version="$(installed_agent_version "$package")"; then
        log_warn "$label did not install a readable package manifest"
        return 1
      fi

      if [ "$installed_version" != "$expected_version" ]; then
        log_warn "$label remains at $installed_version; expected $expected_version"
        return 1
      fi

      if [ "$package" = "@anthropic-ai/claude-code" ] \
        && ! install_claude_native_binary "$expected_version"; then
        return 1
      fi
    }

    verify_t3_release() {
      local release_dir="$1" expected_version="$2"
      local manifest="$release_dir/lib/node_modules/t3/package.json"
      local installed_version native_manifest native_dir
      [ -x "$release_dir/bin/t3" ] && [ -f "$manifest" ] || return 1
      installed_version="$(node -p 'require(process.argv[1]).version' "$manifest")" || return 1
      [ "$installed_version" = "$expected_version" ] || return 1
      native_manifest="$(node -e '
        const root = process.argv[1];
        const name = `@t3code/t3-''${process.platform}-''${process.arch}`;
        try { process.stdout.write(require.resolve(name + "/package.json", { paths: [root] })); }
        catch { process.exit(1); }
      ' "$release_dir/lib/node_modules/t3")" || return 1
      native_dir="$(dirname "$native_manifest")"
      [ -x "$native_dir/t3" ] && [ -s "$native_dir/client/index.html" ]
    }

    install_t3_cli() {
      local expected_version native_package release_root release_dir current_release
      local stage_dir install_output staged_version previous_release current_tmp
      if ! expected_version="$(latest_agent_version t3)"; then
        return 1
      fi
      case "$expected_version" in
        ""|*[!a-zA-Z0-9._-]*)
          log_warn "the registry returned an invalid T3 Code version"
          return 1
          ;;
      esac
      native_package="$(node -p '"@t3code/t3-" + process.platform + "-" + process.arch')"

      release_root="$XDG_DATA_HOME/t3code-tools/t3"
      release_dir="$release_root/releases/$expected_version"
      mkdir -p "$release_root/releases"
      current_release="$(readlink -e "$release_root/current" || true)"
      case "$current_release" in
        "$release_root"/releases/*)
          if verify_t3_release "$current_release" "$expected_version"; then
            release_dir="$current_release"
          fi
          ;;
      esac
      if [ -e "$release_dir" ] && ! verify_t3_release "$release_dir" "$expected_version"; then
        log_warn "existing T3 Code release is incomplete; preserving it for running processes"
        release_dir="$release_root/releases/$expected_version-repair-$(date -u +%Y%m%dT%H%M%S%N)"
      fi
      if [ ! -e "$release_dir" ]; then
        stage_dir="$(mktemp -d "$release_root/.staging.XXXXXX")"
        log_info "staging T3 Code $expected_version without replacing the running release"
        # npm can report success while silently skipping the optional native
        # payload. Install it explicitly and verify the browser bundle below.
        if ! install_output="$(npm install -g --prefix "$stage_dir" \
          --prefer-online --no-fund --no-audit \
          "t3@$expected_version" "$native_package@$expected_version" 2>&1)"; then
          log_warn "T3 Code install failed"
          if [ -n "$install_output" ]; then
            printf '%s\n' "$install_output" >&2
          fi
          rm -rf "$stage_dir"
          return 1
        fi
        if ! verify_t3_release "$stage_dir" "$expected_version"; then
          log_warn "T3 Code release is missing its executable or web client"
          rm -rf "$stage_dir"
          return 1
        fi
        if ! staged_version="$(LD_LIBRARY_PATH='${lib.makeLibraryPath [ pkgs.stdenv.cc.cc.lib ]}' "$stage_dir/bin/t3" --version)" \
          || [ "$staged_version" != "t3 v$expected_version" ]; then
          log_warn "staged T3 Code executable did not report $expected_version"
          rm -rf "$stage_dir"
          return 1
        fi
        mv "$stage_dir" "$release_dir"
        if ! verify_t3_release "$release_dir" "$expected_version"; then
          log_warn "promoted T3 Code release is incomplete"
          return 1
        fi
      fi

      previous_release="$(readlink -e "$release_root/current" || true)"
      current_tmp="$release_root/.current.new"
      rm -f "$current_tmp"
      ln -s "$release_dir" "$current_tmp"
      mv -Tf "$current_tmp" "$release_root/current"
      if [ "$previous_release" != "$release_dir" ]; then
        printf '%s\n' "$release_dir" > "$release_root/activation.pending"
      fi
      log_info "T3 Code $expected_version is ready; older releases remain available to running servers"
    }

    install_cursor_cli() {
      log_info "installing or upgrading cursor agent"
      if ! curl -fsSL https://cursor.com/install | bash 2>&1; then
        log_warn "cursor install failed"
        return 1
      fi
      # Remove cursor installer's takeover of ~/.local/bin/agent to protect Ghostship agent CLI
      if [ -L "$HOME/.local/bin/agent" ]; then
        agent_target="$(readlink "$HOME/.local/bin/agent" || true)"
        if case "$agent_target" in *cursor-agent*) true;; *) false;; esac; then
          rm -f "$HOME/.local/bin/agent"
        fi
      fi
      for version_dir in "$HOME/.local/share/cursor-agent/versions"/*; do
        if [ -d "$version_dir" ]; then
          ln -sf "$(command -v node)" "$version_dir/node"
        fi
      done
      ln -sf "$HOME/.local/bin/cursor-agent" "$HOME/.local/bin/cursor"
      return 0
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
        log_warn "$platform_package binary is missing"
        return 1
      fi

      loader="$(find_nix_glibc_loader || true)"

      rm -f "$NPM_CONFIG_PREFIX/bin/opencode"
      cat > "$NPM_CONFIG_PREFIX/bin/opencode" <<EOF
    #!/usr/bin/env sh
    set -eu
    ${sourceHmSessionVarsIfPresent}
    fallback_bin='$fallback_bin'
    loader='$loader'
    if [ -n "\$loader" ]; then
      exec "\$loader" --library-path "\''${loader%/*}" "\$fallback_bin" "\$@"
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
          return 1
          ;;
      esac

      if ! platform_output="$(npm install -g --no-fund --no-audit "$platform_package@latest" 2>&1)"; then
        log_warn "$platform_package install failed"
        if [ -n "$platform_output" ]; then
          printf '%s\n' "$platform_output" >&2
        fi
        return 1
      fi

      if [ -n "$platform_output" ]; then
        printf '%s\n' "$platform_output" >&2
      fi

      install_opencode_platform_wrapper "$platform_package"
    }

    install_user_shim() {
      name="$1"
      target="$2"
      temporary="$HOME/.local/bin/.$name.tmp.$$"

      cat > "$temporary" <<EOF
    #!/usr/bin/env sh
    set -eu
    target='$target'
    if [ ! -x "\$target" ]; then
      printf 'error: %s is not installed yet; run t3code-tool-maintenance\n' "$name" >&2
      exit 1
    fi
    exec "\$target" "\$@"
      EOF
      chmod 0755 "$temporary"
      mv -f "$temporary" "$HOME/.local/bin/$name"
    }

    install_opencode_user_shim() {
      target="$1"
      temporary="$HOME/.local/bin/.opencode.tmp.$$"

      cat > "$temporary" <<EOF
    #!/usr/bin/env sh
    set -eu
    ${sourceHmSessionVarsIfPresent}
    target='$target'
    if [ ! -x "\$target" ]; then
      printf 'error: opencode is not installed yet; run t3code-tool-maintenance\n' >&2
      exit 1
    fi
    exec "\$target" "\$@"
      EOF
      chmod 0755 "$temporary"
      mv -f "$temporary" "$HOME/.local/bin/opencode"
    }

    mkdir -p "$HOME/.local/bin" "$XDG_CONFIG_HOME" "$XDG_STATE_HOME" "$XDG_CACHE_HOME" "$XDG_DATA_HOME" "$NPM_CONFIG_PREFIX/bin" "$NPM_CONFIG_PREFIX/lib"

    update_status=0
    install_t3_cli || update_status=1
    install_agent_cli "@openai/codex" "codex" || update_status=1
    ${t3codeCodexRgRepair}/bin/t3code-codex-rg-repair || update_status=1
    install_agent_cli "@anthropic-ai/claude-code" "claude" || update_status=1
    install_opencode_cli || update_status=1
    install_cursor_cli || update_status=1
    ${t3codeInstallT3Shim}/bin/t3code-install-t3-shim
    install_user_shim "codex" "$NPM_CONFIG_PREFIX/bin/codex"
    install_user_shim "claude" "$NPM_CONFIG_PREFIX/bin/claude"
    install_opencode_user_shim "$NPM_CONFIG_PREFIX/bin/opencode"
    ${t3codeAntigravityUpdate}/bin/t3code-antigravity-update || update_status=1
    exit "$update_status"
  '';

  t3codeToolAutoUpdate = pkgs.writeShellScriptBin "t3code-tool-auto-update" ''
    set -eu

    ${t3codeRuntimeEnv}
    export NODE_NO_WARNINGS=1

    state_dir="/run/t3code-tool-update"
    pending_restart="$state_dir/restart.pending"
    deferred_update="$state_dir/update-deferred.pending"
    install -d -m 0700 "$state_dir"

    exec 9>"$state_dir/tool-update.lock"
    ${pkgs.util-linux}/bin/flock 9

    log_info() {
      printf 'info: %s\n' "$1" >&2
    }

    ${t3codeIdleCheck}

    if systemctl is-active --quiet t3code-server.service && ! is_t3code_idle; then
      touch "$deferred_update"
      log_info "T3 Code reports active or unknown work; tool update deferred"
      exit 0
    fi
    rm -f "$deferred_update"

    user_version() {
      tool="$1"
      su-exec t3code:t3code sh -c '
        tool="$1"
        tool_path="$(command -v "$tool" 2>/dev/null || true)"
        if [ -z "$tool_path" ]; then
          exit 0
        fi
        version_status=0
        version_output="$(${pkgs.coreutils}/bin/timeout --kill-after=3s 15s "$tool_path" --version 2>/dev/null)" || version_status=$?
        if [ "$version_status" -ne 0 ]; then
          printf "unavailable:%s\n" "$version_status"
          exit 0
        fi
        printf "%s\n" "$version_output" | sed -n "1p"
      ' sh "$tool"
    }

    before_t3="$(user_version t3)"
    t3_activation_pending="$XDG_DATA_HOME/t3code-tools/t3/activation.pending"
    before_t3_release="$(readlink -e "$XDG_DATA_HOME/t3code-tools/t3/current" || true)"
    before_codex="$(user_version codex)"
    before_claude="$(user_version claude)"
    before_cursor="$(user_version cursor)"
    before_opencode="$(user_version opencode)"
    before_antigravity="$(readlink -e "$XDG_DATA_HOME/t3code-tools/antigravity/current" || true)"
    before_agent="$(readlink -e "$HOME/.local/state/t3code-agent-tools-package" || true)"
    before_config="$(${pkgs.coreutils}/bin/sha256sum "$T3CODE_HOME/userdata/settings.json" 2>/dev/null || true)"

    maintenance_status=0
    su-exec t3code:t3code ${t3codeToolMaintenance}/bin/t3code-tool-maintenance || maintenance_status=$?
    su-exec t3code:t3code ${t3codeManagedConfig}/bin/t3code-managed-config
    su-exec t3code:t3code ${t3codeRunHooks}/bin/t3code-run-hooks after-update.d

    after_t3="$(user_version t3)"
    after_t3_release="$(readlink -e "$XDG_DATA_HOME/t3code-tools/t3/current" || true)"
    after_codex="$(user_version codex)"
    after_claude="$(user_version claude)"
    after_cursor="$(user_version cursor)"
    after_opencode="$(user_version opencode)"
    after_antigravity="$(readlink -e "$XDG_DATA_HOME/t3code-tools/antigravity/current" || true)"
    after_agent="$(readlink -e "$HOME/.local/state/t3code-agent-tools-package" || true)"
    after_config="$(${pkgs.coreutils}/bin/sha256sum "$T3CODE_HOME/userdata/settings.json" 2>/dev/null || true)"

    log_info "t3: ''${before_t3:-missing} -> ''${after_t3:-missing}"
    log_info "codex: ''${before_codex:-missing} -> ''${after_codex:-missing}"
    log_info "claude: ''${before_claude:-missing} -> ''${after_claude:-missing}"
    log_info "cursor: ''${before_cursor:-missing} -> ''${after_cursor:-missing}"
    log_info "opencode: ''${before_opencode:-missing} -> ''${after_opencode:-missing}"
    log_info "antigravity: ''${before_antigravity:-bundled} -> ''${after_antigravity:-bundled}"

    if [ -f "$t3_activation_pending" ] \
      || [ "$before_t3" != "$after_t3" ] \
      || [ "$before_t3_release" != "$after_t3_release" ] \
      || [ "$before_codex" != "$after_codex" ] \
      || [ "$before_claude" != "$after_claude" ] \
      || [ "$before_cursor" != "$after_cursor" ] \
      || [ "$before_opencode" != "$after_opencode" ] \
      || [ "$before_antigravity" != "$after_antigravity" ] \
      || [ "$before_agent" != "$after_agent" ] \
      || [ "$before_config" != "$after_config" ]; then
      pending_tmp="$pending_restart.tmp"
      {
        printf 't3=%s\n' "$after_t3"
        printf 'codex=%s\n' "$after_codex"
        printf 'claude=%s\n' "$after_claude"
        printf 'cursor=%s\n' "$after_cursor"
        printf 'opencode=%s\n' "$after_opencode"
        printf 'antigravity=%s\n' "$after_antigravity"
      } > "$pending_tmp"
      mv "$pending_tmp" "$pending_restart"
      log_info "tool update downloaded; queued restart until T3 Code is idle"
    else
      log_info "installed tool versions are unchanged"
    fi
    exit "$maintenance_status"
  '';

  t3codeToolUpdateRestart = pkgs.writeShellScriptBin "t3code-tool-update-restart" ''
    set -eu

    ${t3codeRuntimeEnv}

    state_dir="/run/t3code-tool-update"
    pending_restart="$state_dir/restart.pending"
    deferred_update="$state_dir/update-deferred.pending"
    t3_activation_pending="$XDG_DATA_HOME/t3code-tools/t3/activation.pending"

    log_info() {
      printf 'info: %s\n' "$1" >&2
    }

    ${t3codeIdleCheck}

    [ -f "$pending_restart" ] || [ -f "$deferred_update" ] || [ -f "$t3_activation_pending" ] || exit 0

    exec 9>"$state_dir/tool-update.lock"
    if ! ${pkgs.util-linux}/bin/flock -n 9; then
      log_info "tool maintenance is still running; leaving restart queued"
      exit 0
    fi

    if ! systemctl is-active --quiet t3code-server.service; then
      log_info "t3code-server.service is stopped; the next start will use staged tools"
      rm -f "$pending_restart" "$deferred_update" "$t3_activation_pending"
      exit 0
    fi

    if [ ! -f "$pending_restart" ] \
      && { [ -f "$deferred_update" ] || [ -f "$t3_activation_pending" ]; }; then
      if ! is_t3code_idle; then
        touch "$deferred_update"
        log_info "T3 Code reports active or unknown work; leaving tool update queued"
        exit 0
      fi
      rm -f "$deferred_update"
      ${pkgs.util-linux}/bin/flock -u 9
      log_info "T3 Code became idle; retrying deferred tool update"
      systemctl start t3code-tool-auto-update.service
      exit 0
    fi

    if ! is_t3code_idle; then
      log_info "T3 Code reports active or unknown work; leaving restart queued"
      exit 0
    fi

    sleep 5

    if [ ! -f "$pending_restart" ]; then
      log_info "queued restart was already applied by another service start"
      exit 0
    fi

    if ! is_t3code_idle; then
      log_info "T3 Code is no longer idle; leaving restart queued"
      exit 0
    fi

    log_info "T3 Code reports all work complete; applying queued maintenance restart"
    systemctl restart t3code-server.service
    rm -f "$pending_restart"
    rm -f "$t3_activation_pending"
  '';

  t3codeDaemonMonitor = pkgs.writeShellScriptBin "t3code-server-monitor" ''
    set -eu

    ${t3codeRuntimeEnv}

    log_file="$HOME/.t3code-container/logs/t3code-server-monitor.log"
    mkdir -p "$(dirname "$log_file")"

    log_info() {
      printf '%s info: %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$1" >> "$log_file"
    }

    ${t3codeIdleCheck}
    ${t3codeProviderCheck}

    unhealthy_reason=""
    web_was_active=1

    if ! systemctl is-active --quiet t3code-server.service; then
      unhealthy_reason="t3code-server.service is not active"
      web_was_active=0
    elif ! curl -fsS --max-time 5 -H 'Accept: text/html' http://127.0.0.1:3773/ >/dev/null; then
      unhealthy_reason="T3 Code web UI is not responding"
    elif ! curl -fsS --max-time 5 http://127.0.0.1:3773/.well-known/t3/environment >/dev/null; then
      unhealthy_reason="T3 Code environment endpoint is not responding"
    elif ! t3code_providers_healthy; then
      unhealthy_reason="Codex or OpenCode provider is unavailable"
    fi

    if [ "$web_was_active" -eq 1 ]; then
      main_pid="$(systemctl show t3code-server.service --property MainPID --value)"
      memory_reason=""
      if ! memory_reason="$(${pkgs.python3}/bin/python3 ${../../packages/t3code/memory-watchdog.py} "$main_pid" 2>> "$log_file")"; then
        log_info "memory measurement unavailable; continuing health recovery"
      elif [ -n "$memory_reason" ]; then
        if [ -n "$unhealthy_reason" ]; then
          unhealthy_reason="$unhealthy_reason; $memory_reason"
        else
          unhealthy_reason="$memory_reason"
        fi
      fi
    fi

    state_dir="/run/t3code-tool-update"
    failure_streak_file="$state_dir/server-monitor-failures"
    recovery_attempt_file="$state_dir/server-monitor-recovery-attempted"

    if [ -z "$unhealthy_reason" ]; then
      rm -f "$failure_streak_file" "$recovery_attempt_file"
      log_info "healthy"
      exit 0
    fi

    install -d -m 0700 "$state_dir"
    failure_streak=0
    if [ -r "$failure_streak_file" ]; then
      read -r failure_streak < "$failure_streak_file" || failure_streak=0
    fi
    case "$failure_streak" in
      ""|*[!0-9]*) failure_streak=0 ;;
    esac
    failure_streak=$((failure_streak + 1))
    printf '%s\n' "$failure_streak" > "$failure_streak_file.tmp"
    mv "$failure_streak_file.tmp" "$failure_streak_file"

    force_recovery=0
    # The user-facing server has failed repeatedly; allow bounded recovery to
    # interrupt a stuck generation instead of deferring an unusable server forever.
    if [ "$web_was_active" -eq 0 ] || [ "$failure_streak" -ge 5 ]; then
      force_recovery=1
    fi

    if [ -r "$recovery_attempt_file" ]; then
      attempted_at=0
      read -r attempted_at < "$recovery_attempt_file" || attempted_at=0
      case "$attempted_at" in
        ""|*[!0-9]*) attempted_at=0 ;;
      esac
      now="$(date +%s)"
      if [ "$attempted_at" -gt 0 ] && [ "$((now - attempted_at))" -lt 300 ]; then
        log_info "unhealthy: $unhealthy_reason; recovery was attempted recently; waiting for health to recover"
        exit 0
      fi
    fi

    if [ "$web_was_active" -eq 1 ] && [ "$force_recovery" -eq 0 ] && ! is_t3code_idle; then
      log_info "unhealthy: $unhealthy_reason; T3 Code activity is active or unknown; restart deferred"
      exit 0
    fi

    exec 9>"$state_dir/tool-update.lock"
    if ! ${pkgs.util-linux}/bin/flock -n 9; then
      log_info "unhealthy: $unhealthy_reason; tool maintenance or restart is in progress; restart deferred"
      exit 0
    fi

    # Recheck after acquiring the maintenance lock, close to the restart.
    if [ "$web_was_active" -eq 1 ] && [ "$force_recovery" -eq 0 ] && ! is_t3code_idle; then
      log_info "unhealthy: $unhealthy_reason; work became active or unknown; restart deferred"
      exit 0
    fi

    printf '%s\n' "$(date +%s)" > "$recovery_attempt_file.tmp"
    mv "$recovery_attempt_file.tmp" "$recovery_attempt_file"
    if [ "$force_recovery" -eq 1 ] && [ "$web_was_active" -eq 1 ]; then
      log_info "unhealthy for $failure_streak consecutive checks: $unhealthy_reason; restarting t3code-server.service despite active or unknown work"
    else
      log_info "unhealthy: $unhealthy_reason; restarting t3code-server.service"
    fi
    systemctl reset-failed t3code-server.service || true
    systemctl restart t3code-server.service
  '';

  t3codeContainerHealth = pkgs.writeShellScriptBin "t3code-container-health" ''
    set -eu

    read -r uptime _ < /proc/uptime
    uptime_seconds="''${uptime%%.*}"
    if ! manager_started_usec="$(${pkgs.systemd}/bin/systemctl show -p UserspaceTimestampMonotonic --value)"; then
      exit 0
    fi
    case "$manager_started_usec" in
      ""|*[!0-9]*)
        container_age_seconds=1200
        ;;
      *)
        container_age_seconds=$((uptime_seconds - (manager_started_usec / 1000000)))
        if [ "$container_age_seconds" -lt 0 ]; then
          container_age_seconds=1200
        fi
        ;;
    esac
    if ! setup_state="$(${pkgs.systemd}/bin/systemctl show t3code-container-setup.service -p ActiveState --value)"; then
      exit 0
    fi
    if ! bootstrap_state="$(${pkgs.systemd}/bin/systemctl show t3code-bootstrap.service -p ActiveState --value)"; then
      exit 0
    fi
    if ! web_state="$(${pkgs.systemd}/bin/systemctl show t3code-server.service -p ActiveState --value)"; then
      exit 0
    fi

    if [ "$container_age_seconds" -lt 1200 ] \
      && { [ "$setup_state" = "activating" ] \
        || [ "$bootstrap_state" = "activating" ] \
        || [ "$web_state" = "activating" ]; }; then
      exit 0
    fi

    if ${pkgs.curl}/bin/curl -fsS --max-time 5 -H 'Accept: text/html' http://127.0.0.1:3773/ >/dev/null \
      && ${pkgs.curl}/bin/curl -fsS --max-time 5 http://127.0.0.1:3773/.well-known/t3/environment >/dev/null; then
      exit 0
    fi

    printf 'error: T3 Code web or environment endpoint is unavailable\n' >&2
    exit 1
  '';

  t3codeApplyConfig = pkgs.writeShellScriptBin "t3code-apply-config" ''
    set -eu

    ${t3codeRuntimeEnv}

    recovery_dir="$HOME/.t3code-container/recovery"
    last_good="$recovery_dir/last-good"
    log_file="$HOME/.t3code-container/logs/t3code-apply-config.log"
    systemctl_bin="${pkgs.systemd}/bin/systemctl"
    sudo_bin="/usr/bin/sudo"

    mkdir -p "$recovery_dir" "$(dirname "$log_file")"

    log_info() {
      printf '%s info: %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$1" | tee -a "$log_file" >&2
    }

    log_error() {
      printf '%s error: %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$1" | tee -a "$log_file" >&2
    }

    restore_config() {
      src="$1"
      if [ ! -d "$src" ]; then
        log_error "no last-good config snapshot exists at $src"
        return 1
      fi

      rm -f \
        "$T3CODE_HOME/userdata/settings.json" \
        "$HOME/.codex/config.toml" \
        "$HOME/.config/opencode/opencode.json" \
        "$HOME/.gemini/antigravity-cli/settings.json"
      if [ -d "$src/home" ]; then
        tar -C "$src/home" -cf - . | tar -C "$HOME" -xf -
      fi
    }

    validate_config() {
      command -v t3 >/dev/null 2>&1 || {
        log_error "T3 Code CLI is not installed"
        return 1
      }
      command -v codex >/dev/null 2>&1 || {
        log_error "codex CLI is not installed"
        return 1
      }
      command -v opencode >/dev/null 2>&1 || {
        log_error "opencode CLI is not installed"
        return 1
      }

      for file in \
        "$T3CODE_HOME/userdata/settings.json" \
        "$HOME/.config/opencode/opencode.json" \
        "$HOME/.gemini/antigravity-cli/settings.json"; do
        if [ -f "$file" ] && ! jq -e . "$file" >/dev/null; then
          log_error "invalid JSON: $file"
          return 1
        fi
      done
      if [ -f "$HOME/.codex/config.toml" ] \
        && ! ${pkgs.python3}/bin/python - "$HOME/.codex/config.toml" <<'PY'
    import pathlib
    import sys
    import tomllib

    with pathlib.Path(sys.argv[1]).open("rb") as handle:
        tomllib.load(handle)
    PY
      then
        log_error "invalid TOML: $HOME/.codex/config.toml"
        return 1
      fi

      t3 --version >/dev/null
      codex --version >/dev/null
      claude --version >/dev/null || true
      cursor --version >/dev/null || true
      opencode debug config >/dev/null
    }

    restart_daemon() {
      "$sudo_bin" -n "$systemctl_bin" reset-failed t3code-server.service
      "$sudo_bin" -n "$systemctl_bin" restart t3code-server.service
    }

    ${t3codeProviderCheck}

    wait_healthy() {
      for _ in $(seq 1 90); do
        if curl -fsS --max-time 5 -H 'Accept: text/html' http://127.0.0.1:3773/ >/dev/null \
          && curl -fsS --max-time 5 http://127.0.0.1:3773/.well-known/t3/environment >/dev/null \
          && t3code_providers_healthy; then
          return 0
        fi
        sleep 1
      done
      return 1
    }

    apply_config() {
      log_info "validating T3 Code, Codex, OpenCode, and Antigravity config"
      validate_config

      if [ ! -d "$last_good" ]; then
        log_error "no last-good config snapshot exists; wait for t3code-server.service to start successfully once"
        exit 1
      fi

      log_info "restarting t3code-server.service"
      restart_daemon

      if wait_healthy; then
        log_info "T3 Code providers are healthy"
        exit 0
      fi

      log_error "T3 Code providers did not become healthy; restoring last-good config"
      restore_config "$last_good"
      validate_config
      restart_daemon

      if wait_healthy; then
        log_info "rollback restored a healthy T3 Code runtime"
        exit 1
      fi

      log_error "rollback did not restore a healthy T3 Code runtime"
      exit 1
    }

    case "''${1:-apply}" in
      apply) apply_config ;;
      *)
        printf 'usage: t3code-apply-config [apply]\n' >&2
        exit 2
        ;;
    esac
  '';

  t3codeUserUnits = pkgs.writeShellScriptBin "t3code-user-units" ''
    set -eu

    ${t3codeRuntimeEnv}

    usage() {
      cat >&2 <<EOF
    usage:
      t3code-user-units reload
      t3code-user-units enable-now <unit>...
      t3code-user-units disable-now <unit>...
      t3code-user-units restart <unit>...
      t3code-user-units status <unit>...
      t3code-user-units list-timers
    EOF
      exit 2
    }

    systemctl_user() {
      systemctl --user "$@"
    }

    [ "$#" -ge 1 ] || usage
    command="$1"
    shift

    case "$command" in
      reload)
        [ "$#" -eq 0 ] || usage
        systemctl_user daemon-reload
        ;;
      enable-now)
        [ "$#" -ge 1 ] || usage
        systemctl_user daemon-reload
        systemctl_user enable --now "$@"
        ;;
      disable-now)
        [ "$#" -ge 1 ] || usage
        systemctl_user disable --now "$@"
        systemctl_user daemon-reload
        ;;
      restart)
        [ "$#" -ge 1 ] || usage
        systemctl_user daemon-reload
        systemctl_user restart "$@"
        ;;
      status)
        [ "$#" -ge 1 ] || usage
        systemctl_user status --no-pager "$@"
        ;;
      list-timers)
        [ "$#" -eq 0 ] || usage
        systemctl_user list-timers --all --no-pager
        ;;
      *)
        usage
        ;;
    esac
  '';

  t3codeRunHooks = pkgs.writeShellScriptBin "t3code-run-hooks" ''
    set -eu

    hook_set="''${1:-}"
    if [ -z "$hook_set" ]; then
      printf 'usage: t3code-run-hooks <hook-set>\n' >&2
      exit 2
    fi

    ${t3codeRuntimeEnv}
    export T3CODE_HOOK_SET="$hook_set"

    hook_dir="$HOME/.t3code-container/hooks/$hook_set"
    log_file="$HOME/.t3code-container/logs/t3code-hooks.log"
    mkdir -p "$(dirname "$log_file")" "$hook_dir"

    log_info() {
      printf '%s %s: %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$hook_set" "$1" >> "$log_file"
    }

    if [ ! -d "$hook_dir" ]; then
      log_info "missing hook directory; skipping"
      exit 0
    fi

    found=0
    for hook in "$hook_dir"/*; do
      if [ ! -f "$hook" ] || [ ! -x "$hook" ]; then
        continue
      fi

      found=1
      log_info "running $(basename "$hook")"
      if "$hook" >> "$log_file" 2>&1; then
        log_info "completed $(basename "$hook")"
      else
        hook_status="$?"
        log_info "failed $(basename "$hook") with status $hook_status; continuing"
      fi
    done

    if [ "$found" -eq 0 ]; then
      log_info "no executable hooks"
    fi
  '';

  t3codeDoctor = pkgs.writeShellScriptBin "t3code-doctor" ''
    set -eu

    ${t3codeRuntimeEnv}

    su-exec t3code:t3code ${t3codeToolMaintenance}/bin/t3code-tool-maintenance
    su-exec t3code:t3code ${t3codeRunHooks}/bin/t3code-run-hooks doctor.d
  '';

  t3codeSharedAgents = pkgs.writeShellScriptBin "t3code-shared-agents" ''
    set -eu
    ${t3codeRuntimeEnv}
    exec ${pkgs.python3}/bin/python ${../../scripts/setup-container-agents.py} \
      "$@"
  '';

  t3codeBootstrap = pkgs.writeShellScriptBin "t3code-bootstrap" ''
    set -eu

    ${t3codeRuntimeEnv}

    if [ -d /workspace/ghostship-agent/skills ]; then
      if ! ${t3codeSharedAgents}/bin/t3code-shared-agents --skills-only; then
        printf 'warning: shared agent setup needs attention; preserving provider startup\n' >&2
      fi
    fi
    ${t3codeRunHooks}/bin/t3code-run-hooks bootstrap.d
  '';

  t3codeSnapshotConfig = pkgs.writeShellScriptBin "t3code-snapshot-config" ''
    set -eu

    ${t3codeRuntimeEnv}

    recovery_dir="$HOME/.t3code-container/recovery"
    last_good="$recovery_dir/last-good"
    tmp="$recovery_dir/last-good.tmp"

    mkdir -p "$recovery_dir"
    rm -rf "$tmp"
    mkdir -p "$tmp"

    ${t3codeProviderCheck}
    for _ in $(seq 1 90); do
      if curl -fsS --max-time 5 -H 'Accept: text/html' http://127.0.0.1:3774/ >/dev/null \
        && curl -fsS --max-time 5 http://127.0.0.1:3774/.well-known/t3/environment >/dev/null \
        && t3code_providers_healthy; then
        break
      fi
      sleep 1
    done
    curl -fsS --max-time 5 -H 'Accept: text/html' http://127.0.0.1:3774/ >/dev/null
    curl -fsS --max-time 5 http://127.0.0.1:3774/.well-known/t3/environment >/dev/null
    t3code_providers_healthy

    mkdir -p "$tmp/home"
    for relative in \
      .t3/userdata/settings.json \
      .codex/config.toml \
      .config/opencode/opencode.json \
      .gemini/antigravity-cli/settings.json; do
      if [ -f "$HOME/$relative" ]; then
        mkdir -p "$tmp/home/$(dirname "$relative")"
        cp -a "$HOME/$relative" "$tmp/home/$relative"
      fi
    done

    rm -rf "$last_good"
    mv "$tmp" "$last_good"
  '';

  t3codeTunnel = pkgs.writeShellScriptBin "t3code-tunnel" ''
    set -eu

    ${t3codeRuntimeEnv}

    tunnel_dir="$HOME/.t3code-container/tunnels"
    unit_dir="$HOME/.config/systemd/user"
    log_dir="$HOME/.t3code-container/logs/tunnels"

    usage() {
      cat >&2 <<EOF
    usage:
      t3code-tunnel start <name> <port>
      t3code-tunnel stop <name>
      t3code-tunnel restart <name> <port>
      t3code-tunnel status <name>
      t3code-tunnel url <name>
      t3code-tunnel list
      t3code-tunnel remove <name>
    EOF
      exit 2
    }

    ensure_state() {
      mkdir -p "$tunnel_dir" "$unit_dir" "$log_dir"
    }

    validate_name() {
      name="$1"
      case "$name" in
        ""|"-"*|*"-"|*[!a-z0-9-]*)
          printf 'error: name must be a lowercase DNS label using a-z, 0-9, and hyphen\n' >&2
          exit 2
          ;;
      esac
      if [ "''${#name}" -gt 63 ]; then
        printf 'error: name must be 63 characters or fewer\n' >&2
        exit 2
      fi
    }

    validate_port() {
      case "$1" in
        ""|*[!0-9]*)
          printf 'error: port must be numeric\n' >&2
          exit 2
          ;;
      esac
      if [ "$1" -lt 1 ] || [ "$1" -gt 65535 ]; then
        printf 'error: port must be between 1 and 65535\n' >&2
        exit 2
      fi
    }

    unit_name() {
      printf 't3code-tunnel-%s.service' "$1"
    }

    unit_path() {
      printf '%s/%s' "$unit_dir" "$(unit_name "$1")"
    }

    log_path() {
      printf '%s/%s.log' "$log_dir" "$1"
    }

    write_unit() {
      name="$1"
      port="$2"
      ensure_state
      validate_name "$name"
      validate_port "$port"
      log_file="$(log_path "$name")"
      cat > "$(unit_path "$name")" <<EOF
    [Unit]
    Description=T3 Code quick tunnel: $name
    After=default.target

    [Service]
    Type=simple
    ExecStart=${pkgs.cloudflared}/bin/cloudflared tunnel --no-autoupdate --url http://127.0.0.1:$port
    Restart=always
    RestartSec=5
    StandardOutput=append:$log_file
    StandardError=append:$log_file

    [Install]
    WantedBy=default.target
    EOF
      printf '%s\t%s\n' "$name" "$port" > "$tunnel_dir/$name.tsv"
    }

    systemctl_user() {
      systemctl --user "$@"
    }

    start_tunnel() {
      [ "$#" -eq 2 ] || usage
      name="$1"
      port="$2"
      write_unit "$name" "$port"
      systemctl_user daemon-reload
      systemctl_user enable --now "$(unit_name "$name")"
      printf 'started %s for http://127.0.0.1:%s\n' "$name" "$port"
      printf 'logs: %s\n' "$(log_path "$name")"
    }

    stop_tunnel() {
      [ "$#" -eq 1 ] || usage
      name="$1"
      validate_name "$name"
      systemctl_user stop "$(unit_name "$name")" || true
    }

    restart_tunnel() {
      [ "$#" -eq 2 ] || usage
      stop_tunnel "$1"
      start_tunnel "$1" "$2"
    }

    status_tunnel() {
      [ "$#" -eq 1 ] || usage
      name="$1"
      validate_name "$name"
      systemctl_user status --no-pager "$(unit_name "$name")"
    }

    url_tunnel() {
      [ "$#" -eq 1 ] || usage
      name="$1"
      validate_name "$name"
      log_file="$(log_path "$name")"
      if [ ! -f "$log_file" ]; then
        printf 'error: no log file for tunnel %s\n' "$name" >&2
        exit 1
      fi
      url="$(grep -Eo 'https://[-a-zA-Z0-9.]+\\.trycloudflare\\.com' "$log_file" | tail -n 1 || true)"
      if [ -z "$url" ]; then
        printf 'error: no quick tunnel URL found yet for %s\n' "$name" >&2
        exit 1
      fi
      printf '%s\n' "$url"
    }

    list_tunnels() {
      [ "$#" -eq 0 ] || usage
      ensure_state
      found=0
      for entry in "$tunnel_dir"/*.tsv; do
        [ -f "$entry" ] || continue
        found=1
        IFS="$(printf '\t')" read -r name port < "$entry"
        state="$(systemctl_user is-active "$(unit_name "$name")" 2>/dev/null || true)"
        printf '%s\t%s\t%s' "$name" "$port" "$state"
        if url="$(t3code-tunnel url "$name" 2>/dev/null)"; then
          printf '\t%s' "$url"
        fi
        printf '\n'
      done
      [ "$found" -eq 1 ] || true
    }

    remove_tunnel() {
      [ "$#" -eq 1 ] || usage
      name="$1"
      validate_name "$name"
      systemctl_user disable --now "$(unit_name "$name")" || true
      rm -f "$(unit_path "$name")" "$tunnel_dir/$name.tsv"
      systemctl_user daemon-reload
    }

    [ "$#" -ge 1 ] || usage
    command="$1"
    shift
    case "$command" in
      start) start_tunnel "$@" ;;
      stop) stop_tunnel "$@" ;;
      restart) restart_tunnel "$@" ;;
      status) status_tunnel "$@" ;;
      url) url_tunnel "$@" ;;
      list|ls) list_tunnels "$@" ;;
      remove|rm|delete) remove_tunnel "$@" ;;
      *) usage ;;
    esac
  '';

  t3codeDaemonRun = pkgs.writeShellScriptBin "t3code-server-run" ''
    set -eu

    ${t3codeRuntimeEnv}
    export T3CODE_NODE_EXECUTABLE=${pkgs.nodejs_24}/bin/node
    export NODE_OPTIONS="--require=${../../packages/t3code/t3-runtime-preload.cjs}"
    export XDG_RUNTIME_DIR=/run/user/3000
    cd /workspace

    exec t3 serve \
      --host "$T3CODE_HOST" \
      --port "$T3CODE_PORT" \
      --base-dir "$T3CODE_HOME" \
      /workspace
  '';

  t3codeAccessProxy = pkgs.writeShellScriptBin "t3code-access-proxy" ''
    set -eu
    ${t3codeRuntimeEnv}
    exec ${pkgs.nodejs_24}/bin/node ${../../packages/t3code}/access-proxy.cjs
  '';

  t3codeManagedConfig = pkgs.writeShellScriptBin "t3code-managed-config" ''
    set -eu
    ${t3codeRuntimeEnv}
    config_dir="$T3CODE_HOME/userdata"
    config_file="$config_dir/settings.json"
    [ ! -f "$config_file" ] || exit 0
    mkdir -p "$config_dir"
    config_tmp="$(mktemp "$config_dir/settings.json.tmp.XXXXXX")"
    trap 'rm -f "$config_tmp"' EXIT
    cat > "$config_tmp" <<'JSON'
    {
      "providerInstances": {
        "codex": {"driver": "codex", "enabled": true, "config": {"binaryPath": "codex"}},
        "opencode": {"driver": "opencode", "enabled": true, "config": {"binaryPath": "opencode"}},
        "antigravity": {"driver": "antigravity", "enabled": true, "config": {"binaryPath": "/bin/agy_acp_server.par"}}
      }
    }
    JSON
    chmod 0600 "$config_tmp"
    mv "$config_tmp" "$config_file"
  '';

  t3codeProjectBootstrap = pkgs.writeShellScriptBin "t3code-project-bootstrap" ''
    set -eu

    ${t3codeRuntimeEnv}

    for repo_dir in /workspace/*; do
      [ -e "$repo_dir/.git" ] || continue
      repo_name="$(basename "$repo_dir")"
      if ! output="$(t3 project add \
        --base-dir "$T3CODE_HOME" \
        --title "$repo_name" \
        "$repo_dir" 2>&1)"; then
        # The CLI reports duplicates as errors; all other failures block setup.
        case "$output" in
          *ProjectAlreadyExistsError*) ;;
          *) printf '%s\n' "$output" >&2; exit 1 ;;
        esac
      fi
    done
  '';

  t3codeContainerSetup = pkgs.writeShellScriptBin "t3code-container-setup" ''
    set -eu

    ${t3codeRuntimeEnv}

    mkdir -p \
      "$HOME/.local/bin" \
      "$NPM_CONFIG_PREFIX/bin" \
      "$NPM_CONFIG_PREFIX/lib" \
      "$XDG_DATA_HOME" \
      "$XDG_STATE_HOME" \
      "$XDG_CACHE_HOME" \
      "$T3CODE_HOME/userdata" \
      "$T3CODE_HOME/caches" \
      "$HOME/.t3code-container/logs" \
      "$HOME/.t3code-container/recovery" \
      "$HOME/.t3code-container/tunnels" \
      "$HOME/.t3code-container/logs/tunnels" \
      "$HOME/.t3code-container/hooks/bootstrap.d" \
      "$HOME/.t3code-container/hooks/before-t3code.d" \
      "$HOME/.t3code-container/hooks/doctor.d" \
      "$HOME/.t3code-container/hooks/after-update.d" \
      "$HOME/.codex" \
      "$HOME/.gemini/antigravity-cli" \
      "$HOME/.local/share/keyrings" \
      "$HOME/.config/opencode" \
      "$HOME/.automation" \
      "$HOME/.config/systemd/user" \
      /workspace \
      /mnt/share \
      /var/lib/docker \
      /var/run \
      /tmp \
      /run/user/3000
    chown -R t3code:t3code \
      "$HOME/.local" \
      "$HOME/.config" \
      "$HOME/.cache" \
      "$HOME/.automation" \
      "$T3CODE_HOME" \
      "$HOME/.t3code-container" \
      "$HOME/.codex" \
      "$HOME/.gemini" \
      "$HOME/.local/share/keyrings" \
      "$HOME/.config/systemd"
    chown t3code:t3code /run/user/3000
    chmod 0700 /run/user/3000
    su-exec t3code:t3code ${t3codeManagedConfig}/bin/t3code-managed-config
    ln -sfn ${../../docs/t3code.md} "$HOME/.t3code-container/README.md"
    chown -h t3code:t3code "$HOME/.t3code-container/README.md"
    for hook_set in bootstrap.d before-t3code.d doctor.d after-update.d; do
      hook="$HOME/.t3code-container/hooks/$hook_set/40-ghostship-agent-install"
      cat > "$hook" <<'EOF'
    #!/bin/sh
    exec ${t3codeInstallGhostshipAgent}/bin/t3code-install-ghostship-agent "$@"
    EOF
      chmod 0755 "$hook"
      chown t3code:t3code "$hook"
    done
    if [ ! -e "$HOME/tools" ] && [ -d /workspace/ghostship-agent/tools ]; then
      ln -s /workspace/ghostship-agent/tools "$HOME/tools"
      chown -h t3code:t3code "$HOME/tools"
    fi
    for tool in agent ghostship-cloakbrowser; do
      if [ -x "$HOME/tools/bin/$tool" ]; then
        ln -sfn "$HOME/tools/bin/$tool" "$HOME/.local/bin/$tool"
        chown -h t3code:t3code "$HOME/.local/bin/$tool"
      fi
    done
    current_t3_release="$(readlink -e "$XDG_DATA_HOME/t3code-tools/t3/current" || true)"
    case "$current_t3_release" in
      "$XDG_DATA_HOME"/t3code-tools/t3/releases/*) ;;
      *) current_t3_release="" ;;
    esac
    if [ -z "$current_t3_release" ] \
      || [ ! -x "$current_t3_release/bin/t3" ] \
      || [ ! -x "$NPM_CONFIG_PREFIX/bin/codex" ] \
      || [ ! -x "$NPM_CONFIG_PREFIX/bin/opencode" ]; then
      if ! su-exec t3code:t3code ${t3codeToolMaintenance}/bin/t3code-tool-maintenance; then
        # Optional ACP updates must not block startup with the bundled runtime.
        test -x "$XDG_DATA_HOME/t3code-tools/t3/current/bin/t3" \
          || test -x "$NPM_CONFIG_PREFIX/bin/t3" || exit 1
        for tool in codex opencode; do
          test -x "$NPM_CONFIG_PREFIX/bin/$tool" || exit 1
        done
        printf 'warning: some updates failed; starting with installed tools\n' >&2
      fi
    fi
    su-exec t3code:t3code ${t3codeInstallT3Shim}/bin/t3code-install-t3-shim
    su-exec t3code:t3code ${t3codeCodexRgRepair}/bin/t3code-codex-rg-repair
    su-exec t3code:t3code ${t3codeProjectBootstrap}/bin/t3code-project-bootstrap
    cat > "$HOME/.local/bin/t3code-server-run" <<'EOF'
    #!/bin/sh
    exec ${t3codeDaemonRun}/bin/t3code-server-run "$@"
    EOF
    chown t3code:t3code "$HOME/.local/bin/t3code-server-run"
    chmod 0755 "$HOME/.local/bin/t3code-server-run"
    rm -f "$HOME/.local/bin/t3code-pair"
    cat > "$HOME/.local/bin/t3code-tunnel" <<'EOF'
    #!/bin/sh
    exec ${t3codeTunnel}/bin/t3code-tunnel "$@"
    EOF
    chown t3code:t3code "$HOME/.local/bin/t3code-tunnel"
    chmod 0755 "$HOME/.local/bin/t3code-tunnel"
    cat > "$HOME/.local/bin/t3code-user-units" <<'EOF'
    #!/bin/sh
    exec ${t3codeUserUnits}/bin/t3code-user-units "$@"
    EOF
    chown t3code:t3code "$HOME/.local/bin/t3code-user-units"
    chmod 0755 "$HOME/.local/bin/t3code-user-units"
    cat > "$HOME/.local/bin/t3code-apply-config" <<'EOF'
    #!/bin/sh
    exec ${t3codeApplyConfig}/bin/t3code-apply-config "$@"
    EOF
    chown t3code:t3code "$HOME/.local/bin/t3code-apply-config"
    chmod 0755 "$HOME/.local/bin/t3code-apply-config"

  '';

  t3codeDockerdRun = pkgs.writeShellScriptBin "t3code-dockerd-run" ''
    set -eu

    ${t3codeRuntimeEnv}

    rm -f /var/run/docker.pid
    exec dockerd \
      --host=unix:///var/run/docker.sock \
      --group=t3code \
      --data-root=/var/lib/docker \
      --storage-driver=vfs \
      --iptables=false \
      --ip-masq=false \
      --bridge=none
  '';

  t3codeEntrypoint = pkgs.writeShellScriptBin "t3code-systemd-entrypoint" ''
    set -eu

    exec ${pkgs.systemd}/lib/systemd/systemd
  '';

  t3codeImageContents = t3codePackages ++ [
    antigravityAcp
    t3codeEntrypoint
    t3codeContainerSetup
    t3codeDockerdRun
    t3codeDaemonRun
    t3codeAccessProxy
    t3codeProjectBootstrap
    t3codeToolMaintenance
    t3codeInstallT3Shim
    t3codeAntigravityUpdate
    t3codeInstallGhostshipAgent
    t3codeToolAutoUpdate
    t3codeToolUpdateRestart
    t3codeDaemonMonitor
    t3codeContainerHealth
    t3codeRunHooks
    t3codeSharedAgents
    t3codeDoctor
    t3codeApplyConfig
    t3codeUserUnits
    t3codeBootstrap
    t3codeSnapshotConfig
    t3codeTunnel
    pkgs.dockerTools.binSh
    pkgs.dockerTools.usrBinEnv
    pkgs.dockerTools.caCertificates
  ];

  t3codeImage = pkgs.dockerTools.buildLayeredImageWithNixDb {
    name = imageName;
    tag = imageTag;
    contents = t3codeImageContents;
    extraCommands = ''
      mkdir -p etc/nix etc/pam.d etc/sudoers.d etc/systemd/system/multi-user.target.wants etc/systemd/user/sockets.target.wants usr/bin usr/share/systemd/user nix/store nix/var/log/nix nix/var/nix tmp workspace home/t3code
      mkdir -p mnt/share run/user var/empty var/lib/docker var/log/journal var/run
      mkdir -p lib lib64
      ln -s ${pkgs.stdenv.cc.bintools.dynamicLinker} lib/$(basename ${pkgs.stdenv.cc.bintools.dynamicLinker})
      ln -s ${pkgs.stdenv.cc.bintools.dynamicLinker} lib64/$(basename ${pkgs.stdenv.cc.bintools.dynamicLinker})
      chmod 1777 tmp
      chmod 0555 var/empty
      cp ${pkgs.sudo}/bin/sudo usr/bin/sudo
      chmod 0755 usr/bin/sudo
      cat > etc/passwd <<'EOF'
      root:x:0:0:root:/root:/bin/sh
      nobody:x:65534:65534:Unprivileged:/var/empty:/bin/sh
      t3code:x:3000:3000:T3 Code:/home/t3code:/bin/sh
      EOF
      cat > etc/group <<'EOF'
      root:x:0:
      nobody:x:65534:
      t3code:x:3000:
      EOF
      nixbld_members=""
      nixbld_index=1
      while [ "$nixbld_index" -le 32 ]; do
        printf 'nixbld%s:x:%s:30000:Nix build user %s:/var/empty:/bin/sh\n' \
          "$nixbld_index" "$((30000 + nixbld_index))" "$nixbld_index" >> etc/passwd
        if [ -n "$nixbld_members" ]; then
          nixbld_members="$nixbld_members,"
        fi
        nixbld_members="$nixbld_members""nixbld$nixbld_index"
        nixbld_index="$((nixbld_index + 1))"
      done
      printf 'nixbld:x:30000:%s\n' "$nixbld_members" >> etc/group
      cat > etc/nix/nix.conf <<'EOF'
      experimental-features = nix-command flakes
      sandbox = false
      allowed-users = root t3code
      trusted-users = root
      max-jobs = 2
      cores = 2
      build-users-group = nixbld
      EOF
      rm -f etc/sudoers etc/sudoers.d/t3code-apply-config etc/pam.d/sudo
      cat > etc/sudoers <<'EOF'
      root ALL=(ALL:ALL) ALL
      #includedir /etc/sudoers.d
      EOF
      chmod 0440 etc/sudoers
      cat > etc/sudoers.d/t3code-apply-config <<'EOF'
      t3code ALL=(root) NOPASSWD: ${pkgs.systemd}/bin/systemctl reset-failed t3code-server.service
      t3code ALL=(root) NOPASSWD: ${pkgs.systemd}/bin/systemctl restart t3code-server.service
      EOF
      chmod 0440 etc/sudoers.d/t3code-apply-config
      rm -f etc/pam.d/systemd-user
      cat > etc/pam.d/systemd-user <<'EOF'
      account required ${pkgs.pam}/lib/security/pam_permit.so
      session required ${pkgs.pam}/lib/security/pam_permit.so
      EOF
      cat > etc/pam.d/sudo <<'EOF'
      auth sufficient ${pkgs.pam}/lib/security/pam_permit.so
      account required ${pkgs.pam}/lib/security/pam_permit.so
      session required ${pkgs.pam}/lib/security/pam_permit.so
      EOF
      for system_unit in halt.target shutdown.target final.target systemd-halt.service umount.target; do
        cp -a "${pkgs.systemd}/example/systemd/system/$system_unit" etc/systemd/system/
      done
      cp -a ${pkgs.systemd}/example/systemd/user/. usr/share/systemd/user/
      rm -f etc/systemd/user/dbus.socket etc/systemd/user/dbus.service etc/systemd/user/sockets.target.wants/dbus.socket
      cat > etc/systemd/user/dbus.socket <<'EOF'
      [Unit]
      Description=D-Bus User Message Bus Socket

      [Socket]
      ListenStream=%t/bus
      ExecStartPost=-${pkgs.systemd}/bin/systemctl --user set-environment DBUS_SESSION_BUS_ADDRESS=unix:path=%t/bus

      [Install]
      WantedBy=sockets.target
      EOF
      cat > etc/systemd/user/dbus.service <<'EOF'
      [Unit]
      Description=D-Bus User Message Bus
      Documentation=man:dbus-daemon(1)
      Requires=dbus.socket

      [Service]
      Type=notify
      NotifyAccess=main
      ExecStart=${pkgs.dbus}/bin/dbus-daemon --config-file=${pkgs.dbus}/share/dbus-1/session.conf --address=systemd: --nofork --nopidfile --systemd-activation --syslog-only
      ExecReload=${pkgs.dbus}/bin/dbus-send --print-reply --session --type=method_call --dest=org.freedesktop.DBus / org.freedesktop.DBus.ReloadConfig
      Slice=session.slice
      EOF
      ln -s ../dbus.socket etc/systemd/user/sockets.target.wants/dbus.socket
      cat > etc/systemd/system/t3code-container-setup.service <<'EOF'
      [Unit]
      Description=Prepare T3 Code container state
      DefaultDependencies=no
      Conflicts=shutdown.target
      Before=shutdown.target

      [Service]
      Type=oneshot
      ExecStart=${t3codeContainerSetup}/bin/t3code-container-setup
      RemainAfterExit=yes
      TimeoutStartSec=20m
      TasksMax=infinity

      [Install]
      WantedBy=multi-user.target
      EOF
      cat > etc/systemd/system/nix-daemon.service <<'EOF'
      [Unit]
      Description=Nix package manager daemon
      DefaultDependencies=no
      After=t3code-container-setup.service nix-daemon.socket
      Requires=t3code-container-setup.service nix-daemon.socket
      Conflicts=shutdown.target
      Before=user@3000.service t3code-bootstrap.service t3code-server.service shutdown.target

      [Service]
      Type=simple
      ExecStart=@${pkgs.nix}/bin/nix-daemon nix-daemon --daemon
      KillMode=mixed
      LimitNOFILE=1048576
      Delegate=yes
      Restart=always
      RestartSec=5
      TimeoutStopSec=30s
      TasksMax=infinity

      [Install]
      WantedBy=multi-user.target
      EOF
      cat > etc/systemd/system/nix-daemon.socket <<'EOF'
      [Unit]
      Description=Nix package manager daemon socket
      DefaultDependencies=no
      After=t3code-container-setup.service
      Requires=t3code-container-setup.service
      Conflicts=shutdown.target
      Before=nix-daemon.service user@3000.service t3code-bootstrap.service t3code-server.service shutdown.target

      [Socket]
      ListenStream=/nix/var/nix/daemon-socket/socket
      SocketMode=0666
      DirectoryMode=0755
      RemoveOnStop=true

      [Install]
      WantedBy=multi-user.target
      EOF
      cat > etc/systemd/system/user@.service <<'EOF'
      [Unit]
      Description=T3 Code user manager for UID %i
      Documentation=man:user@.service(5)
      DefaultDependencies=no
      After=t3code-container-setup.service nix-daemon.socket
      Requires=t3code-container-setup.service nix-daemon.socket
      Conflicts=shutdown.target
      Before=t3code-bootstrap.service t3code-server.service shutdown.target
      IgnoreOnIsolate=yes

      [Service]
      User=%i
      PAMName=systemd-user
      Type=notify-reload
      Environment=HOME=/home/t3code
      Environment=USER=t3code
      Environment=LOGNAME=t3code
      Environment=XDG_RUNTIME_DIR=/run/user/%i
      Environment=DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/%i/bus
      Environment=NIX_REMOTE=daemon
      ExecStart=${pkgs.systemd}/lib/systemd/systemd --user
      Slice=user-%i.slice
      ReloadSignal=RTMIN+25
      KillMode=mixed
      Delegate=pids memory cpu
      DelegateSubgroup=init.scope
      TasksMax=infinity
      TimeoutStopSec=10s
      KeyringMode=inherit
      OOMScoreAdjust=100
      MemoryPressureWatch=skip
      Restart=always
      RestartSec=5

      [Install]
      WantedBy=multi-user.target
      EOF
      cat > etc/systemd/system/dockerd.service <<'EOF'
      [Unit]
      Description=T3 Code Docker daemon
      DefaultDependencies=no
      After=t3code-container-setup.service
      Requires=t3code-container-setup.service
      Conflicts=shutdown.target
      Before=shutdown.target

      [Service]
      Type=simple
      ExecStart=${t3codeDockerdRun}/bin/t3code-dockerd-run
      Restart=always
      RestartSec=5
      TimeoutStopSec=30s
      TasksMax=infinity

      [Install]
      WantedBy=multi-user.target
      EOF
      cat > etc/systemd/system/t3code-bootstrap.service <<'EOF'
      [Unit]
      Description=Run T3 Code bootstrap hooks
      DefaultDependencies=no
      After=t3code-container-setup.service nix-daemon.socket user@3000.service dockerd.service
      Requires=t3code-container-setup.service nix-daemon.socket user@3000.service dockerd.service
      Conflicts=shutdown.target
      Before=shutdown.target

      [Service]
      Type=oneshot
      User=t3code
      Group=t3code
      Environment=HOME=/home/t3code
      Environment=USER=t3code
      Environment=XDG_RUNTIME_DIR=/run/user/3000
      Environment=DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/3000/bus
      Environment=OPENCODE_AUTOMATION_DIR=/home/t3code/.automation
      Environment=PATH=${t3codePath}:/home/t3code/.local/bin:/home/t3code/.local/share/t3code-tools/npm/bin:/bin:/usr/bin
      ExecStart=${t3codeBootstrap}/bin/t3code-bootstrap
      RemainAfterExit=yes
      TimeoutStartSec=20m
      StandardOutput=append:/home/t3code/.t3code-container/logs/t3code-bootstrap.log
      StandardError=append:/home/t3code/.t3code-container/logs/t3code-bootstrap.log
      TasksMax=infinity

      [Install]
      WantedBy=multi-user.target
      EOF
      cat > etc/systemd/system/t3code-server.service <<'EOF'
      [Unit]
      Description=T3 Code server and web UI
      DefaultDependencies=no
      After=t3code-container-setup.service user@3000.service dockerd.service t3code-bootstrap.service
      Requires=t3code-container-setup.service user@3000.service dockerd.service t3code-bootstrap.service
      Conflicts=shutdown.target
      Before=shutdown.target

      [Service]
      Type=simple
      User=t3code
      Group=t3code
      Environment=HOME=/home/t3code
      Environment=USER=t3code
      Environment=XDG_RUNTIME_DIR=/run/user/3000
      Environment=DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/3000/bus
      Environment=OPENCODE_AUTOMATION_DIR=/home/t3code/.automation
      Environment=AGENT_CLOAK_BASE_URL=http://cloakbrowser:8080
      Environment=PATH=${t3codePath}:/home/t3code/.local/bin:/home/t3code/.local/share/t3code-tools/npm/bin:/bin:/usr/bin
      ExecStartPre=${t3codeRunHooks}/bin/t3code-run-hooks before-t3code.d
      ExecStartPre=+${pkgs.coreutils}/bin/rm -f /run/t3code-tool-update/restart.pending /home/t3code/.local/share/t3code-tools/t3/activation.pending
      ExecStart=${t3codeDaemonRun}/bin/t3code-server-run
      ExecStartPost=${t3codeSnapshotConfig}/bin/t3code-snapshot-config
      Restart=always
      RestartSec=5
      TimeoutStartSec=20m
      TimeoutStopSec=10s
      SuccessExitStatus=0 143
      StandardOutput=append:/home/t3code/.t3code-container/logs/t3code-server.service.log
      StandardError=append:/home/t3code/.t3code-container/logs/t3code-server.service.log
      # This cgroup includes every provider and its tools, not only the web server.
      MemoryHigh=24G
      MemoryMax=32G
      OOMPolicy=continue
      TasksMax=infinity

      [Install]
      WantedBy=multi-user.target
      EOF
      cat > etc/systemd/system/t3code-access-proxy.service <<'EOF'
      [Unit]
      Description=T3 Code access through the Cloudflare-authenticated site
      DefaultDependencies=no
      After=t3code-server.service
      Requires=t3code-container-setup.service
      Conflicts=shutdown.target
      Before=shutdown.target

      [Service]
      User=t3code
      Group=t3code
      Environment=HOME=/home/t3code
      ExecStart=${t3codeAccessProxy}/bin/t3code-access-proxy
      Restart=always
      RestartSec=5
      StandardOutput=append:/home/t3code/.t3code-container/logs/t3code-access-proxy.log
      StandardError=append:/home/t3code/.t3code-container/logs/t3code-access-proxy.log

      [Install]
      WantedBy=multi-user.target
      EOF
      cat > etc/systemd/system/t3code-tool-auto-update.service <<'EOF'
      [Unit]
      Description=Update T3 Code, Codex, Antigravity, OpenCode, and Ghostship tooling
      DefaultDependencies=no
      After=t3code-bootstrap.service
      Requires=t3code-bootstrap.service
      Conflicts=shutdown.target
      Before=shutdown.target

      [Service]
      Type=oneshot
      Environment=PATH=${t3codePath}:/home/t3code/.local/bin:/home/t3code/.local/share/t3code-tools/npm/bin:/bin:/usr/bin
      ExecStart=${t3codeToolAutoUpdate}/bin/t3code-tool-auto-update
      StandardOutput=append:/home/t3code/.t3code-container/logs/t3code-tool-auto-update.log
      StandardError=append:/home/t3code/.t3code-container/logs/t3code-tool-auto-update.log
      TasksMax=infinity
      EOF
      cat > etc/systemd/system/t3code-tool-auto-update.timer <<'EOF'
      [Unit]
      Description=Periodic T3 Code agent tool updates
      DefaultDependencies=no
      After=t3code-bootstrap.service
      Conflicts=shutdown.target
      Before=shutdown.target

      [Timer]
      OnBootSec=10m
      OnUnitActiveSec=4h
      Persistent=true
      Unit=t3code-tool-auto-update.service

      [Install]
      WantedBy=multi-user.target
      EOF
      cat > etc/systemd/system/t3code-tool-update-restart.service <<'EOF'
      [Unit]
      Description=Restart T3 Code after queued maintenance becomes idle
      DefaultDependencies=no
      After=t3code-bootstrap.service
      Requires=t3code-bootstrap.service
      Conflicts=shutdown.target
      Before=shutdown.target

      [Service]
      Type=oneshot
      Environment=PATH=${t3codePath}:/home/t3code/.local/bin:/home/t3code/.local/share/t3code-tools/npm/bin:/bin:/usr/bin
      ExecStart=${t3codeToolUpdateRestart}/bin/t3code-tool-update-restart
      StandardOutput=append:/home/t3code/.t3code-container/logs/t3code-tool-update-restart.log
      StandardError=append:/home/t3code/.t3code-container/logs/t3code-tool-update-restart.log
      TasksMax=infinity
      EOF
      cat > etc/systemd/system/t3code-tool-update-restart.timer <<'EOF'
      [Unit]
      Description=Apply queued T3 Code maintenance when idle
      DefaultDependencies=no
      After=t3code-bootstrap.service
      Conflicts=shutdown.target
      Before=shutdown.target

      [Timer]
      OnBootSec=2m
      OnUnitActiveSec=1m
      Unit=t3code-tool-update-restart.service

      [Install]
      WantedBy=multi-user.target
      EOF
      cat > etc/systemd/system/t3code-server-monitor.service <<'EOF'
      [Unit]
      Description=Monitor T3 Code server and agent tools
      DefaultDependencies=no
      After=t3code-server.service
      Conflicts=shutdown.target
      Before=shutdown.target

      [Service]
      Type=oneshot
      Environment=PATH=${t3codePath}:/home/t3code/.local/bin:/home/t3code/.local/share/t3code-tools/npm/bin:/bin:/usr/bin
      ExecStart=${t3codeDaemonMonitor}/bin/t3code-server-monitor
      StandardOutput=append:/home/t3code/.t3code-container/logs/t3code-server-monitor.log
      StandardError=append:/home/t3code/.t3code-container/logs/t3code-server-monitor.log
      TasksMax=infinity
      EOF
      cat > etc/systemd/system/t3code-server-monitor.timer <<'EOF'
      [Unit]
      Description=Periodic T3 Code server monitor
      DefaultDependencies=no
      After=t3code-server.service
      Conflicts=shutdown.target
      Before=shutdown.target

      [Timer]
      OnBootSec=2m
      OnUnitActiveSec=1m
      Unit=t3code-server-monitor.service

      [Install]
      WantedBy=multi-user.target
      EOF
      cat > etc/systemd/system/multi-user.target <<'EOF'
      [Unit]
      Description=T3 Code Multi-User System
      DefaultDependencies=no
      Wants=t3code-container-setup.service nix-daemon.socket nix-daemon.service user@3000.service dockerd.service t3code-bootstrap.service t3code-server.service t3code-access-proxy.service t3code-tool-auto-update.timer t3code-tool-update-restart.timer t3code-server-monitor.timer
      After=t3code-container-setup.service nix-daemon.socket user@3000.service dockerd.service
      AllowIsolate=yes
      EOF
      rm -f etc/systemd/system/docker.service \
        etc/systemd/system/docker.socket \
        etc/systemd/system/multi-user.target.wants/docker.service \
        etc/systemd/system/sockets.target.wants/docker.socket
      ln -s multi-user.target etc/systemd/system/default.target
      ln -s ../t3code-container-setup.service etc/systemd/system/multi-user.target.wants/t3code-container-setup.service
      ln -s ../nix-daemon.socket etc/systemd/system/multi-user.target.wants/nix-daemon.socket
      ln -s ../nix-daemon.service etc/systemd/system/multi-user.target.wants/nix-daemon.service
      ln -s ../user@.service etc/systemd/system/multi-user.target.wants/user@3000.service
      ln -s ../dockerd.service etc/systemd/system/multi-user.target.wants/dockerd.service
      ln -s ../t3code-bootstrap.service etc/systemd/system/multi-user.target.wants/t3code-bootstrap.service
      ln -s ../t3code-server.service etc/systemd/system/multi-user.target.wants/t3code-server.service
      ln -s ../t3code-access-proxy.service etc/systemd/system/multi-user.target.wants/t3code-access-proxy.service
      ln -s ../t3code-tool-auto-update.timer etc/systemd/system/multi-user.target.wants/t3code-tool-auto-update.timer
      ln -s ../t3code-tool-update-restart.timer etc/systemd/system/multi-user.target.wants/t3code-tool-update-restart.timer
      ln -s ../t3code-server-monitor.timer etc/systemd/system/multi-user.target.wants/t3code-server-monitor.timer
    '';
    fakeRootCommands = ''
      chown -R root:root nix/store nix/var/log/nix nix/var/nix
      chmod -R u+rwX,go+rX nix/store nix/var/log/nix nix/var/nix
      chown 0:0 usr/bin/sudo
      chmod 4755 usr/bin/sudo
    '';
    config = {
      Cmd = [ "${t3codeEntrypoint}/bin/t3code-systemd-entrypoint" ];
      Env = [
        "HOME=/home/t3code"
        "USER=t3code"
        "DOCKER_HOST=unix:///var/run/docker.sock"
        "XDG_RUNTIME_DIR=/run/user/3000"
        "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/3000/bus"
        "XDG_CONFIG_HOME=/home/t3code/.config"
        "XDG_STATE_HOME=/home/t3code/.local/state"
        "XDG_CACHE_HOME=/home/t3code/.cache"
        "XDG_DATA_HOME=/home/t3code/.local/share"
        "NPM_CONFIG_PREFIX=/home/t3code/.local/share/t3code-tools/npm"
        "npm_config_prefix=/home/t3code/.local/share/t3code-tools/npm"
        "OPENCODE_AUTOMATION_DIR=/home/t3code/.automation"
        "PATH=${t3codePath}:/home/t3code/.local/bin:/home/t3code/.local/share/t3code-tools/npm/bin:/bin:/usr/bin"
        "NIX_SSL_CERT_FILE=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
        "SSL_CERT_FILE=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
        "NIX_CONFIG=experimental-features = nix-command flakes"
        "NIX_REMOTE=daemon"
        "T3CODE_HOME=/home/t3code/.t3"
        "T3CODE_HOST=127.0.0.1"
        "T3CODE_PORT=3774"
        "T3CODE_NO_BROWSER=true"
        "AGENT_CLOAK_BASE_URL=http://cloakbrowser:8080"
      ];
      WorkingDir = "/home/t3code";
      ExposedPorts = {
        "3773/tcp" = { };
      };
    };
  };

in
{
  # The Antigravity ACP archive is unfree; keep the exception scoped to this app.
  nixpkgs.config.allowUnfreePredicate =
    pkg:
    builtins.elem (lib.getName pkg) [
      "antigravity-acp"
    ];

  ghostship.agentHost.enable = true;
  ghostship.apps.t3code = {
    name = "T3 Code";
    group = "Services";
    description = "Codex, OpenCode, and Antigravity workspace";
    icon = "mdi-code-braces-#7c3aed";
    order = 102;
    hostname = "t3code.ghostship.io";
    origin = "http://t3code:3773";
    healthPath = "/";
    muximux = {
      icon = "muximux-code";
      color = "#7c3aed";
      dropdown = false;
    };
  };



  virtualisation.oci-containers.containers."t3code" = {
    image = "${imageName}:${imageTag}";
    imageFile = t3codeImage;
    pull = "never";
    labels = {
      "io.containers.autoupdate" = "disabled";
    };
    ports = [ ];
    extraOptions = [
      "--privileged"
      "--systemd=always"
      "--pids-limit=-1"
      "--stop-timeout=180"
      "--hostname=t3code.ghostship.io"
      "--network=ghostship_net"
      "--health-cmd=${t3codeContainerHealth}/bin/t3code-container-health"
      "--health-interval=30s"
      "--health-timeout=15s"
      "--health-retries=5"
      "--health-start-period=5m"
    ];
    volumes = [
      "${t3codeDocker}:/var/lib/docker:rw"
      "${t3codeWorkspace}:/workspace:rw"
      "${t3codeHome}:/home/t3code:rw"
      "${t3codeNixRoot}/nix:/nix:rw"
      "${t3codeSecrets}:${t3codeSecretsFile}:ro"
      "${config.ghostship.agentHost.sharedPath}:/mnt/share:rw"
    ];
    environmentFiles = [ t3codeSecrets ];
  };

  systemd.tmpfiles.rules = [
    "d /srv/apps/t3code 0755 root root -"
    "d ${t3codeDocker} 0755 root root -"
    "d ${t3codeHome} 0755 3000 3000 -"
    "d ${t3codeNixRoot} 0755 root root -"
    "d ${t3codeNixRoot}/nix 0755 root root -"
    "d ${t3codeWorkspace} 0755 3000 3000 -"
  ];

  systemd.services.podman-t3code = {
    restartIfChanged = false;
    stopIfChanged = false;
    after = [
      "init-ghostship-net.service"
      "mnt-share.mount"
    ];
    wants = [
      "init-ghostship-net.service"
      "mnt-share.mount"
    ];
    serviceConfig.TimeoutStopSec = lib.mkForce "210s";
    preStart = lib.mkAfter ''
      set -eu

      install -d -m0755 -o root -g root /srv/apps/t3code
      install -d -m0755 -o root -g root ${t3codeDocker}
      install -d -m0755 -o 3000 -g 3000 ${t3codeHome}
      install -d -m0755 -o root -g root ${t3codeNixRoot}
      install -d -m0755 -o 3000 -g 3000 ${t3codeWorkspace}

      nix_store_uri='local?root=${t3codeNixRoot}'
      ${pkgs.nix}/bin/nix copy \
        --no-check-sigs \
        --to "$nix_store_uri" \
        ${lib.escapeShellArgs (map toString t3codeImageContents)}

      gcroot_dir=${t3codeNixRoot}/nix/var/nix/gcroots/ghostship-t3code-image
      rm -rf "$gcroot_dir"
      install -d -m0755 -o root -g root "$gcroot_dir"
      for store_path in ${lib.escapeShellArgs (map toString t3codeImageContents)}; do
        ln -s "$store_path" "$gcroot_dir/$(basename "$store_path")"
      done

      rm -f ${t3codeNixRoot}/nix/var/nix/temproots/*
      rm -rf ${t3codeNixRoot}/nix/var/nix/builds/*
      install -d -m0755 -o 3000 -g 3000 ${t3codeHome}/.local/bin
      install -d -m0755 -o 3000 -g 3000 ${t3codeHome}/.local/share
      install -d -m0755 -o 3000 -g 3000 ${t3codeHome}/.local/state
      install -d -m0755 -o 3000 -g 3000 ${t3codeHome}/.cache
      install -d -m0755 -o 3000 -g 3000 ${t3codeHome}/.config/opencode
      install -d -m0755 -o 3000 -g 3000 ${t3codeHome}/.codex
      install -d -m0755 -o 3000 -g 3000 ${t3codeHome}/.gemini/antigravity-cli
      install -d -m0700 -o 3000 -g 3000 ${t3codeHome}/.local/share/keyrings
      install -d -m0755 -o 3000 -g 3000 ${t3codeHome}/.automation
      install -d -m0755 -o 3000 -g 3000 ${t3codeHome}/.config/systemd/user
      install -d -m0755 -o 3000 -g 3000 ${t3codeHome}/.t3/userdata
      install -d -m0755 -o 3000 -g 3000 ${t3codeHome}/.t3/caches
      install -d -m0755 -o 3000 -g 3000 ${t3codeHome}/.t3code-container/logs/tunnels
      install -d -m0755 -o 3000 -g 3000 ${t3codeHome}/.t3code-container/recovery
      install -d -m0755 -o 3000 -g 3000 ${t3codeHome}/.t3code-container/tunnels
      install -d -m0755 -o 3000 -g 3000 ${t3codeHome}/.t3code-container/hooks/bootstrap.d
      install -d -m0755 -o 3000 -g 3000 ${t3codeHome}/.t3code-container/hooks/before-t3code.d
      install -d -m0755 -o 3000 -g 3000 ${t3codeHome}/.t3code-container/hooks/doctor.d

    '';
  };

}
