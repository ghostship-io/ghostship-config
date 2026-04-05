#!/usr/bin/env nix-shell
#!nix-shell -i bash -p age jq nixos-install-tools

set -euo pipefail

hostname_value="${1:-$(hostname)}"
json_path="${2:-}"

if [ "$(id -u)" -ne 0 ]; then
  echo "Error: run bootstrap as root so it can manage /etc/nix/secrets/age.key." >&2
  exit 1
fi

install -d -m 700 /etc/nix/secrets

if [ ! -f /etc/nix/secrets/age.key ]; then
  age-keygen -o /etc/nix/secrets/age.key
fi

age_public_key="$(age-keygen -y /etc/nix/secrets/age.key)"

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
    printf 'Warning: could not update the live hostname; continuing with requested hostname in bootstrap JSON.\n' >&2
  fi
fi

if [ -f /etc/nixos/hardware-configuration.nix ]; then
  hardware_config="$(cat /etc/nixos/hardware-configuration.nix)"
else
  hardware_config="$(nixos-generate-config --show-hardware-config)"
fi

json="$(
  jq -n \
    --arg hostname "$hostname_value" \
    --arg public_key "$age_public_key" \
    --arg hw_config "$hardware_config" \
    '{hostname: $hostname, public_key: $public_key, hardware_config: $hw_config}'
)"

if [ -n "$json_path" ]; then
  install -d -m 755 "$(dirname "$json_path")"
  printf '%s\n' "$json" > "$json_path"
else
  printf '%s\n' "$json"
fi
