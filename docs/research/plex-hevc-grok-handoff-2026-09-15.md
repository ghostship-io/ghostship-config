# Plex HEVC pipeline handoff for Grok

Resume in `/workspace/nixos-config-tdarr` on
`feat/tdarr-pilot-session-safe`. The branch is clean at `a38924dd` and is
pushed to `origin/feat/tdarr-pilot-session-safe`. Its two commits are:

- `532d98af feat: add session-safe HEVC encoding pilot`
- `a38924dd feat: configure guarded Plex HEVC flow`

## Hard guardrail

Preserve the active T3 Code session through every nixos-config operation.
Keep `podman-t3code.service`, the `t3code` container, and its inner runtime
running. Use the targeted-unit process in `docs/container-workflow.md`; do not
run a full switch until its dry activation and all hooks prove T3 remains
running.

Baseline recorded before and verified after the Tdarr-only restart:

```text
t3code container ID: 1047746b6c2ec97369f7bdfd8591a7d52911edd081f17ff80066a0faab5d6480
started: 2026-09-08 13:42:42.875919347 +0000 UTC
podman-t3code MainPID: 1371704
```

The target is root SSH alias `chill-penguin`. The committed host worktree is
`/home/nixos/nixos-config-tdarr-pilot` at `a38924dd`.

## User policy

- Encode on the existing M1 Ultra server; no external worker.
- Use HEVC for storage savings while protecting visual quality.
- Aim near 10 GiB for a two-hour 1080p title and reject output above roughly
  20 GiB per two hours rather than lowering quality further.
- Keep original-language audio. Retain mono/stereo and cap every retained
  track at 5.1. Remove unrelated dubs unless commentary or another meaningful
  alternate warrants review.
- Foreign-language titles require English subtitles; an English dub is not
  required.
- Serve home and remote Plex clients including Samsung, Apple TV,
  Android/Google TV, iPhone, and browsers.

## Live state

The deployment is runtime-only and survives garbage collection through these
roots, but it does not survive a reboot until a safe full NixOS activation:

```text
/nix/var/nix/gcroots/tdarr-pilot-unit
  -> /nix/store/6w7wx9liq1g8mjwddy1p8sx92pvanwbc-unit-podman-tdarr.service
/nix/var/nix/gcroots/tdarr-policy-unit
  -> /nix/store/s21b0gls1xwma67zl4jvxqlg5a8hm9xd-unit-tdarr-language-policy.service
/nix/var/nix/gcroots/tdarr-policy-timer-unit
  -> /nix/store/nafzdqavff92q398z6y4marjxsgiqkl8-unit-tdarr-language-policy.timer
```

Observed immediately before this handoff:

- `podman-tdarr.service`: active and healthy.
- `tdarr-language-policy.timer`: active, hourly with jitter.
- Container limit: eight CPUs and 12 GiB RAM.
- Internal node `9kvP5w3`: paused, one CPU transcode worker, no GPU workers.
- Flow `plex-hevc-guarded-v1`: present with 13 plugins and 14 edges.
- Pilot library `plex-hevc-pilot`: `/media`, cache `/temp/pilot`, flow selected.
- Policy contains 1,424 Radarr/Sonarr roots, including 36 Korean and 20
  Chinese roots. It reads local SQLite databases without API credentials and
  writes atomically.
- Production Movies and TV mounts are read-only. No production media changed.

The upstream container's bundled x265 reported a 32-bit/no-assembly build and
managed about 0.4 fps under two CPUs. The deployed node now uses pinned Nix
FFmpeg 9.0.1 through the read-only `/nix/store` mount. Its binary tests pass.
A deliberately interrupted native CRF 20 slow test reached about 9 fps under
eight CPUs while Plex background detection jobs were running. Measure a full
sample before estimating backlog completion.

## First fix

The custom flow plugins are not loadable yet. This read-only API check:

```sh
ssh chill-penguin 'podman exec tdarr curl -fsS \
  -H "Content-Type: application/json" \
  --data "{\"data\":{\"string\":\"Plex\",\"pluginType\":\"Local\"}}" \
  http://127.0.0.1:8265/api/v2/search-flow-plugins'
```

returns two `Read error` rows with `pluginName` equal to `1.0.0`. Tdarr expects
a category layer beneath `LocalFlowPlugins`. Move the source files from:

```text
tdarr-plugins/plexPolicy/1.0.0/index.js
tdarr-plugins/plexValidate/1.0.0/index.js
```

to:

```text
tdarr-plugins/ghostship/plexPolicy/1.0.0/index.js
tdarr-plugins/ghostship/plexValidate/1.0.0/index.js
```

That extra level also requires changing `plexPolicy`'s methods import from
`../../../../methods/lib` back to `../../../../../methods/lib`. Verify the API
then returns `plexPolicy` and `plexValidate` with their real names and version.
Do not unpause the node until this passes.

