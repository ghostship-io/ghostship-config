# ghostship-config Utility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a surgical, idempotent configuration update utility in Python that supports multiple formats and secure secret handling via environment/file references.

**Architecture:** A standalone Python script with format-specific "drivers" that perform in-memory updates and a single idempotent write. Supports `env:`, `file:`, and `literal:` value prefixes.

**Tech Stack:** Python 3, `lxml` (XML), `ruamel.yaml` (YAML), `configparser` (INI), Nix (Derivation).

---

### Task 1: Initialize Core Script and Utility Functions

**Files:**
- Create: `modules/common/scripts/ghostship-config.py`

- [ ] **Step 1: Write the core script structure**
  Implement the argument parser, the `ValueResolver` (env/file/literal), and the main `ConfigManager` orchestration.

```python
import sys
import os
import argparse
import logging

class ValueResolver:
    @staticmethod
    def resolve(value):
        if value.startswith("env:"):
            var_name = value[4:]
            return os.environ.get(var_name, "")
        if value.startswith("file:"):
            path = value[5:]
            try:
                with open(path, "r") as f:
                    return f.read().strip()
            except Exception as e:
                logging.error(f"Failed to read secret from {path}: {e}")
                return ""
        if value.startswith("literal:"):
            return value[8:]
        return value

def main():
    parser = argparse.ArgumentParser(description="Surgical Config Updater")
    parser.add_argument("command", choices=["set"], help="Action to perform")
    parser.add_argument("file", help="Path to config file")
    parser.add_argument("patches", nargs="*", help="Key=Value pairs (prefix with env:, file:, or literal:)")
    parser.add_argument("--dry-run", action="store_true", help="Don't write to disk")
    parser.add_argument("--format", help="Override format detection")
    
    args = parser.parse_args()
    
    if not os.path.exists(args.file):
        print(f"File not found: {args.file}. Skipping.")
        sys.exit(0)

    # Core logic here...
    print(f"Updating {args.file}...")

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Commit**

```bash
git add modules/common/scripts/ghostship-config.py
git commit -m "feat(config): initialize ghostship-config core structure"
```

### Task 2: Implement XML Driver (Tags and Attributes)

**Files:**
- Modify: `modules/common/scripts/ghostship-config.py`

- [ ] **Step 1: Add XML support**
  Implement `XMLDriver` using `lxml`.

```python
from lxml import etree

class XMLDriver:
    def __init__(self, content):
        self.tree = etree.fromstring(content.encode("utf-8"))
        self.dirty = False

    def get(self, path):
        if "@" in path:
            tag_path, attr = path.rsplit(".@", 1)
            node = self.tree.find(tag_path.replace(".", "/"))
            return node.get(attr) if node is not None else None
        node = self.tree.find(path.replace(".", "/"))
        return node.text if node is not None else None

    def set(self, path, value):
        if "@" in path:
            tag_path, attr = path.rsplit(".@", 1)
            node = self.tree.find(tag_path.replace(".", "/"))
            if node is not None and node.get(attr) != value:
                node.set(attr, value)
                self.dirty = True
        else:
            node = self.tree.find(path.replace(".", "/"))
            if node is not None and node.text != value:
                node.text = value
                self.dirty = True

    def serialize(self):
        return etree.tostring(self.tree, pretty_print=True, encoding="unicode")
```

- [ ] **Step 2: Commit**

```bash
git commit -am "feat(config): add XML driver (tags and attributes)"
```

### Task 3: Implement YAML Driver

**Files:**
- Modify: `modules/common/scripts/ghostship-config.py`

- [ ] **Step 1: Add YAML support**
  Implement `YAMLDriver` using `ruamel.yaml`.

```python
from ruamel.yaml import YAML
from io import StringIO

class YAMLDriver:
    def __init__(self, content):
        self.yaml = YAML()
        self.yaml.preserve_quotes = True
        self.data = self.yaml.load(content)
        self.dirty = False

    def _get_node(self, path):
        parts = path.split(".")
        curr = self.data
        for part in parts:
            if isinstance(curr, dict) and part in curr:
                curr = curr[part]
            else:
                return None
        return curr

    def set(self, path, value):
        parts = path.split(".")
        curr = self.data
        for part in parts[:-1]:
            curr = curr.setdefault(part, {})
        
        if str(curr.get(parts[-1])) != str(value):
            curr[parts[-1]] = value
            self.dirty = True

    def serialize(self):
        stream = StringIO()
        self.yaml.dump(self.data, stream)
        return stream.getvalue()
