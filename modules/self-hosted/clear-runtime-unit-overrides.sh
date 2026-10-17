#!/usr/bin/env bash
# Remove runtime overrides of NixOS-declared units left by targeted
# activations and session guards, so a full switch runs exactly the generated
# units. Runtime masks (links to /dev/null) are deliberate and stay.
# Usage: clear-runtime-unit-overrides.sh RUNTIME_DIR DECLARED_DIR
set -eu
runtime=$1
declared=$2
[ -d "$runtime" ] || exit 0

for dropins in "$runtime"/*.d; do
  [ -d "$dropins" ] || continue
  unit=$(basename "$dropins" .d)
  [ -e "$declared/$unit" ] || continue
  for file in "$dropins"/*; do
    [ -e "$file" ] || [ -L "$file" ] || continue
    echo "removing runtime override $file"
    rm -f "$file"
  done
  rmdir "$dropins" 2>/dev/null || true
done

for link in "$runtime"/*; do
  [ -L "$link" ] || continue
  [ "$(readlink "$link")" = /dev/null ] && continue
  [ -e "$declared/$(basename "$link")" ] || continue
  echo "removing shadowed runtime unit $link"
  rm -f "$link"
done

for deps in "$runtime"/*.requires "$runtime"/*.wants; do
  [ -d "$deps" ] || continue
  for link in "$deps"/*; do
    if [ -L "$link" ] && [ ! -e "$link" ]; then
      echo "removing dangling runtime dependency $link"
      rm -f "$link"
    fi
  done
  rmdir "$deps" 2>/dev/null || true
done
