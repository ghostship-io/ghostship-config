# Boomer GZDoom controls handoff - 2026-04-30

## What changed

- Restored the first Boomer GZDoom config baseline from `e0e6880`, then moved
  to config-only `JoyN` overrides as live button reports came in.
- Kept only the existing GZDoom menu A/B source patch.
- Kept right-stick vertical look at `Axis3scale=0.25`.
- Confirmed in-game reports:
  - `Joy1` / B: jump.
  - `Joy2` / A: use/open.
  - `Joy3` / X: crouch was reported, but the same report also said X did
    nothing, so this needs retest if Doom returns.
  - `Joy10` / Minus: automap.
  - `POV1Left` / `POV1Right`: previous/next weapon.
- Guessed remaining bindings before pausing Doom:
  - `Joy6`: User 1 candidate for L1.
  - `Joy7`: User 2 candidate for R1.
  - `Joy8`: alt-fire candidate for L2.
  - `Joy9` / `Joy14` / trigger axes: fire candidates for R2.
  - `Joy11` / `Joy12`: Plus/menu candidates.
  - `Joy15` / `Joy16`: L4/R4 guesses.

## Probe attempts

- A temporary `echo GZDoomProbe ...` cfg was launched on Boomer's active
  Gamescope/Xwayland display. GZDoom started, but console `echo` output did not
  persist to the logfile.
- A temporary cvar/archive probe was attempted next. The live config file was
  changed, but existing game-specific `Chex.Bindings` from the prior probe
  meant the run still did not yield reliable `joyprobe_*` persisted cvars.
- Before any future GZDoom work, clear stale non-Doom binding sections such as
  `Chex.Bindings` and `Chex.AutomapBindings`, or use a fresh `XDG_CONFIG_HOME`
  while launching on the active display.

## Current decision

GZDoom is being removed from the live Boomer ROM library for now, per operator
request. Do not keep iterating on the controls until Doom is intentionally
reintroduced.
