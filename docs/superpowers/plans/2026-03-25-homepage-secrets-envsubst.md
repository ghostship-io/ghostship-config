# Homepage Secrets Envsubst Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move all Homepage widget secrets into one sops-managed env file and render `services.yaml` through `envsubst` during activation.

**Architecture:** Store every Homepage secret in a single `homepage-secrets` entry in `secrets.yaml` as shell-style `KEY=value` lines. Have `homepage.nix` read that one sops secret, export it in the activation script, and render a YAML template with `envsubst` instead of performing placeholder replacement loops.

**Tech Stack:** NixOS, `sops-nix`, `envsubst` from `gettext`, shell activation scripts, `yq-go` for existing YAML edits.

---

### Task 1: Consolidate Homepage secrets

**Files:**
- Modify: `secrets.yaml`
- Modify: `modules/self-hosted/secrets.nix`

- [ ] **Step 1: Replace individual Homepage secret entries with one `homepage-secrets` entry**
- [ ] **Step 2: Encrypt the new secret value through sops**
- [ ] **Step 3: Update `sops.secrets` to expose only the combined Homepage secret**

### Task 2: Render Homepage services from a template

**Files:**
- Modify: `modules/self-hosted/homepage.nix`

- [ ] **Step 1: Add a `services.yaml.tpl` text template with `${VAR}` placeholders**
- [ ] **Step 2: Read and export the combined Homepage secret during activation**
- [ ] **Step 3: Use `envsubst` to render the template to `services.yaml`**
- [ ] **Step 4: Remove placeholder replacement logic and any leftover secret rewrites**

### Task 3: Verify the configuration update

**Files:**
- Modify: `modules/self-hosted/homepage.nix`
- Modify: `modules/self-hosted/secrets.nix`
- Modify: `secrets.yaml`

- [ ] **Step 1: Run diff checks and confirm no Homepage secrets remain hardcoded**
- [ ] **Step 2: Confirm the Nix evaluation/build path is still clean aside from the known `/boot/asahi` issue**
- [ ] **Step 3: Commit the change set**
