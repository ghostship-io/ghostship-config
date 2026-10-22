# Pinning the private agent revision

The private agent source is a flake input of this public repository
(`ghostship-private-agent`). A NixOS host can only evaluate it with a GitHub
credential — a bare public tarball fetch returns `404 Not Found`.

## The public tree names nothing

This repository is public, and every repository in the fleet is treated as
public. The committed tree therefore names **no private repository, no
revision, and no content hash**. `flake.nix` and `flake.lock` carry a
placeholder:

```nix
ghostship-private-agent.url = "path:./private-agent-source";
```

`private-agent-source/flake.nix` is a small committed placeholder. It
resolves, so the repository evaluates on its own, and it declares the same
input the private source declares, so the lock keeps one node for it and the
substitution is a change of the locked source alone.

The consequence is the property the public tree needs. **An evaluation that
does not need the private source works with no credential at all**: the
development shells, the browser tests, and any other public check. **An
evaluation that does need it fails with a message that says the source was
not supplied**, and names the procedure. Nothing fails with a confusing
"path does not exist".

A checkout that has not been supplied with the private source therefore
evaluates the parts of the configuration that are public, and says clearly
what is missing for the rest.

## The public source policy

The committed lock may name only reviewed public sources, and the shared
policy module checks every node of it: the locked source, the original
declaration, and the input references. Two shapes are accepted and validated
rather than refused, because they are the lock format's own:

- a **parent input path**, which is how Nix records the ancestry of a relative
  input. The path is resolved through the input references, and a path that
  does not resolve, or that cycles, is refused.
- a **follows list**, which is an input reference rather than a source.

Every other unknown field is still refused, and a source that is not a
reviewed public source is still refused whether or not a placeholder is
expected.

## The private specification

The pinned source is supplied from a specification that lives outside the
repository:

| Consumer | Source of the specification |
|---|---|
| Continuous integration | the `GHOSTSHIP_PRIVATE_SOURCES` secret of the `private-source-ci` environment |
| A deployment host | a root-only file, for example `/etc/ghostship/private-sources.json` |

**The specification secret is environment scoped, not repository scoped.** It
lives in the `private-source-ci` environment, beside the read-only deploy key,
and the jobs that read it declare that environment. A repository level secret
would be readable by any workflow in the same repository, including one that
removes the environment gate, so protecting only the deploy key would not
protect the source coordinates. The environment scope is what keeps them
behind the review that the environment requires.

The specification is JSON and names one input:

```json
{
  "ghostship-private-agent": {
    "type": "github",
    "owner": "<owner>",
    "repo": "<repository>",
    "rev": "<revision>",
    "narHash": "sha256-<content hash>",
    "lastModified": 0
  }
}
```

Never write the specification into a tracked file. A tracked copy would
publish the repository name, the revision, and the content hash, which is
exactly the chain needed to find and fetch a private repository.

## Supplying the source

`scripts/private-inputs.py` writes the specification into `flake.nix` and
`flake.lock` before evaluation:

```sh
# A host, with the specification at its root-only path.
python3 scripts/private-inputs.py apply --spec /etc/ghostship/private-sources.json

# Continuous integration, which additionally imports the source with the
# read-only deploy key and points the lock at the Nix store copy.
python3 scripts/private-inputs.py import

# Put the committed placeholders back, for example before publishing a
# refreshed lock file.
python3 scripts/private-inputs.py restore
```

`apply` leaves the lock pointing at the GitHub source, so the host resolves
it with its own credential.

`import` fetches the source with the scoped read-only deploy key, verifies
the content hash against the specification, and **copies the source into the
Nix store**. The lock then names the store path, not a working directory, so
the evaluation still resolves after the importer has exited and its working
directory has been removed. The evaluation that follows the importer
therefore has a durable source, and a failure cannot leave a lock that names
a path which no longer exists.

The importer refuses to run unless the **committed** tree carries the
placeholder. Both the importer and privacy scanner use
`scripts/source_privacy.py` to validate every source node in the committed
lock, including duplicate nodes and each original source. GitHub owner and
repository pairs must be exact entries in `scripts/privacy-allowlist.txt`;
suffix allowances do not grant source permission. The managed local
placeholder is the only path source accepted in the root lock. Public
dependency nodes and follows references remain supported. New source types
or fields require policy review. A lock file is never exempt as a whole.

This is a bounded source-format check, not proof that arbitrary tracked text
cannot encode a private identifier. Other tracked text still receives the
category and optional private-pattern checks, with their reported coverage
boundaries. Older scanner copies in other repositories do not enforce this
policy until their owners propagate and enable it.

CI runs `tests/test_private_inputs.py` in the public Nix environment before
applying any private specification. Store and flake integration tests need
the writable daemon store and public source tree; they are skipped when Nix
is absent from the separate build sandbox. The browser job needs no private
credentials and continues to use the committed public placeholder.

The importer reports a failure as a step, never as the command that failed.
The command carries the repository name, the revision, and the content hash,
so echoing it into a log would publish the discovery chain.

## Deploying a new agent revision

1. Merge the change in the private agent repository and note the merged
   commit.
2. Update the specification with the new revision and its content hash. The
   specification is private, so this is a change to the environment secret and
   to the host's root-only file, not to a commit here.
3. If the host does not hold a GitHub credential for the private source,
   prime the fetcher cache instead:

   ```sh
   nix flake prefetch 'git+file:///path/to/the-private-checkout?rev=<rev>' --json
   nix copy --to ssh-ng://root@<host> /nix/store/<source>
   ```

   Use the returned `storePath`. The pinned source can then resolve from the
   store without putting a GitHub token in shell history, process arguments,
   or the host's Nix configuration.
4. Deploy the host. The specification is applied before evaluation, so the
   host picks up the new revision without any change to this repository.

If a future bump is not primed, the host's upgrade fails with the `404`
archive error described above and the running generation is unaffected.

## Why not a standing token

The host deliberately has no long-lived GitHub credential in its Nix
configuration; the existing `github` secret unit is projected only to the
services that need it. Priming the fetcher cache at deploy time keeps the
private input out of the public repository's evaluation path and avoids a
daemon-wide token.
