# Fleet-Wide Surgical Configuration Migration Plan

> **For agentic workers:** Historical note: this archived plan predates the current repo-local OpenSpec workflow.

**Goal:** Convert all self-hosted services to a "Pure Surgical" configuration model using `ghostship-config`. Remove all full-file templates, `cp`, `install`, and `envsubst` logic. Enforce the "Ghostship Standard" (identity, privacy, secrets).

**Architecture:** 
1. Activation scripts check for config existence.
2. If exists, apply surgical patches via `ghostship-config`.
3. If missing, skip (let app initialize on first run).
4. No full-file overwrites or template logic remains in Nix.

**Tech Stack:** NixOS, `ghostship-config` utility.

---

### Task 1: Migrate "Arr" Apps (Sonarr, Radarr, Prowlarr)

**Files:**
- Modify: `modules/self-hosted/sonarr.nix`
- Modify: `modules/self-hosted/radarr.nix`
- Modify: `modules/self-hosted/prowlarr.nix`

- [ ] **Step 1: Update Sonarr activation script**
  Enforce Ghostship Standard (InstanceName, Analytics, UpdateMechanic).

- [ ] **Step 2: Update Radarr activation script**
  Enforce Ghostship Standard.

- [ ] **Step 3: Update Prowlarr activation script**
  Enforce Ghostship Standard.

- [ ] **Step 4: Commit**
```bash
git commit -am "refactor(arr): surgically enforce Ghostship Standard for Sonarr, Radarr, Prowlarr"
```

### Task 2: Migrate Bazarr and NZBGet (Remove Templates)

**Files:**
- Modify: `modules/self-hosted/bazarr.nix`
- Modify: `modules/self-hosted/nzbget.nix`

- [ ] **Step 1: Clean up Bazarr**
  Remove `bazarr-config-yaml` and `bazarr-config-script`. Update activation script to patch existing file only. Enforce `general.instance_name="Ghostship Bazarr"` and `analytics.enabled=literal:false`.

- [ ] **Step 2: Clean up NZBGet**
  Remove `nzbget-conf-template` and `nzbget-config-script`. Update activation script to patch existing file only. Enforce `ControlUsername=literal:ghostship`.

- [ ] **Step 3: Commit**
```bash
git commit -am "refactor(self-hosted): remove Bazarr and NZBGet full-file templates"
```

### Task 3: Migrate Plex and Tautulli

**Files:**
- Modify: `modules/self-hosted/plex.nix`
- Modify: `modules/self-hosted/tautulli.nix`

- [ ] **Step 1: Update Plex activation script**
  Already using surgical updates, but ensure `Preferences.@FriendlyName=literal:"Ghostship Plex"` is enforced.

- [ ] **Step 2: Update Tautulli activation script**
  Ensure `PMS.pms_name=literal:"Ghostship Plex"` is enforced.

- [ ] **Step 3: Commit**
```bash
git commit -am "refactor(plex): enforce Ghostship Identity for Plex and Tautulli"
```

### Task 4: Migrate RomM and RomM-DB

**Files:**
- Modify: `modules/self-hosted/romm.nix`
- Modify: `modules/self-hosted/romm-db.nix`

- [ ] **Step 1: Update RomM**
  Remove `romm-config-yaml`. Activation script should only patch `config.yml` and `romm.env` if they exist.

- [ ] **Step 2: Update RomM-DB**
  Update activation script to patch `MYSQL_PASSWORD` in `romm-db.env` surgically.

- [ ] **Step 3: Commit**
```bash
git commit -am "refactor(romm): switch to pure surgical env/yaml patching"
```

### Task 5: Migrate Homepage (Pure Surgical)

**Files:**
- Modify: `modules/self-hosted/homepage.nix`

- [ ] **Step 1: Remove all Homepage templates**
  Remove `homepage-services-yaml`, `homepage-widgets-yaml`, `homepage-bookmarks-yaml`, and `homepage-docker-yaml`.

- [ ] **Step 2: Update activation script**
  Only use `ghostship-config` to inject API keys into `services.yaml` if it exists. (e.g., `services[name=Sonarr].widget.key=env:HOMEPAGE_SONARR_KEY`).

- [ ] **Step 3: Commit**
```bash
git commit -am "refactor(homepage): move to pure surgical dashboard management"
```

### Task 6: Migrate SearXNG, Recyclarr, and PAL

**Files:**
- Modify: `modules/self-hosted/searxng.nix`
- Modify: `modules/self-hosted/recyclarr.nix`
- Modify: `modules/self-hosted/plex-auto-languages.nix`

- [ ] **Step 1: Update SearXNG**
  Remove `searxng-settings-yaml`. Patch `general.instance_name="Ghostship Search"` and `server.secret_key` surgically.

- [ ] **Step 2: Update Recyclarr**
  Remove `recyclarr-yaml`. Patch API keys surgically.

- [ ] **Step 3: Update PAL**
  Remove `pal-config-yaml`. Patch plex token surgically.

- [ ] **Step 4: Commit**
```bash
git commit -am "refactor(self-hosted): finalize surgical migration for SearXNG, Recyclarr, PAL"
```

### Task 7: Migrate Muximux and VueTorrent

**Files:**
- Modify: `modules/self-hosted/muximux.nix`
- Modify: `modules/self-hosted/vuetorrent.nix`

- [ ] **Step 1: Update Muximux**
  Remove `muximux-settings`. Patch `general.title="ghostship.io"` surgically.

- [ ] **Step 2: Update VueTorrent**
  Ensure all `sed` replacements are fully converted to `ghostship-config`.

- [ ] **Step 3: Commit**
```bash
git commit -am "refactor(self-hosted): complete pure surgical migration"
```

---
