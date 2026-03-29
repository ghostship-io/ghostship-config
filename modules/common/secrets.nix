{ inputs, config, pkgs, ... }:

let
  sops-edit = pkgs.writeShellScriptBin "sops-edit" ''
    export SOPS_AGE_KEY_FILE=/etc/nix/secrets/age.key
    if [ "$(id -u)" -ne 0 ]; then
      echo "Error: This script requires root privileges."
      echo "Please run from a root shell: sops-edit"
      exit 1
    fi
    REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || echo ".")
    TARGET_FILE="''${1:-secrets.yaml}"
    if [ -f "$TARGET_FILE" ]; then
      exec ${pkgs.sops}/bin/sops "$TARGET_FILE"
    else
      exec ${pkgs.sops}/bin/sops "$REPO_ROOT/$TARGET_FILE"
    fi
  '';

  sops-decrypt = pkgs.writeShellScriptBin "sops-decrypt" ''
    export SOPS_AGE_KEY_FILE=/etc/nix/secrets/age.key
    if [ "$(id -u)" -ne 0 ]; then
      echo "Error: This script requires root privileges."
      echo "Please run from a root shell: sops-decrypt"
      exit 1
    fi
    REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || echo ".")
    TARGET_FILE="''${1:-secrets.yaml}"
    
    if [ -f "$TARGET_FILE" ]; then
      FILE_PATH="$TARGET_FILE"
    else
      FILE_PATH="$REPO_ROOT/$TARGET_FILE"
    fi

    if [ ! -f "$FILE_PATH" ]; then
      echo "Error: Secrets file not found at $FILE_PATH"
      exit 1
    fi

    echo "Decrypting $FILE_PATH to $REPO_ROOT/secrets.dec.yaml..."
    # Decrypt and strip metadata using yq to keep only the actual data
    ${pkgs.sops}/bin/sops -d "$FILE_PATH" | ${pkgs.yq-go}/bin/yq 'del(.sops)' > "$REPO_ROOT/secrets.dec.yaml"
    # Change owner of secrets.dec.yaml to match secrets.yaml
    OWNER=$(stat -c '%U:%G' "$FILE_PATH")
    chown "$OWNER" "$REPO_ROOT/secrets.dec.yaml"
    echo "Done. Edit secrets.dec.yaml and then run sops-encrypt to save changes."
  '';

  sops-encrypt = pkgs.writeShellScriptBin "sops-encrypt" ''
    export SOPS_AGE_KEY_FILE=/etc/nix/secrets/age.key
    if [ "$(id -u)" -ne 0 ]; then
      echo "Error: This script requires root privileges."
      echo "Please run from a root shell: sops-encrypt"
      exit 1
    fi
    REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || echo ".")
    DEC_FILE="$REPO_ROOT/secrets.dec.yaml"
    TARGET_FILE="''${1:-secrets.yaml}"

    if [ -f "$TARGET_FILE" ]; then
      FILE_PATH="$TARGET_FILE"
    else
      FILE_PATH="$REPO_ROOT/$TARGET_FILE"
    fi

    if [ ! -f "$DEC_FILE" ]; then
      echo "Error: Decrypted file not found at $DEC_FILE"
      exit 1
    fi

    echo "Overwriting $FILE_PATH with $DEC_FILE and encrypting in-place..."
    cp "$DEC_FILE" "$FILE_PATH"
    
    # Encrypt in-place using the config to ensure correct recipients
    ${pkgs.sops}/bin/sops --encrypt --in-place --config "$REPO_ROOT/.sops.yaml" "$FILE_PATH"
    
    echo "Success! Removing $DEC_FILE..."
    rm "$DEC_FILE"
  '';

  sops-list-keys = pkgs.writeShellScriptBin "sops-list-keys" ''
    if [ "$(id -u)" -ne 0 ]; then
      echo "Error: This script requires root privileges."
      echo "Please run from a root shell: sops-list-keys"
      exit 1
    fi
    REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || echo ".")
    SOPS_CONFIG="$REPO_ROOT/.sops.yaml"

    if [ ! -f "$SOPS_CONFIG" ]; then
      echo "Error: .sops.yaml not found at $SOPS_CONFIG"
      exit 1
    fi

    echo "Public keys and associated systems in .sops.yaml:"
    echo "--------------------------------------------------"
    # Extract age keys and comments, handling cases with and without comments
    grep "age1" "$SOPS_CONFIG" | sed -E 's/^[[:space:]]*- ([^[:space:]#]+)([[:space:]]*#[[:space:]]*)?(.*)$/\1 \3/' | while read -r key system; do
      printf "%-60s | %s\n" "$key" "''${system:-Unknown}"
    done
  '';

  sops-reencrypt = pkgs.writeShellScriptBin "sops-reencrypt" ''
    export SOPS_AGE_KEY_FILE=/etc/nix/secrets/age.key
    if [ "$(id -u)" -ne 0 ]; then
      echo "Error: This script requires root privileges."
      echo "Please run from a root shell: sops-reencrypt"
      exit 1
    fi
    REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || echo ".")
    TARGET_FILE="''${1:-secrets.yaml}"

    # If file exists locally, use it. Otherwise try repo root.
    if [ -f "$TARGET_FILE" ]; then
      FILE_PATH="$TARGET_FILE"
    else
      FILE_PATH="$REPO_ROOT/$TARGET_FILE"
    fi

    if [ ! -f "$FILE_PATH" ]; then
      echo "Error: Secrets file not found at $FILE_PATH"
      exit 1
    fi

    echo "Re-encrypting $FILE_PATH using keys defined in .sops.yaml..."
    ${pkgs.sops}/bin/sops updatekeys "$FILE_PATH"
  '';

  sops-add-key = pkgs.writeShellScriptBin "sops-add-key" ''
    if [ "$(id -u)" -ne 0 ]; then
      echo "Error: This script requires root privileges."
      echo "Please run from a root shell: sops-add-key"
      exit 1
    fi
    REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || echo ".")
    SOPS_CONFIG="$REPO_ROOT/.sops.yaml"

    if [ -z "''${1:-}" ]; then
      echo "Usage: sops-add-key <public_age_key> [system_name]"
      exit 1
    fi

    NEW_KEY="$1"
    SYSTEM_NAME="''${2:-}"

    if [ ! -f "$SOPS_CONFIG" ]; then
      echo "Error: .sops.yaml not found at $SOPS_CONFIG"
      exit 1
    fi

    # Check if key already exists
    if grep -q "$NEW_KEY" "$SOPS_CONFIG"; then
      echo "Key already exists in .sops.yaml"
      exit 0
    fi

    echo "Adding key $NEW_KEY to $SOPS_CONFIG..."
    # Add the key using yq
    ${pkgs.yq-go}/bin/yq -i ".creation_rules[0].key_groups[0].age += [\"$NEW_KEY\"]" "$SOPS_CONFIG"

    # If system name provided, append the comment to the line with the new key
    if [ -n "$SYSTEM_NAME" ]; then
      sed -i "s|$NEW_KEY|$NEW_KEY # $SYSTEM_NAME|" "$SOPS_CONFIG"
    fi
    echo "Key added. Don't forget to run sops-reencrypt."
  '';


  sops-remove-key = pkgs.writeShellScriptBin "sops-remove-key" ''
    if [ "$(id -u)" -ne 0 ]; then
      echo "Error: This script requires root privileges."
      echo "Please run from a root shell: sops-remove-key"
      exit 1
    fi
    REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || echo ".")
    SOPS_CONFIG="$REPO_ROOT/.sops.yaml"

    if [ -z "''${1:-}" ]; then
      echo "Usage: sops-remove-key <public_age_key>"
      exit 1
    fi

    KEY_TO_REMOVE="$1"

    if [ ! -f "$SOPS_CONFIG" ]; then
      echo "Error: .sops.yaml not found at $SOPS_CONFIG"
      exit 1
    fi

    echo "Removing key $KEY_TO_REMOVE from $SOPS_CONFIG..."
    # Using yq to remove the key from the first creation rule's age list
    ${pkgs.yq-go}/bin/yq -i ".creation_rules[0].key_groups[0].age -= [\"$KEY_TO_REMOVE\"]" "$SOPS_CONFIG"
    echo "Key removed. Don't forget to run sops-reencrypt."
  '';

  sops-register-host = pkgs.writeShellScriptBin "sops-register-host" ''
    set -euo pipefail
    export SOPS_AGE_KEY_FILE=/etc/nix/secrets/age.key
    if [ "$(id -u)" -ne 0 ]; then
      echo "Error: This script requires root privileges."
      echo "Please run from a root shell: sops-register-host"
      exit 1
    fi
    REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || echo ".")
    
    echo "Paste the JSON bootstrap data and press Ctrl+D:"
    DATA=$(cat)
    
    # Check if data is valid JSON
    if ! echo "$DATA" | ${pkgs.jq}/bin/jq . >/dev/null 2>&1; then
      echo "Error: Invalid JSON input."
      exit 1
    fi

    HOSTNAME=$(echo "$DATA" | ${pkgs.jq}/bin/jq -r '.hostname')
    PUBLIC_KEY=$(echo "$DATA" | ${pkgs.jq}/bin/jq -r '.public_key')
    HW_CONFIG=$(echo "$DATA" | ${pkgs.jq}/bin/jq -r '.hardware_config')
    
    if [ -z "$HOSTNAME" ] || [ "$HOSTNAME" == "null" ]; then
      echo "Error: Could not parse hostname from input."
      exit 1
    fi
    
    echo "Registering host: $HOSTNAME"
    echo "Public Key: $PUBLIC_KEY"
    
    # 1. Update .sops.yaml
    echo "Updating .sops.yaml..."
    # Fallback to direct yq and sed if helper not available
    ${pkgs.yq-go}/bin/yq -i ".creation_rules[0].key_groups[0].age += [\"$PUBLIC_KEY\"]" "$REPO_ROOT/.sops.yaml"
    sed -i "s|$PUBLIC_KEY|$PUBLIC_KEY # $HOSTNAME|" "$REPO_ROOT/.sops.yaml"
    
    # 2. Create host directory and files
    HOST_DIR="$REPO_ROOT/hosts/$HOSTNAME"
    mkdir -p "$HOST_DIR"
    
    echo "Updating $HOST_DIR/hardware-configuration.nix..."
    echo "$HW_CONFIG" > "$HOST_DIR/hardware-configuration.nix"
    
    if [ ! -f "$HOST_DIR/default.nix" ]; then
      echo "Creating basic $HOST_DIR/default.nix..."
      cat > "$HOST_DIR/default.nix" <<EOF
{ ... }:

