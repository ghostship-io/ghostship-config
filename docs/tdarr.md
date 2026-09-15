# Tdarr pilot

The encoder must run on the existing Chill Penguin server and target HEVC;
an external worker is outside the selected design.

The Nix-managed `tdarr` service uses the shared `ghostship_net` network at
`http://tdarr:8265`; no host ports or public endpoint are exposed. The pinned
ARM64 image contains the server and an internal CPU node. Its root startup
initializes ownership, then uses apps UID/GID 3000. The pilot intentionally
omits auto-update until an image/flow combination has passed validation.

Production movies and TV are read-only under `/source`. Only copied samples
under `/srv/apps/tdarr/pilot` (`/media` inside Tdarr) may be replaced. Cache and
application state live under `/srv/apps/tdarr`. The node runs one CPU
transcode worker and no GPU or health-check workers, with an eight-CPU quota
and a 12 GiB RAM cap. Do not pause for Plex playback. Encodes write to cache
while the original stays in place; after review, `plexReplace` copies beside
it and atomically renames over the original so the path is never empty. The
library schedule is enabled for every hour. It uses Nix's native ARM64 FFmpeg because the image's bundled x265 build
was about 20 times slower in the initial test. The M1 Ultra's Linux video
encoder is not supported; do not assume GPU device passthrough supplies
hardware encoding.

`tdarr-language-policy.service` reads the local Radarr and Sonarr SQLite
databases without API credentials and atomically publishes their original
language metadata to Tdarr. An hourly timer reconciles changes. Missing or
unknown metadata routes a file to review. Tdarr startup idempotently installs
the locked `Plex HEVC guarded v1` flow and pilot library. Local flow plugins
live under `tdarr-plugins/<category>/<pluginName>/<version>/` because Tdarr
requires that extra category layer beneath `LocalFlowPlugins`.

## Pilot completion

Stage representative copies (grain, animation, foreign dialogue, subtitles,
ordinary TV, high-bitrate remux). The flow operates only on `/media`; it keeps
original-language audio and English full/forced subtitles. It uses HEVC
quality-based encoding, retains compatible AAC/AC-3/E-AC-3 tracks up to 5.1,
and converts incompatible or larger channel layouts to AC-3. It validates
duration, stream inventory, the duration-scaled size ceiling, meaningful
savings, and a full output decode before requiring manual review. Test playback
on Samsung, Apple TV, Android/Google TV, iPhone and browser clients. No
production replacement is enabled by this module.

Visual quality takes precedence over reaching a fixed file size. Begin the
pilot at x265 CRF 20 with a slow preset and test grain/dark/motion sequences;
this is lossy encoding, not a promise of identical quality. Preserve an
existing efficient encode or reject an output with less than 15% savings.
Use 10 GiB per two hours as the encoding threshold and 20 GiB per two hours as
the validation ceiling, scaled by duration. CRF remains authoritative: reject
rather than lower quality further when difficult material exceeds the ceiling.
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
source-change detection, validation gates, recoverable originals, and
Radarr/Sonarr/Plex refresh.
Review the arr upgrade policy to prevent repeated download/encode loops.
Keep originals outside scanned libraries for 7–14 days with a quota. Never
overwrite in place or treat a zero encoder exit code as a health check.

Use the T3 session guard in `container-workflow.md` for activation. If a full
switch affects T3 Code, use only the generated Tdarr unit with a retained GC
root and report full-system activation as deferred.
