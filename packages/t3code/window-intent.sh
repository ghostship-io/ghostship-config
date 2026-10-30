# Shared by all deployment effect writers. WINDOW_DIR must be identical for
# the window command and every writer; never remove its lock file.
announce_intent() {
  local writer=$1 record
  [[ $writer =~ ^[a-z][a-z0-9-]*$ ]] || return 1
  : "${WINDOW_DIR:?WINDOW_DIR is required}"
  install -d -m 0700 "$WINDOW_DIR"
  exec {window_fd}>"$WINDOW_DIR/window.lock"
  flock -x "$window_fd"
  if [[ -e $WINDOW_DIR/window.start ]]; then
    record=$(mktemp "$WINDOW_DIR/effect-intent.$writer.XXXXXXXX")
    printf '%s %s\n' "$writer" "$(date -u +%FT%TZ)" > "$record"
    sync -f "$record"
    sync -f "$WINDOW_DIR"
  fi
  flock -u "$window_fd"
  exec {window_fd}>&-
}
