# WSL2 Z Drive NFS Mount Design

## Goal

Replace the current WSL2 `Z:`-backed SMB/CIFS mount flow with a direct
NFS mount at `/mnt/z`, using the same Synology export and the same
performance-oriented mount options already used by `chill-penguin`.

## Scope

- Applies only to WSL2 hosts in this repo.
- Preserves the Linux-side mount path as `/mnt/z`.
- Removes the dependency on the Windows `Z:` drive and the current
  imperative `mount-z` SMB script.
- Keeps graceful behavior when Synology is unreachable or the host is on
  another network.

## Non-Goals

- No changes to non-WSL hosts.
- No change to the Synology export itself.
- No attempt to preserve Windows `Z:` drive detection or SMB fallback.

## Current State

The repo currently manages `/mnt/z` through `modules/develop/wsl-mounts.nix`
with a root `mount-z` helper and a `mount-z.service` oneshot unit. That
path:

- checks whether `Z:` exists in Windows via `cmd.exe`
- loads `smb-secrets`
- mounts the backing share through `mount.cifs`

This keeps `/mnt/z` working, but it binds the Linux mount path to Windows'
SMB mapping and adds Windows/network coupling that is not needed if WSL can
mount the Synology export directly over NFS.

## Proposed Design

### Mount Model

Replace the scripted CIFS mount with a declarative NFS filesystem entry:

- mount point: `/mnt/z`
- filesystem type: `nfs`
- device: `192.168.200.106:/volume1/share`

This is the same export already mounted by `chill-penguin` at `/mnt/share`.

### Mount Options

Reuse the same options from `hosts/chill-penguin/hardware-configuration.nix`:

- `nofail`
- `x-systemd.automount`
- `noatime`
- `nodiratime`
- `soft`
- `intr`
- `timeo=30`
- `retrans=2`
- `rsize=1048576`
- `wsize=1048576`
- `nfsvers=4.1`
- `async`
- `tcp`
- `actimeo=120`

These should remain identical unless later testing on WSL shows a
WSL-specific compatibility issue.

### Host Scoping

The NFS `/mnt/z` mount must remain WSL-only.

Implementation should keep the configuration attached to the WSL host path
already used by `launch-octopus` and `armored-armadillo`, rather than moving
it into a generic shared module used by non-WSL machines.

### Dependencies

WSL hosts need the NFS client tooling available. The WSL mount module should
ensure `nfs-utils` is present for those hosts.

The existing SMB-specific pieces should be removed if nothing else uses them:

- `mount-z` script package
- `mount-z.service`
- `smb-secrets` declaration from the WSL/develop path

## Failure Handling

The mount must fail gracefully when Synology is unavailable or the WSL host
is on a different network.

This is achieved by:

- `x-systemd.automount`
  `/mnt/z` is mounted on first access instead of at boot, so startup is not
  blocked waiting on the NAS.
- `nofail`
  A failed mount attempt does not put the system into a degraded startup
  path.
- `soft`, `timeo=30`, and `retrans=2`
  Access failures should return in bounded time instead of hanging for long
  periods.

The expected user-visible behavior is:

- on-network: `/mnt/z` mounts automatically on first access
- off-network or NAS down: `/mnt/z` access fails without blocking boot or
  wedging the system for extended periods

## Files To Change

- Modify: `modules/develop/wsl-mounts.nix`
- Modify: `modules/develop/secrets.nix` if `smb-secrets` becomes unused
- Modify: `README.md` to describe `/mnt/z` as a direct WSL NFS mount instead
  of a Windows `Z:`/SMB mount
- Modify: `CHANGELOG.md` with a curated note about the WSL mount change
- Modify: `home/config/skills/wsl2/SKILL.md` so it no longer claims the
  Z-drive path is SMB-backed

## Verification Plan

### Static Verification

- Evaluate/build each WSL host:
  - `nixos-rebuild build --flake .#launch-octopus`
  - `nixos-rebuild build --flake .#armored-armadillo`

### Runtime Verification

On a WSL host after switching:

- confirm the automount unit exists for `/mnt/z`
- access `/mnt/z` and verify it mounts as NFS v4.1
- verify mount options include the tuned `rsize`, `wsize`, and `actimeo`
- confirm that a disconnected/off-network state does not block system boot
  and that `/mnt/z` access fails in bounded time

Representative checks:

- `systemctl status mnt-z.automount`
- `findmnt /mnt/z`
- `nfsstat -m`

## Risks

- WSL2 networking differences could make one or more of the `chill-penguin`
  NFS options less effective or unsupported, though the baseline expectation
  is that standard Linux NFS client behavior will work.
- Removing `smb-secrets` must be done carefully to avoid breaking unrelated
  secret consumers, if any are later found.

## Recommendation

Implement the direct declarative NFS mount and keep it WSL-scoped. This
removes the Windows drive-letter dependency, aligns WSL with the working
Synology mount strategy already used on `chill-penguin`, and gives the
desired graceful off-network behavior through systemd automounting.
