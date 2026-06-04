{
  config,
  lib,
  osConfig,
  pkgs,
  ...
}:

let
  isWsl = osConfig.ghostship.host.roles.wsl or false;
  codexDesktopHome = "$HOME/.codex-desktop";
  codexDesktopSqlite = "$HOME/.codex-desktop/sqlite";
in
{
  home.file.".codex/AGENTS.md" = {
    source = ../../home/config/AGENTS.md;
    force = true;
  };

  home.activation.codexDesktopHome = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    CODEX_DESKTOP_HOME="${codexDesktopHome}"

    mkdir -p \
      "$CODEX_DESKTOP_HOME" \
      "$CODEX_DESKTOP_HOME/sqlite" \
      "$CODEX_DESKTOP_HOME/sessions" \
      "$CODEX_DESKTOP_HOME/worktrees" \
      "$CODEX_DESKTOP_HOME/.tmp"
  '';

  home.activation.codexDesktopWindowsMigration = lib.mkIf isWsl (
    lib.hm.dag.entryAfter
      [
        "codexDesktopHome"
        "wslHomeSymlink"
        "wslWindowsCodexAgents"
      ]
      ''
        SOURCE_HOME="$HOME/win-home/.codex"
        TARGET_HOME="${codexDesktopHome}"
        SQLITE_HOME="${codexDesktopSqlite}"
        MARKER_DIR="$TARGET_HOME/.migration"
        MARKER="$MARKER_DIR/windows-codex-home"

        normalize_desktop_config() {
          CONFIG="$TARGET_HOME/config.toml"
          [ -f "$CONFIG" ] || return 0

          TMP="$CONFIG.hm-tmp"

          if ${pkgs.gnugrep}/bin/grep -q '^sqlite_home[[:space:]]*=' "$CONFIG"; then
            ${pkgs.gnused}/bin/sed -i \
              's|^sqlite_home[[:space:]]*=.*|sqlite_home = "'"$SQLITE_HOME"'"|' \
              "$CONFIG"
          else
            {
              printf 'sqlite_home = "%s"\n' "$SQLITE_HOME"
              ${pkgs.coreutils}/bin/cat "$CONFIG"
            } > "$TMP"
            ${pkgs.coreutils}/bin/mv "$TMP" "$CONFIG"
          fi

          ${pkgs.gnused}/bin/sed -i \
            -e "s|^NODE_REPL_TRUSTED_CODE_PATHS[[:space:]]*=.*|NODE_REPL_TRUSTED_CODE_PATHS = \"$TARGET_HOME\"|" \
            -e "s|^CODEX_HOME[[:space:]]*=.*|CODEX_HOME = \"$TARGET_HOME\"|" \
            "$CONFIG"

          if ${pkgs.gnugrep}/bin/grep -q '^\[mcp_servers\.node_repl\.env\]' "$CONFIG"; then
            if ${pkgs.gnugrep}/bin/grep -q '^CODEX_SQLITE_HOME[[:space:]]*=' "$CONFIG"; then
              ${pkgs.gnused}/bin/sed -i \
                "s|^CODEX_SQLITE_HOME[[:space:]]*=.*|CODEX_SQLITE_HOME = \"$SQLITE_HOME\"|" \
                "$CONFIG"
            else
              ${pkgs.gawk}/bin/awk '
                { print }
                $0 ~ /^CODEX_HOME[[:space:]]*=/ {
                  print "CODEX_SQLITE_HOME = \"" sqlite_home "\""
                }
              ' sqlite_home="$SQLITE_HOME" "$CONFIG" > "$TMP"
              ${pkgs.coreutils}/bin/mv "$TMP" "$CONFIG"
            fi

            if ${pkgs.gnugrep}/bin/grep -q '^WSLENV[[:space:]]*=' "$CONFIG" \
              && ! ${pkgs.gnugrep}/bin/grep -q 'CODEX_SQLITE_HOME/w' "$CONFIG"; then
              ${pkgs.gnused}/bin/sed -i \
                's|CODEX_HOME/w:|CODEX_HOME/w:CODEX_SQLITE_HOME/w:|' \
                "$CONFIG"
            fi
          fi
        }

        if [ ! -d "$SOURCE_HOME" ]; then
          normalize_desktop_config
          exit 0
        fi

        if [ -f "$MARKER" ]; then
          normalize_desktop_config
          exit 0
        fi

        if [ -f "$TARGET_HOME/auth.json" ] || [ -f "$TARGET_HOME/config.toml" ] || [ -d "$TARGET_HOME/sessions/2026" ]; then
          echo "Detected existing Codex Desktop WSL migration at $TARGET_HOME"
          mkdir -p "$MARKER_DIR"
          printf 'detected existing migration\n' > "$MARKER"
          normalize_desktop_config
          exit 0
        fi

        if ${pkgs.procps}/bin/pgrep -f 'codex app-server' >/dev/null \
          || ${pkgs.procps}/bin/pgrep -f 'node_repl.exe' >/dev/null; then
          echo "Skipping Codex Desktop Windows migration because Codex Desktop is running"
          exit 0
        fi

        echo "Migrating Windows Codex Desktop state from $SOURCE_HOME to $TARGET_HOME"
        mkdir -p "$TARGET_HOME" "$MARKER_DIR"

        for entry in auth.json config.toml AGENTS.md skills sessions worktrees; do
          [ -e "$SOURCE_HOME/$entry" ] || continue

          if [ -d "$SOURCE_HOME/$entry" ]; then
            mkdir -p "$TARGET_HOME/$entry"
            ${pkgs.rsync}/bin/rsync -a \
              --exclude='logs_2.sqlite*' \
              --exclude='*.sqlite-wal' \
              --exclude='*.sqlite-shm' \
              --exclude='.tmp/plugins/' \
              --exclude='cache/' \
              --exclude='caches/' \
              --exclude='Cache/' \
              --exclude='log/' \
              --exclude='logs/' \
              --exclude='*.log' \
              "$SOURCE_HOME/$entry/" "$TARGET_HOME/$entry/"
          else
            ${pkgs.rsync}/bin/rsync -a \
              --exclude='logs_2.sqlite*' \
              --exclude='*.sqlite-wal' \
              --exclude='*.sqlite-shm' \
              "$SOURCE_HOME/$entry" "$TARGET_HOME/"
          fi
        done

        mkdir -p "$SQLITE_HOME"
        normalize_desktop_config
        printf 'migrated from %s\n' "$SOURCE_HOME" > "$MARKER"
      ''
  );
}
