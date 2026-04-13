{ inputs, config, lib, pkgs, ... }:

let
  recipients = import ../../secrets/recipients.nix;
  catalog = import ../../secrets/catalog.nix { inherit recipients; };
  rulesFile = ../../secrets/rules.nix;
  editKeyPath = "$HOME/.ssh/id_ed25519_ragenix";
  editKeyPubPath = "$HOME/.ssh/id_ed25519_ragenix.pub";
  ragenixPackage = inputs.ragenix.packages.${pkgs.stdenv.hostPlatform.system}.default;
  catalogJson = builtins.toJSON (
    lib.mapAttrs
      (_: meta: {
        inherit (meta) relativeFile recipientGroup recipients format exports;
      })
      catalog.units
  );

  secret-edit-keygen = pkgs.writeShellApplication {
    name = "secret-edit-keygen";
    runtimeInputs = [ pkgs.openssh ];
    text = ''
      set -euo pipefail
      if [ -e "$HOME/.ssh/id_ed25519_ragenix" ]; then
        echo "$HOME/.ssh/id_ed25519_ragenix already exists"
        exit 0
      fi
      mkdir -p "$HOME/.ssh"
      chmod 700 "$HOME/.ssh"
      ssh-keygen -q -t ed25519 -N "" -f "$HOME/.ssh/id_ed25519_ragenix" -C "$(id -un)@$(hostname)-ragenix"
      chmod 600 "$HOME/.ssh/id_ed25519_ragenix"
      chmod 644 "$HOME/.ssh/id_ed25519_ragenix.pub"
      echo "Created $HOME/.ssh/id_ed25519_ragenix"
      cat "$HOME/.ssh/id_ed25519_ragenix.pub"
    '';
  };

  secret-list = pkgs.writeShellApplication {
    name = "secret-list";
    runtimeInputs = [ pkgs.jq ];
    text = ''
      jq -r 'to_entries[] | "\(.key)	\(.value.relativeFile)	\(.value.recipientGroup)"' <<'EOF'
${catalogJson}
EOF
    '';
  };

  secret-edit = pkgs.writeShellApplication {
    name = "secret-edit";
    runtimeInputs = [ pkgs.jq ragenixPackage ];
    text = ''
      set -euo pipefail
      if [ "$#" -ne 1 ]; then
        echo "Usage: secret-edit <logical-secret-name>" >&2
        exit 1
      fi
      if [ ! -r "$HOME/.ssh/id_ed25519_ragenix" ]; then
        echo "Missing $HOME/.ssh/id_ed25519_ragenix. Run secret-edit-keygen first." >&2
        exit 1
      fi
      repo_root=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
      rel_file=$(jq -r --arg name "$1" '.[$name].relativeFile // empty' <<'EOF'
${catalogJson}
EOF
)
      if [ -z "$rel_file" ]; then
        echo "Unknown logical secret: $1" >&2
        exit 1
      fi
      exec ${ragenixPackage}/bin/ragenix --identity "$HOME/.ssh/id_ed25519_ragenix" --rules "$repo_root/secrets/rules.nix" --edit "$repo_root/$rel_file"
    '';
  };

  secret-rekey = pkgs.writeShellApplication {
    name = "secret-rekey";
    runtimeInputs = [ ragenixPackage ];
    text = ''
      set -euo pipefail
      if [ ! -r "$HOME/.ssh/id_ed25519_ragenix" ]; then
        echo "Missing $HOME/.ssh/id_ed25519_ragenix. Run secret-edit-keygen first." >&2
        exit 1
      fi
      repo_root=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
      exec ${ragenixPackage}/bin/ragenix --identity "$HOME/.ssh/id_ed25519_ragenix" --rules "$repo_root/secrets/rules.nix" --rekey
    '';
  };

  secrets-edit = pkgs.writeShellApplication {
    name = "secrets-edit";
    text = ''
      set -euo pipefail
      repo_root=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
      common_root=$(dirname "$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null || printf '%s/.git\n' "$repo_root")")
      mirror_path="''${GHOSTSHIP_SECRETS_MIRROR:-$repo_root/secrets.dec.yaml}"
      if [ ! -e "$mirror_path" ] && [ -e "$common_root/secrets.dec.yaml" ]; then
        mirror_path="$common_root/secrets.dec.yaml"
      fi
      mkdir -p "$(dirname "$mirror_path")"
      if [ ! -e "$mirror_path" ]; then
        : > "$mirror_path"
        chmod 600 "$mirror_path"
      fi
      editor="''${EDITOR:-vi}"
      exec "$editor" "$mirror_path"
    '';
  };

  secrets-list-keys = pkgs.writeShellApplication {
    name = "secrets-list-keys";
    runtimeInputs = [ pkgs.jq ];
    text = ''
      jq -r 'keys[]' <<'EOF'
${catalogJson}
EOF
    '';
  };

  secrets-reencrypt = pkgs.writeShellApplication {
    name = "secrets-reencrypt";
    runtimeInputs = [ pkgs.age pkgs.jq pkgs.yq-go ];
    text = ''
      set -euo pipefail
      repo_root=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
      common_root=$(dirname "$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null || printf '%s/.git\n' "$repo_root")")
      mirror_path="''${GHOSTSHIP_SECRETS_MIRROR:-$repo_root/secrets.dec.yaml}"
      if [ ! -e "$mirror_path" ] && [ -e "$common_root/secrets.dec.yaml" ]; then
        mirror_path="$common_root/secrets.dec.yaml"
      fi
      if [ ! -f "$mirror_path" ]; then
        echo "Missing plaintext mirror: $mirror_path" >&2
        exit 1
      fi

      catalog_json=$(cat <<'EOF'
${catalogJson}
EOF
)

      while IFS= read -r name; do
        rel_file=$(jq -r --arg name "$name" '.[$name].relativeFile' <<<"$catalog_json")
        plaintext=$(yq -r ".[\"$name\"] // \"\"" "$mirror_path")
        if [ -z "$plaintext" ]; then
          echo "Missing or empty plaintext entry for $name in $mirror_path" >&2
          exit 1
        fi
        tmp_plain=$(mktemp)
        trap 'rm -f "$tmp_plain"' EXIT
        printf '%s\n' "$plaintext" > "$tmp_plain"
        mapfile -t recipients < <(jq -r --arg name "$name" '.[$name].recipients[]' <<<"$catalog_json")
        age_args=()
        for recipient in "''${recipients[@]}"; do
          age_args+=("-r" "$recipient")
        done
        mkdir -p "$repo_root/$(dirname "$rel_file")"
        age -e "''${age_args[@]}" -o "$repo_root/$rel_file" "$tmp_plain"
        rm -f "$tmp_plain"
        trap - EXIT
        echo "Encrypted $name -> $rel_file"
      done < <(jq -r 'keys[]' <<<"$catalog_json")
    '';
  };
in
{
  options.ghostship.secretTooling = lib.mkOption {
    type = lib.types.attrs;
    readOnly = true;
    default = { };
    description = "Read-only metadata for the Ghostship secret editing workflow.";
  };

  config = {
    ghostship.secretTooling = {
      inherit recipients;
      editKeyPath = "/home/nixos/.ssh/id_ed25519_ragenix";
      rulesFile = "/home/nixos/nixos-config/secrets/rules.nix";
    };

    environment.systemPackages = [
      ragenixPackage
      secret-edit-keygen
      secret-edit
      secret-list
      secret-rekey
      secrets-edit
      secrets-list-keys
      secrets-reencrypt
    ];

    system.activationScripts.ghostship-ssh-host-public-key = {
      text = ''
        if [ -f /etc/ssh/ssh_host_ed25519_key.pub ]; then
          echo "SSH host ed25519 public key:"
          cat /etc/ssh/ssh_host_ed25519_key.pub
        fi
      '';
      supportsDryActivation = false;
    };
  };
}
