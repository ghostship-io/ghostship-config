#!/usr/bin/env nix-shell
#!nix-shell -i bash -p jq nixos-install-tools openssh

set -euo pipefail

if [ "$#" -lt 1 ] || [ -z "${1:-}" ]; then
  echo "Usage: sudo ./bootstrap.sh <hostname> [output-dir]" >&2
  exit 1
fi

hostname_value="$1"
output_dir="${2:-./${hostname_value}-host-intake}"

if [ "$(id -u)" -ne 0 ] || [ -z "${SUDO_USER:-}" ]; then
  echo "Error: run bootstrap with sudo so it can read or generate SSH host keys." >&2
  exit 1
fi

hostname_set=false
hostnamectl_error=""

if command -v hostnamectl >/dev/null 2>&1; then
  if hostnamectl_error="$(hostnamectl set-hostname "$hostname_value" 2>&1)"; then
    hostname_set=true
  fi
fi

if [ "$hostname_set" = false ] && command -v hostname >/dev/null 2>&1; then
  if hostname "$hostname_value"; then
    hostname_set=true
  fi
fi

if [ "$hostname_set" = false ] && [ -w /proc/sys/kernel/hostname ]; then
  if { printf '%s\n' "$hostname_value" > /proc/sys/kernel/hostname; } 2>/dev/null; then
    hostname_set=true
  fi
fi

if [ "$hostname_set" = false ]; then
  if [ -n "$hostnamectl_error" ]; then
    printf 'Warning: could not update the live hostname: %s\n' "$hostnamectl_error" >&2
  else
    printf 'Warning: could not update the live hostname; continuing with requested hostname in capture bundle.\n' >&2
  fi
fi

is_wsl=false
if grep -qiE '(microsoft|wsl)' /proc/sys/kernel/osrelease 2>/dev/null; then
  is_wsl=true
fi

if [ ! -f /etc/ssh/ssh_host_ed25519_key.pub ]; then
  echo "Generating SSH host keys..." >&2
  ssh-keygen -A >/dev/null
fi

if [ ! -f /etc/ssh/ssh_host_ed25519_key.pub ]; then
  echo "Error: missing /etc/ssh/ssh_host_ed25519_key.pub after host-key generation." >&2
  exit 1
fi

if [ -f /etc/nixos/hardware-configuration.nix ]; then
  hardware_config="$(cat /etc/nixos/hardware-configuration.nix)"
else
  hardware_config="$(nixos-generate-config --show-hardware-config)"
fi

hardware_platform="$(uname -m)"
kernel_release="$(uname -r)"
generated_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

install -d -m 755 "$output_dir" "$output_dir/public"
printf '%s\n' "$hardware_config" > "$output_dir/hardware-configuration.nix"
cp /etc/ssh/ssh_host_ed25519_key.pub "$output_dir/public/ssh_host_ed25519_key.pub"
chmod 644 "$output_dir/public/ssh_host_ed25519_key.pub"

jq -n \
  --arg hostname "$hostname_value" \
  --arg generated_at "$generated_at" \
  --arg hardware_config "hardware-configuration.nix" \
  --arg ssh_host_public_key "public/ssh_host_ed25519_key.pub" \
  --argjson is_wsl "$is_wsl" \
  '{hostname: $hostname, generated_at: $generated_at, hardware_config: $hardware_config, ssh_host_public_key: $ssh_host_public_key, is_wsl: $is_wsl}' \
  > "$output_dir/manifest.json"

jq -n \
  --arg hostname "$hostname_value" \
  --arg system "$hardware_platform" \
  --arg kernel_release "$kernel_release" \
  --argjson is_wsl "$is_wsl" \
  '{hostname: $hostname, system: $system, kernel_release: $kernel_release, is_wsl: $is_wsl}' \
  > "$output_dir/facts.json"

cat > "$output_dir/bootstrap-notes.md" <<EOF
# Host Intake Bundle

Copy this directory into the repo at `references/host-intake/${hostname_value}/`,
then ask Codex to integrate the host into the repo. Remove the temporary
intake directory after Codex finishes the integration.
EOF

printf 'Created host intake bundle at %s\n' "$output_dir"
printf 'Next steps:\n' >&2
printf '1. Copy %s into the repo at references/host-intake/%s/\n' "$output_dir" "$hostname_value" >&2
printf '2. Ask Codex to integrate the staged intake bundle.\n' >&2
printf '3. Review and commit the resulting repo changes, then remove the temporary intake directory.\n' >&2
