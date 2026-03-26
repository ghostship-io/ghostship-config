{ config, lib, pkgs, ... }:

{
  # System-level activation script to fix home directory ownership
  # This runs as root, allowing it to fix files owned by root.
  system.activationScripts.homeChown = {
    text = ''
      # Iterate through all directories in /home to detect users
      for HOME_DIR in /home/*; do
        if [ -d "$HOME_DIR" ]; then
          USER=$(basename "$HOME_DIR")
          
          # Check if the user exists and the group with the same name exists
          if id "$USER" >/dev/null 2>&1 && getent group "$USER" >/dev/null 2>&1; then
            SENTINEL="$HOME_DIR/.local/state/nix/home_chown.done"
            
            if [ ! -f "$SENTINEL" ]; then
              echo "Running one-time system-level home directory chown for $USER:$USER..."
              
              # Ensure the sentinel directory exists with correct ownership first
              mkdir -p "$(dirname "$SENTINEL")"
              chown -R "$USER:$USER" "$(dirname "$SENTINEL")"

              # Perform the recursive chown
              chown -R "$USER:$USER" "$HOME_DIR"

              # Create the sentinel file
              touch "$SENTINEL"
              chown "$USER:$USER" "$SENTINEL"
            fi
          fi
        fi
      done
    '';
    # Ensure this runs after the users and groups are created
    deps = [ "users" "groups" ];
  };
}
