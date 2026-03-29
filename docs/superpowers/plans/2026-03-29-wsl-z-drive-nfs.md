# WSL Z Drive NFS Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the WSL-only `/mnt/z` SMB/CIFS mount path with a direct Synology NFS mount that reuses `chill-penguin`'s tuning and fails gracefully off-network.

**Architecture:** Keep the change scoped to the existing WSL host import path by replacing the imperative `mount-z` script in `modules/develop/wsl-mounts.nix` with a declarative `fileSystems."/mnt/z"` NFS entry. Remove the now-unused SMB secret declaration, and update docs so the repo describes `/mnt/z` as a WSL-only direct NFS mount.

**Tech Stack:** Nix flakes, NixOS modules, systemd automount, NFS v4.1, README/CHANGELOG/skill docs

---

### Task 1: Replace WSL SMB Mounting With Declarative NFS

**Files:**
- Modify: `modules/develop/wsl-mounts.nix`

- [ ] **Step 1: Confirm only WSL hosts import the WSL mount module**

Run:
```bash
rg -n "../../modules/develop/default.nix" hosts
```

Expected:
- output lists only `hosts/launch-octopus/default.nix`
- output lists only `hosts/armored-armadillo/default.nix`

- [ ] **Step 2: Replace the imperative SMB script/service with a declarative NFS mount**

Write:
```nix
{ pkgs, ... }:

{
  environment.systemPackages = with pkgs; [
    nfs-utils
  ];

  fileSystems."/mnt/z" = {
    device = "192.168.200.106:/volume1/share";
    fsType = "nfs";
    options = [
      "nofail"
      "x-systemd.automount"
      "noatime"
      "nodiratime"
      "soft"
      "intr"
      "timeo=30"
      "retrans=2"
      "rsize=1048576"
      "wsize=1048576"
      "nfsvers=4.1"
      "async"
      "tcp"
      "actimeo=120"
    ];
  };
}
```

- [ ] **Step 3: Verify the module parses cleanly**

Run:
```bash
nix-instantiate --parse modules/develop/wsl-mounts.nix
```

Expected:
- parse succeeds and prints the normalized Nix expression

### Task 2: Remove Obsolete SMB Secret Wiring

**Files:**
- Modify: `modules/develop/secrets.nix`

- [ ] **Step 1: Confirm `smb-secrets` is only used by the old WSL mount path**

Run:
```bash
rg -n "smb-secrets|SMB_SERVER|SMB_SHARE|mount.cifs" .
```

Expected:
- the only live module dependency is the old WSL mount path
- no other runtime module still depends on `smb-secrets`

- [ ] **Step 2: Remove the obsolete `smb-secrets` declaration**

Write:
```nix
{ ... }:

{
  sops.secrets = { };
}
```

- [ ] **Step 3: Verify the secrets module parses cleanly**

Run:
```bash
nix-instantiate --parse modules/develop/secrets.nix
```

Expected:
- parse succeeds and prints the normalized Nix expression

### Task 3: Update Repo Documentation To Match

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `home/config/skills/wsl2/SKILL.md`

- [ ] **Step 1: Update README language for `/mnt/z`**

Write:
```md
- **Z Mount (`/mnt/z`)**: WSL2 hosts mount the shared Synology export directly over NFS with systemd automounting for better performance and graceful off-network behavior.
```

Place it in the WSL2 Integration section.

- [ ] **Step 2: Add a changelog entry**

Write under `## Unreleased` / `### Changed`:
```md
- **WSL `/mnt/z` NFS mount**: Replaced the WSL-only `Z:`-backed SMB mount script with a direct Synology NFS automount at `/mnt/z`, reusing the tuned `chill-penguin` mount options so access is faster on-network and fails gracefully when the NAS is unavailable or the host is off-network.
```

- [ ] **Step 3: Update the WSL2 skill description**

Replace the existing Z-drive note with:
```md
- **Z Mount (`/mnt/z`)**: Managed as a direct NFS mount on WSL hosts. It is mounted lazily via systemd automount, so always check whether it is currently mounted before assuming the share is available.
```

### Task 4: Verify WSL Hosts Evaluate After The Change

**Files:**
- Verify: `modules/develop/wsl-mounts.nix`
- Verify: `modules/develop/secrets.nix`
- Verify: `README.md`
- Verify: `CHANGELOG.md`
- Verify: `home/config/skills/wsl2/SKILL.md`

- [ ] **Step 1: Build `launch-octopus`**

Run:
```bash
nixos-rebuild build --flake .#launch-octopus
```

Expected:
- build/evaluation succeeds

- [ ] **Step 2: Build `armored-armadillo`**

Run:
```bash
nixos-rebuild build --flake .#armored-armadillo
```

Expected:
- build/evaluation succeeds

- [ ] **Step 3: Review the final diff**

Run:
```bash
git diff -- modules/develop/wsl-mounts.nix modules/develop/secrets.nix README.md CHANGELOG.md home/config/skills/wsl2/SKILL.md
```

Expected:
- diff shows only the WSL-only NFS mount change, SMB secret cleanup, and matching documentation updates

- [ ] **Step 4: Commit the implementation**

Run:
```bash
git add modules/develop/wsl-mounts.nix modules/develop/secrets.nix README.md CHANGELOG.md home/config/skills/wsl2/SKILL.md
git commit -m "feat(wsl): mount z over nfs"
```

Expected:
- a single implementation commit is created with the WSL-only NFS change
