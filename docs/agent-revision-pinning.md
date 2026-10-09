# Pinning the private agent revision

`ghostship-agent` is a private GitHub repository. It is a flake input of this
public repository (`ghostship-private-agent`), and a NixOS host can only
evaluate it with a GitHub credential — a bare public tarball fetch returns
`404 Not Found`.

## Deploying a new agent revision

1. Merge the change in `ghostship-io/ghostship-agent` and note the merged commit.
2. Bump `ghostship-private-agent.url` in `flake.nix` to that commit.
3. Prime the host's Nix fetcher cache once with a token that can read the
   repository. On the host:

   ```sh
   sudo env NIX_CONFIG='access-tokens = github.com=<token>' \
     nix flake metadata github:ghostship-io/ghostship-agent/<rev>
   ```

   The source lands in the store and the git-rev cache; the pinned revision
   then resolves offline, so the normal `nixos-upgrade` / `nixos-rebuild`
   path works afterward without the token. Alternatively seed the source with
   `nix copy --to ssh-ng://<host> /nix/store/<source>` from a machine that can
   fetch it.
4. Set the lock entry's `narHash` so evaluation never needs to resolve the
   ref. The narHash is the store path hash of the fetched source:

   ```sh
   nix flake prefetch 'git+file:///path/to/ghostship-agent?rev=<rev>' --json
   ```

   Write the returned `hash` into `flake.lock` under
   `nodes.ghostship-private-agent.locked.narHash` and the revision into
   `locked.rev`.

The token in step 3 is only needed until the revision is in the host's store
or cache. If a future bump is not primed, the host's upgrade fails with the
`404` archive error described above and the running generation is unaffected.

## Why not a standing token

The host deliberately has no long-lived GitHub credential in its Nix
configuration; the existing `github` secret unit is projected only to the
services that need it. Priming the fetcher cache at deploy time keeps the
private input out of the public repository's evaluation path and avoids a
daemon-wide token.
