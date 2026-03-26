# Comprehensive Fleet Configuration Customization Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port all customized environment settings from `chill-penguin-root` into Nix modules using `ghostship-config` surgical updates. 

**Architecture:** 
- **Muximux**: Define all 30 portal sections in the exact order found on the server.
- **Homepage**: Define the group/service hierarchy, widgets, and docker sockets.
- **SearXNG**: Port custom engine list and valkey configuration.
- **NZBGet**: Port full Server 1/2 and Category definitions.
- **Recyclarr**: Port "Optimal" quality profiles and 20+ custom format mappings with scores.
- **Tautulli**: Port UI preferences and the specific link to the Ghostship Plex instance.
- **Arr Apps**: Enforce standard "Ghostship" settings (No SSL, No Browser, Docker Update).

---

### Task 1: Port Muximux (Ordered Portals)

**Files:**
- Modify: `modules/self-hosted/muximux.nix`

- [ ] **Step 1: Port all 30 portal links in exact order**
  Enforce settings for: Homepage, Arcane, Plex, NZBGet, VueTorrent, Sonarr, Radarr, Prowlarr, OpenWebUI, PriceGhost, MeTube, Manyfold, Synology, HomeAssistant, RomM, Tautulli, Huntarr, Bazarr, Booklore, Warracker, Fileflows, ActivePieces, ZeroByte, ConvertX, Syncthing, BentoPDF, IT Tools, Llama, SearXNG, SSH.

### Task 2: Port Homepage (Hierarchy & Widgets)

**Files:**
- Modify: `modules/self-hosted/homepage.nix`

- [ ] **Step 1: Port full 8-group hierarchy**
  Groups: Calendar, Plex, Library, Downloads, Utilities, Automation, Management, Infrastructure.
- [ ] **Step 2: Port custom widgets**
  Weather (the owner's local area), Resources, and SearXNG search widget.
- [ ] **Step 3: Port docker socket config**
  Enforce `chill-penguin` socket path.

### Task 3: Port Recyclarr (Optimal Profiles & Custom Formats)

**Files:**
- Modify: `modules/self-hosted/recyclarr.nix`

- [ ] **Step 1: Port Sonarr/Radarr "Optimal" profiles**
  Includes quality definitions and upgrade paths.
- [ ] **Step 2: Port 20+ Custom Format mappings**
  Port Trash IDs and specific scores for x265, x264, AV1, Atmos, DTS, etc.

### Task 4: Port NZBGet (Full Infrastructure)

**Files:**
- Modify: `modules/self-hosted/nzbget.nix`

- [ ] **Step 1: Port full Server 1 (Eweka) and Server 2 (UsenetPrime) config**
- [ ] **Step 2: Port category definitions (Sonarr, Radarr, Prowlarr)**
- [ ] **Step 3: Enforce `ControlPassword=""` and `UpdateCheck=none`**

### Task 5: Port SearXNG (Engines & Valkey)

**Files:**
- Modify: `modules/self-hosted/searxng.nix`

- [ ] **Step 1: Port full engine list**
  Include Google, DDG, Brave, Mojeek, Yep, Wikipedia, Arxiv, Anna's Archive.
- [ ] **Step 2: Enforce Valkey URL and search formats**

### Task 6: Port Tautulli (Plex Linking & UI)

**Files:**
- Modify: `modules/self-hosted/tautulli.nix`

- [ ] **Step 1: Enforce link to "Ghostship Plex"**
  Inject `pms_client_id`, `pms_identifier`, and `pms_token`.
- [ ] **Step 2: Port Home Library Cards and Stats Cards layout**

### Task 7: Finalize Arr Standard Keys

**Files:**
- Modify: `modules/self-hosted/sonarr.nix`, `radarr.nix`, `prowlarr.nix`

- [ ] **Step 1: Enforce `EnableSsl=False`, `LaunchBrowser=False`, `UpdateMechanism=Docker`**

---