{
  imports = [
    ./hardware-configuration.nix
  ];

  networking.hostName = "$HOSTNAME";
}
EOF
    fi
    
    # 3. Re-encrypt secrets
    echo "Re-encrypting secrets..."
    ${pkgs.sops}/bin/sops updatekeys "$REPO_ROOT/secrets.yaml"
    
    echo ""
    echo "--------------------------------------------------------------------------------"
    echo "Host $HOSTNAME has been registered successfully!"
    echo "Next Steps:"
    echo "1. Verify .sops.yaml changes."
    echo "2. Add '$HOSTNAME' to 'flake.nix' in the 'nixosConfigurations' section."
    echo "3. Commit and push the changes."
    echo "4. On the new host, from a root shell run: nixos-rebuild build --flake .#$HOSTNAME && ./result/bin/switch-to-configuration switch"
    echo "--------------------------------------------------------------------------------"
  '';
in
{
  environment.systemPackages = [ 
    sops-edit
    sops-decrypt
    sops-encrypt
    sops-reencrypt
    sops-add-key
    sops-remove-key
    sops-list-keys
    sops-register-host
  ];

  sops = {
    defaultSopsFile = ../../secrets.yaml;
    defaultSopsFormat = "yaml";

    # Ensure we use the package from sops-nix itself
    package = inputs.sops-nix.packages.${pkgs.stdenv.hostPlatform.system}.sops-install-secrets;

    # Use age key in /etc/nix for secrets encryption
    age.keyFile = "/etc/nix/secrets/age.key";
    age.generateKey = true;

    secrets = {
    };
  };

  system.activationScripts.sops-public-key = {
    text = ''
      if [ -f /etc/nix/secrets/age.key ]; then
        echo "SOPS age public key:"
        ${pkgs.age}/bin/age-keygen -y /etc/nix/secrets/age.key
      fi
    '';
    supportsDryActivation = false;
  };
}
