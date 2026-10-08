# Ghostship Agent Desktop session environment for login shells.
if [ -r /config/agent-desktop/session-env ]; then
  set -a
  . /config/agent-desktop/session-env
  set +a
fi