```

- [ ] **Step 2: Commit**

```bash
git commit -am "feat(config): add YAML driver with comment preservation"
```

### Task 4: Implement INI and Quirky Drivers

**Files:**
- Modify: `modules/common/scripts/ghostship-config.py`

- [ ] **Step 1: Add INI support**
  Implement `INIDriver` and special handling for Muximux and qBittorrent.

```python
import configparser

class INIDriver:
    def __init__(self, content, php_header=False):
        self.header = ""
        if php_header and content.startswith("<?php"):
            self.header, content = content.split("\n", 1)
            self.header += "\n"
        
        self.config = configparser.ConfigParser(interpolation=None)
        self.config.optionxform = str # Preserve case
        self.config.read_string(content)
        self.dirty = False

    def set(self, path, value):
        section, key = path.split(".", 1)
        # Handle qBittorrent backslashes if needed
        key = key.replace(".", "\\") 
        if not self.config.has_section(section):
            self.config.add_section(section)
        
        if not self.config.has_option(section, key) or self.config.get(section, key) != str(value):
            self.config.set(section, key, str(value))
            self.dirty = True

    def serialize(self):
        stream = StringIO()
        self.config.write(stream)
        return self.header + stream.getvalue()
```

- [ ] **Step 2: Commit**

```bash
git commit -am "feat(config): add INI and Muximux drivers"
```

### Task 5: Implement Flat KV Driver

**Files:**
- Modify: `modules/common/scripts/ghostship-config.py`

- [ ] **Step 1: Add Flat KV support**
  Implement `KVDriver` for NZBGet and .env files.

```python
import re

class KVDriver:
    def __init__(self, content):
        self.lines = content.splitlines()
        self.dirty = False

    def set(self, key, value):
        pattern = re.compile(rf"^{re.escape(key)}\s*=\s*.*")
        new_line = f"{key}={value}"
        for i, line in enumerate(self.lines):
            if pattern.match(line):
                if line != new_line:
                    self.lines[i] = new_line
                    self.dirty = True
                return
        self.lines.append(new_line)
        self.dirty = True

    def serialize(self):
        return "\n".join(self.lines) + "\n"
```

- [ ] **Step 2: Commit**

```bash
git commit -am "feat(config): add Flat KV driver for NZBGet/.env"
```

### Task 6: Nix Derivation and System Integration

**Files:**
- Create: `modules/common/ghostship-config.nix`
- Modify: `modules/common/default.nix`

- [ ] **Step 1: Create the Nix derivation**

```nix
{ pkgs, ... }:

let
  ghostship-config = pkgs.writers.writePython3Bin "ghostship-config" {
    libraries = with pkgs.python3Packages; [
      lxml
      ruamel-yaml
    ];
  } (builtins.readFile ./scripts/ghostship-config.py);
in
{
  environment.systemPackages = [ ghostship-config ];
}
```

- [ ] **Step 2: Integrate into `modules/common/default.nix`**
  Import `./ghostship-config.nix`.

- [ ] **Step 3: Commit**

```bash
git add modules/common/ghostship-config.nix modules/common/default.nix
git commit -m "feat(nix): package ghostship-config and add to system packages"
```

### Task 7: Migrate Services (Proof of Concept)

**Files:**
- Modify: `modules/self-hosted/sonarr.nix`
- Modify: `modules/self-hosted/tautulli.nix`

- [ ] **Step 1: Update Sonarr activation script**
  Replace `yq` calls with `ghostship-config`.

- [ ] **Step 2: Update Tautulli activation script**
  Replace `yq` calls with `ghostship-config`.

- [ ] **Step 3: Commit**

```bash
git commit -am "refactor(self-hosted): migrate Sonarr and Tautulli to ghostship-config"
```

### Task 8: Comprehensive Migration

**Files:**
- Modify: All remaining `self-hosted` modules with activation scripts.

- [ ] **Step 1: Migrate Radarr, Prowlarr, Plex, Bazarr, etc.**
  (Repeat for all modules identified in audit).

- [ ] **Step 2: Commit**

```bash
git commit -am "refactor(self-hosted): complete migration to ghostship-config"
```

---
