# Podman Auto-Update Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every self-hosted Podman container pull the latest image by default and add a daily native Podman auto-update job for the stack.

**Architecture:** Update each self-hosted container definition to set `pull = "always";` and the Podman registry auto-update label, then add a single shared systemd service/timer in `modules/self-hosted/common.nix` that runs `podman auto-update` once per day. Keep failure handling limited to systemd/journal for the first pass so the notification follow-up can be added later without changing the update mechanism.

**Tech Stack:** Nix flakes, NixOS modules, Podman, systemd timers, native `podman auto-update`

---

### Task 1: Add A Shared Native Podman Auto-Update Service

**Files:**
- Modify: `modules/self-hosted/common.nix`

- [x] **Step 1: Add the daily auto-update service and timer**

Write:
```nix
{ config, lib, pkgs, ... }:

{
  users.users.apps = {
    isSystemUser = true;
    uid = 3000;
    group = "apps";
    description = "Service user for self-hosted apps";
    shell = "/run/current-system/sw/bin/nologin";
  };
  users.groups.apps.gid = 3000;

  systemd.services.init-ghostship-net = {
    description = "Create ghostship_net podman network";
    after = [ "network.target" ];
    wantedBy = [ "multi-user.target" ];
    serviceConfig.Type = "oneshot";
    script = ''
      ${pkgs.podman}/bin/podman network inspect ghostship_net >/dev/null 2>&1 || \
      ${pkgs.podman}/bin/podman network create ghostship_net
    '';
  };

  systemd.services.podman-auto-update = {
    description = "Run native Podman auto-update for Ghostship containers";
    after = [ "network-online.target" "init-ghostship-net.service" ];
    wants = [ "network-online.target" "init-ghostship-net.service" ];
    serviceConfig = {
      Type = "oneshot";
      ExecStart = "${pkgs.podman}/bin/podman auto-update";
    };
  };

  systemd.timers.podman-auto-update = {
    description = "Daily native Podman auto-update for Ghostship containers";
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnCalendar = "daily";
      Persistent = true;
      RandomizedDelaySec = "30m";
    };
  };

  systemd.tmpfiles.rules = [
    "d /srv/apps 0755 apps apps -"
  ];
}
```

- [x] **Step 2: Parse-check the module**

Run:
```bash
nix-instantiate --parse modules/self-hosted/common.nix
```

Expected:
- parse succeeds

### Task 2: Add `pull = "always"` And Auto-Update Labels To Every Self-Hosted Container

**Files:**
- Modify: all `modules/self-hosted/*.nix` files that define `virtualisation.oci-containers.containers.*`

- [x] **Step 1: Add the pull policy and auto-update label to each container definition**

For each container, ensure the definition includes:

```nix
pull = "always";
labels = {
  "io.containers.autoupdate" = "registry";
};
```

If a container already has `labels`, merge the new label into the existing attrset instead of replacing the existing labels.

For example:

```nix
labels = {
  "io.containers.autoupdate" = "registry";
  "existing.label" = "value";
};
```

- [x] **Step 2: Parse-check representative container modules**

Run:
```bash
nix-instantiate --parse modules/self-hosted/hermes.nix
nix-instantiate --parse modules/self-hosted/homepage.nix
nix-instantiate --parse modules/self-hosted/cloudflared.nix
```

Expected:
- all parse checks succeed

### Task 3: Update Documentation And Agent Memory

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `AGENTS.md`

- [x] **Step 1: Document the daily Podman auto-update behavior in the README**

Add a short note in the self-hosted services or maintenance section that the stack uses native Podman auto-update and pulls `latest` images daily.

- [x] **Step 2: Add a changelog entry**

Write under `## Unreleased` / `### Changed`:

```md
- **Podman auto-update**: Every self-hosted OCI container now sets `pull = "always";` and carries Podman's registry auto-update label, and a daily native `podman auto-update` timer refreshes changed images in place. Failed restarts are still surfaced through systemd/journal for now.
```

- [x] **Step 3: Record the repo preference in AGENTS.md**

Add a short memory that the self-hosted Podman stack should default to `pull = "always";` and native auto-update.

### Task 4: Verify The Self-Hosted Host Builds Cleanly

**Files:**
- Verify: `modules/self-hosted/common.nix`
- Verify: all touched `modules/self-hosted/*.nix`
- Verify: `README.md`
- Verify: `CHANGELOG.md`
- Verify: `AGENTS.md`

- [x] **Step 1: Attempt to build `chill-penguin`**

Run:
```bash
nixos-rebuild build --flake .#chill-penguin
```

Expected:
- build/evaluation succeeds on an `aarch64-linux` host; this workspace is `x86_64-linux`, so the real build path cannot complete locally here

- [x] **Step 2: Confirm the generated config resolves as intended**

Run:
```bash
nix eval .#nixosConfigurations.chill-penguin.config.virtualisation.oci-containers.containers
```

Expected:
- every self-hosted container includes `pull = "always"`
- every self-hosted container includes `io.containers.autoupdate = "registry"`

- [ ] **Step 3: Commit the implementation**

Run:
```bash
git add modules/self-hosted/common.nix modules/self-hosted/*.nix README.md CHANGELOG.md AGENTS.md docs/superpowers/plans/2026-03-30-podman-auto-update.md
git commit -m "feat(podman): auto-update self-hosted images"
```

Expected:
- one implementation commit is created for the Podman auto-update rollout
