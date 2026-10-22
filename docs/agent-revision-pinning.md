# Pinning the private agent revision

`ghostship-agent` is a private GitHub repository. It is a flake input of this
public repository (`ghostship-private-agent`), and a NixOS host can only
evaluate it with a GitHub credential — a bare public tarball fetch returns
`404 Not Found`.

## Deploying a new agent revision

1. Merge the change in `ghostship-io/ghostship-agent` and note the merged commit.
2. Bump `ghostship-private-agent.url` in `flake.nix` to that commit.
3. Import the pinned source on a machine with repository access, then copy
   its store path to the host:

   ```sh
   nix flake prefetch 'git+file:///path/to/ghostship-agent?rev=<rev>' --json
   nix copy --to ssh-ng://root@<host> /nix/store/<source>
   ```

   Use the returned `storePath`. The pinned source can then resolve from the
   store without putting a GitHub token in shell history, process arguments,
   or the host's Nix configuration.
4. Set the lock entry's `narHash` so evaluation never needs to resolve the
   ref. The narHash is the store path hash of the fetched source:

   ```sh
   nix flake prefetch 'git+file:///path/to/ghostship-agent?rev=<rev>' --json
   ```

   Write the returned `hash` into `flake.lock` under
   `nodes.ghostship-private-agent.locked.narHash` and the revision into
   `locked.rev`.

If a future bump is not primed, the host's upgrade fails with the
`404` archive error described above and the running generation is unaffected.

## The organisation namespace

The private agent source now lives in the `ghostship-io` organisation. The
`ghostship-private-agent` input URL and both lock owners name that
organisation. The pinned revision is `f6a415dd` (free-pool grant removal and
conservative unknown limits), which descends from the previous pin
`cb003746`, so nothing on the pinned line is dropped. The repositories were
renamed at the same time — `nixos-config` became `ghostship-config` and
`orca-advanced-calibration` became `ghostship-orca` — while local checkout
paths and T3 project identifiers stayed the same.

The coordinator's repository map, its incident repository and the webhook
receiver's allowlist now name the canonical repositories. The receiver also
serves the seven previous names, and the coordinator configuration carries a
`repository_aliases` map from each previous name to its canonical one, so that
existing issue owners, queued deliveries, CI issue mappings and pull request
links survive the transfer.

Those aliases take effect only in an agent revision that implements them. A
pin bump that adds them must descend from the pinned revision, as
[the pin guard](#the-pin-must-not-move-backwards) requires; a revision from
another line would drop the coordinator behaviour that is already deployed.
The pinned revision `f6a415dd` carries that implementation, so the alias map
is live.

## The pin must not move backwards

A pull request that moves the pin to a revision that does not descend from the
pinned one silently drops everything that is on the pinned line. The Fleet
checks job runs `scripts/check-agent-pin.py`, which compares the pull
request's `ghostship-private-agent` revision with the base branch's and fails
unless the new revision descends from the old one. Git answers that in the
fetched agent source, which the job reads with the read-only agent key.

An intentional move to another line needs an explicit approval line in the
pull request body or in one of its commits, naming the reason:

```text
pin-regression-approved: the pinned line was merged into main
```

The line needs a reason; an empty approval does not pass the check.

## Why not a standing token

The host deliberately has no long-lived GitHub credential in its Nix
configuration; the existing `github` secret unit is projected only to the
services that need it. Priming the fetcher cache at deploy time keeps the
private input out of the public repository's evaluation path and avoids a
daemon-wide token.
