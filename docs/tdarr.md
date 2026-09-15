# Tdarr pilot

The encoder must run on the existing Chill Penguin server and target HEVC;
an external worker is outside the selected design.

The Nix-managed `tdarr` service uses the shared `ghostship_net` network at
`http://tdarr:8265`; no host ports or public endpoint are exposed. The upstream
ARM64 image contains the server and an internal CPU node. Its root startup
initializes ownership, then uses apps UID/GID 3000. The pilot intentionally
omits auto-update until an image/flow combination has passed validation.

Production movies and TV are read-only under `/source`. Only copied samples
under `/srv/apps/tdarr/pilot` (`/media` inside Tdarr) may be replaced. Cache and
application state live under `/srv/apps/tdarr`. The node starts paused, with
one CPU transcode worker, no GPU workers, a two-CPU quota and a 6 GiB RAM cap.
The M1 Ultra's Linux video encoder is not supported; do not assume GPU device
passthrough supplies hardware encoding.

## Pilot completion

Stage representative copies (grain, animation, foreign dialogue, subtitles,
ordinary TV, high-bitrate remux). Configure a flow only for `/media`; preserve
original-language audio and English full/forced subtitles. Start with HEVC
quality-based encoding, AC-3 up to 5.1 plus optional AAC stereo, and retained
subtitle/attachment/chapter metadata. Validate full decode, duration, stream
inventory, meaningful savings and playback on the user's Samsung, Apple TV,
Android/Google TV, iPhone and browser clients. No production replacement is
enabled by this module.

Visual quality takes precedence over reaching a fixed file size. Begin the
pilot at x265 CRF 20 with a slow preset and test grain/dark/motion sequences;
this is lossy encoding, not a promise of identical quality. Preserve an
existing efficient encode or reject an output with insufficient savings.
Never upscale, change frame rate, or automatically convert HDR/interlaced
sources in the first production policy.

Audio must have at most six channels (5.1). Preserve mono/stereo and compatible
original-language tracks. Downmix higher-channel layouts with a tested matrix;
check dialogue and levels before replacement. Remove unrelated dubbed audio
by default, retaining English full/forced subtitles. Original multilingual
dialogue, commentary or historically meaningful alternate tracks warrant
review. Resolve original language from authoritative item metadata and inspect
stream tags/title; missing or contradictory tags require review, not deletion.
An English dub is not required for foreign films. Both commentary and main
tracks must satisfy the channel limit.

Before production, add persistent source fingerprints/policy versions,
bounded disk reservations, import events plus periodic NFS reconciliation,
source-change detection, Plex activity throttling, validation gates, staged
NAS replacement with recoverable originals, and Radarr/Sonarr/Plex refresh.
Review the arr upgrade policy to prevent repeated download/encode loops.
Keep originals outside scanned libraries for 7–14 days with a quota. Never
overwrite in place or treat a zero encoder exit code as a health check.

Use the T3 session guard in `container-workflow.md` for activation. If a full
switch affects T3 Code, use only the generated Tdarr unit with a retained GC
root and report full-system activation as deferred.