There is one disposable partial benchmark output at:

```text
/srv/apps/tdarr/pilot/bridge-native-crf20-slow.mkv (5,065,257 bytes)
```

Remove that exact file before scanning the pilot library. It is not library
media and was cut short by the benchmark stop.

## What the flow is designed to do

`modules/self-hosted/tdarr-language-policy.py` maps Radarr movie roots and
Sonarr series roots to accepted ISO language tags. Unknown metadata routes to
review.

`plexPolicy` accepts only SDR, progressive video at 1080p or below. It encodes
non-HEVC files above the duration-scaled 10 GiB threshold with libx265 CRF 20,
slow preset, and bounded x265 threads. Smaller H.264 video can be copied when
only its audio needs repair. Existing HEVC is copied unless another stream
needs modification. HDR, interlaced video, missing audio language tags,
missing original-language audio, and commentary-like track titles route to
manual review.

Compatible AAC, AC-3, and E-AC-3 original-language tracks at 5.1 or below are
copied. Other original-language audio is converted to AC-3 at a channel-scaled
bitrate and at most six channels. Unrelated audio languages are removed.
English and original-language subtitles are kept; other tagged subtitles are
removed.

After encoding, `plexValidate` checks codec behavior, unchanged dimensions,
audio channel and language policy, English subtitles on foreign titles, at
least 15% savings for a video encode, a 20% lower-bound sanity check, and the
duration-scaled 20 GiB ceiling. Tdarr also checks duration within 99.9–100.1%
and fully decodes the output. A valid item then waits at `Require Review`.
Only approval replaces the staged pilot input.

The production roots remain read-only. The built-in replace plugin deletes its
`.partial.old` original immediately, so it is acceptable only for disposable
pilot copies. Production needs a separate rollback implementation.

## Resume sequence

1. Fix the local plugin layout and import path. Run `node --check` on both
   plugins, `python -m py_compile` on the policy generator, `jq -e` on the flow,
   `git diff --check`, and `nix develop .#ci -c scripts/check`. Completion means
   all checks pass.
2. Commit and push the fix. Update the committed host worktree, rebuild the
   three exact units above, retain their GC roots, and relink them with
   `systemctl link --runtime --force`. Restart only `podman-tdarr.service`.
   Completion means Tdarr is healthy, native FFmpeg passes its binary test,
   both local plugins load, the flow/library records exist, and the T3 baseline
   is unchanged.
3. Remove the partial benchmark file. Create a 30–60 second H.264 test input by
   stream-copying a representative source into a new subdirectory below
   `/srv/apps/tdarr/pilot`. Keep the production source read-only. Start with an
   English-original sample because the pilot flow input currently uses
   `eng,en`; explicitly change that pilot input for a Korean or Chinese sample.
4. Before each encode, distinguish real Plex playback from background paths
   under `Cache/Transcode/Detection`. Defer for active viewing sessions. Keep
   the node paused except for the bounded test.
5. Scan only `plex-hevc-pilot`, unpause node `9kvP5w3`, and watch one item reach
   the review stage. Confirm the job report used Nix FFmpeg, CRF 20 slow, the
   intended stream maps, duration and size gates, and the full decode. Re-pause
   the node before approving the disposable staged copy.
6. Probe the replaced staged copy and play it on the actual client families.
   Record throughput, source/output size, stream inventory, and visible/audio
   problems. Repeat with grain, dark motion, animation, foreign dialogue,
   forced subtitles, and over-5.1 audio. Completion means the policy has passed
   representative files and actual Plex clients.
7. Before production, add active-playback throttling, persistent source
   fingerprints and policy versions, cache/NAS free-space reservations,
   source-change race checks, bounded retries, 7–14 day rollback storage with
   quota, and Radarr/Sonarr/Plex refresh without creating upgrade loops. Then
   make production mounts writable only for the validated atomic replacement
   service. Keep the review gate until the user accepts the client tests.
8. Prepare the full NixOS activation only after inspecting
   `switch-to-configuration dry-activate`, T3 unit changes, dependency restarts,
   auto-update hooks, and imperative activation hooks. Completion means the
   service survives reboot and the recorded T3 container identity, start time,
   and MainPID remain unchanged.

## Verification already completed

`nix develop .#ci -c scripts/check` passed after `a38924dd`, including Nix
syntax, workflow scripts, both Linux development shells, and all four host
evaluations. The JSON, Python syntax, JavaScript syntax, and staged diff checks
also passed. Live checks proved service health, the CPU/memory limits, native
FFmpeg selection, read-only production mounts, policy generation, flow/library
bootstrap, paused workers, and unchanged T3 state. The custom plugin discovery
failure above is the remaining blocker to an end-to-end pilot.
