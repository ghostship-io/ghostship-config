# The config contains one absolute evidence root; window.lock is never replaced.
window_root() {
  : "${WINDOW_CONFIG:?}"
  [[ -f $WINDOW_CONFIG && -r $WINDOW_CONFIG ]] || { echo 'missing window config' >&2; return 1; }
  WINDOW_ROOT=$(cat "$WINDOW_CONFIG")
  [[ $WINDOW_ROOT == /* && $WINDOW_ROOT != *$'\n'* && $WINDOW_ROOT != / ]] || { echo 'invalid evidence root' >&2; return 1; }
}
window_id_valid() { [[ $1 =~ ^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$ && $1 != no-window && $1 != . && $1 != .. ]]; }
announce_intent() {
  local writer=$1 id dir record
  [[ $writer =~ ^[a-z][a-z0-9-]*$ ]] || return 1
  window_root
  [[ -d $WINDOW_ROOT && -f $WINDOW_ROOT/window.lock ]] || { echo 'window root is not provisioned' >&2; return 1; }
  exec {window_fd}<"$WINDOW_ROOT/window.lock"
  flock -s "$window_fd"
  id=no-window
  if [[ -e $WINDOW_ROOT/active-window ]]; then
    [[ -f $WINDOW_ROOT/active-window && ! -L $WINDOW_ROOT/active-window ]] || return 1
    id=$(cat "$WINDOW_ROOT/active-window")
    window_id_valid "$id" || return 1
    [[ -f $WINDOW_ROOT/$id/window.start && ! -L $WINDOW_ROOT/$id/window.start ]] || return 1
  fi
  dir=$WINDOW_ROOT/$id
  install -d -m 0700 "$dir"
  record=$(mktemp "$dir/effect-intent.$writer.XXXXXXXX")
  printf '%s %s\n' "$writer" "$(date -u +%FT%TZ)" > "$record"
  sync -f "$record"
  sync -f "$dir"
  # The descriptor stays open through the effect.
}
