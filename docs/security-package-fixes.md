# Security-fixed Nix and Podman pins

Campaign #102 (October 2026) pins the upstream fixed releases of the two
packages that the host runs: Nix on its 2.34 maintenance line and Podman on its
5.8 line. The pins live in an overlay, they replace exactly two packages, and
they leave the rest of the pinned nixpkgs untouched. No nixpkgs bump, no
`flake.nix` or `flake.lock` change, and no change to any host, kernel or
container configuration.

Nothing here is live until the coordinator deploys a configuration that
contains these files. This document records what the change does, how the pins
are proven to be the upstream fixed releases, what a deployment will and will
not do, and what remains unverified.

## Advisories

| Package | Pinned | Was | Advisory |
| --- | --- | --- | --- |
| Nix | 2.34.9 | 2.34.8 | Nix and Lix security advisory, October 2026 |
| Podman | 5.8.8 | 5.8.6 | GHSA-2cvf-wqm6-wr9g / CVE-2026-94603 |

Nix, upstream advisory
<https://discourse.nixos.org/t/security-advisory-for-nix-and-lix-october-2026/80547>:

- CVE-2026-110449 — unsigned integer overflow in list allocation, a heap
  out-of-bounds write while evaluating untrusted expressions.
- CVE-2026-110450 — unprivileged `repair` could replace a store path before
  its contents were verified, a local privilege escalation.
- CVE-2026-110451 — macOS Seatbelt sandbox escape. macOS only; this
  deployment is Linux.
- CVE-2026-110452 — the multi-user installer left store contents owned by the
  invoking user. Installer only; NixOS installs are not affected.
- CVE-2026-110453 — the daemon did not reject build users on unsandboxed
  macOS and FreeBSD configurations.

Podman, upstream advisory
<https://github.com/podman-container-tools/podman/security/advisories/GHSA-2cvf-wqm6-wr9g>:
`podman run` treated any image that carried the
`io.podman.annotations.checkpoint.runtime.name` annotation as a checkpoint and
silently restored it, discarding the sandbox the caller asked for (for example
`--cap-drop=ALL`) in favour of the capability set stored in the image. The fix
removes that behaviour and rejects checkpoint images on `podman run`;
`podman container restore` stays available. Rootless containers are not
affected because they do not support checkpoint and restore.

Podman 5.8.6 already sits above the 5.8.4 threshold of GHSA-4hq8-gpf5-8p68
(the environment leak), and 5.8.8 also carries the 5.8.7 fixes.

## Pins and upstream identity

| Package | Version | Source | Source hash |
| --- | --- | --- | --- |
| Nix | 2.34.9 | `github.com/NixOS/nix` tag `2.34.9` | `sha256-ZJwg/qG4M1Impy774HKMZ3Hsq7vlBJy7sXl1fI9QDXI=` |
| Podman | 5.8.8 | `github.com/podman-container-tools/podman` tag `v5.8.8` | `sha256-fl2/HyUh2EBbSw6O50H04Bltu2ZNF1Fay9XNNzKVpSE=` |

The Nix hash was recomputed locally from the fetched tree and matches the hash
that upstream nixpkgs published for the same bump (nixpkgs pull request
573623). The Podman hash was recomputed locally from the fetched tree.

Upstream commits that carry the fixes, between `2.34.8` and `2.34.9`:

- `7c2264f810d7` — libexpr: tighten allocBytes with an overload that detects
  the unsigned overflow (CVE-2026-110449).
- `4d01f74afb6e` — libstore/daemon: disallow unprivileged repair in
  AddMultipleToStore, AddToStoreNar and AddToStore (CVE-2026-110450).
- `b97f0b8617ca` — libstore: unpack to a temporary location in
  LocalStore::addToStore.
- `62e26393c2b1` — record gid in getPeerInfo when using LOCAL_PEERCRED
  (CVE-2026-110453).
- `3becb9b1215e` — installer: fix store object ownership in multi-user
  installs (CVE-2026-110452).
- `56107313a950` — fix the sandbox breakpoint escape (CVE-2026-110451).

Upstream commits that carry the Podman fix, between `v5.8.6` and `v5.8.8`:

- `7728ba0a9009` — revert "Enable 'podman run' for checkpoint images".
- `24706290d5c9` — error when a checkpoint image is run.
- `29c8c6e50607` — rework the podman run checkpoint test.
- `fe908f63e15b` — merge commit from fork.

## How the pins are applied

`modules/common/security-package-fixes.nix` installs the overlay from
`packages/security-fixes/default.nix`.

The overlay repoints exactly these attributes:

| Attribute | Before | After |
| --- | --- | --- |
| `pkgs.nix` | 2.34.8 | 2.34.9 |
| `pkgs.nixVersions.stable` | 2.34.8 | 2.34.9 |
| `pkgs.nixVersions.nix_2_34` | 2.34.8 | 2.34.9 |
| `pkgs.nixVersions.nixComponents_2_34` | 2.34.8 tree | 2.34.9 tree |
| `pkgs.podman` | 5.8.6 | 5.8.8 |

The other Nix lines that the pinned nixpkgs carries — `nixVersions.latest`
(2.35.2), `nix_2_35`, `nix_2_31` and the git snapshot — are **not** repointed.
They stay on the releases the nixpkgs input ships, and the same advisory lists
those releases as affected. No host configuration in this repository
references them. Pinning the 2.35 line is a follow-up, not part of this
change.

Nix is not repackaged from scratch. The pinned nixpkgs builds Nix from a
release source tree that its expression pins per release, and it exposes two
supported extension points on the `nixComponents_2_34` scope:

- `overrideSource` swaps the release tree.
- `overrideAllMesonComponents` re-stamps the version on every component.

Both are needed. Overriding the source alone would build the 2.34.9 tree and
still label it 2.34.8 in the derivation name, in the `.version` file written
into the build tree and in the reported version, which is exactly the mistake
the upstream `srcVersion` test exists to catch. The overlay also re-stamps the
scope's own `version` attribute so that the scope cannot report a stale
release; that change is behaviour-neutral, because every version comparison in
the packaging expressions has the same result for 2.34.8 and 2.34.9, and the
resulting derivation paths are identical either way.

Podman is version-bumped through `overrideAttrs` on the pinned nixpkgs
expression. The pinned expression builds Podman from the release tarball with
`vendorHash = null`, because the tarball ships its own `vendor/` tree, so
only the source and the version move. The helper binary wrapper, the
AppArmor, seccomp and SELinux inputs, the `extraPackages` and `extraRuntimes`
overrides that the NixOS podman module applies, and the systemd unit files in
the package are all inherited unchanged. The NixOS module's helper override
keeps the pinned source, which the module asserts and the test file checks.

The overlay reads `prev` only. Reading `final` would make the overlay depend
on its own result, because the result publishes the pinned `nixVersions`
scope.

## Upstream tests

The upstream Nix test suite is imported from the pinned nixpkgs and bound to
the pinned build, so that the upstream regressions run against the build this
repository installs. It is upstream's own file; only the package it is bound
to changes. It carries:

- `srcVersion`, the packaging regression that compares the reported version
  with the `.version` file of the fetched tree.
- `nixpkgs-lib`, the nixpkgs library suite, run against the pinned Nix.
- `nix-misc`, `nix-upgrade` and the installer test from the nixpkgs NixOS
  test suite.

The upstream `nix-fallback-paths` coherence check keeps its slot in the test
set and is bound to the pinned build, but it is no longer the upstream
comparison: that comparison reads a file of the nixpkgs input and compares it
with the release this repository pins, so it cannot pass against a pinned
input. The check that replaced it proves that the difference cannot reach a
runtime consumer. See the known limitation below.

Building the pinned `nix` package is itself a regression run: the upstream
expression sets `doCheck = true` and runs the upstream unit and functional
test suites as build inputs of the package.

## Upstream regressions

Building the pinned `nix` package is itself an upstream regression run: the
aggregate derivation has `doCheck = true` and its `checkInputs` are the
upstream test runs. `pkgs.nix` is
`/nix/store/w549lvx46kb0nxf14wrd8jh63495lyfv-nix-2.34.9.drv` with outputs
`out`, `dev`, `doc`, `man`; `out` is
`/nix/store/p715bsngf3drwygs5n2adp1qlwvmgxm7-nix-2.34.9`.

| Check input | Derivation | Observed result |
| --- | --- | --- |
| `nix-util-tests.tests.run` | `/nix/store/vqgki64vplh9k1wpsfxvfn7p9byq5qg7-nix-util-tests-run.drv` | passed locally; reused by host build |
| `nix-store-tests.tests.run` | `/nix/store/zvinh7cflw1lx37wwa4y81wh8gw9azz8-nix-store-tests-run.drv` | passed locally; reused by host build |
| `nix-expr-tests.tests.run` | `/nix/store/zxqkva15s53n1fdsfz3xfkdbq5ica571-nix-expr-tests-run.drv` | passed locally; reused by host build |
| `nix-fetchers-tests.tests.run` | `/nix/store/imgys1l30s8ccy5d54zgg37a94qrsh7h-nix-fetchers-tests-run.drv` | passed locally; reused by host build |
| `nix-flake-tests.tests.run` | `/nix/store/vcp53p91l802lim535cq8ylis2bsrmgd-nix-flake-tests-run.drv` | passed locally; reused by host build |
| `nix-functional-tests` | `/nix/store/8p41921m6byidlmid3zh35csf1gf5iy2-nix-functional-tests-2.34.9.drv` | **200 passed, 9 skipped, 0 failed** |
| `nix-perl-bindings` | `/nix/store/7zjhc0m2am5fzvz7iyc84461rc4dqav6-nix-perl-2.34.9.drv` | reused, not re-exercised (see below) |

### The functional suite passed on the host, sandboxed

The functional derivation `8p41921m…` (derivation SHA-256
`27e39c63a13e8d856e57f8e75e25769b10d2435d26886ab8adf6cd24ca265758`) was built on the host with `sandbox = true` and a direct
`--store local`, inside a transient unit bounded to `MemoryMax = 6G`,
`MemoryHigh = 4G`, `MemorySwapMax = 0`, `TasksMax = 2048`, `CPUQuota = 200%`,
`Nice = 10`, one build job, two cores, offline substitutes disabled and
`sandbox-fallback = false`. The live builder `/build`, its cgroup and
`NIX_BUILD_CORES = 2` were observed during the run. It exited 0 with
200 passed, 9 skipped and 0 failed.

The protected evidence record retains the output identity, NAR hash and build-log
digest. Historical success does not establish current store registration or
GC-root retention; re-read those before any activation.

A first functional attempt failed **before `nix` was executed** (a `PATH`
problem in the invoking shell), so it says nothing about the suite; the second
attempt is the one above.

This supersedes the earlier 196 passed / 9 skipped / 4 failed result, which was
seen only in the T3 Code container and only with `sandbox = false`. The cause
of that container-only failure is analysed below and is not a property of the
pinned source.

### The full aggregate was built on the host

`w549lvx4…` (derivation SHA-256 `1e20bee2dcbc02ccce13027c01bda1319e80e5a8bc8df246c83f4314df1bf1dc`)
was built on the host to all four outputs with exit 0, reusing the functional,
unit-test and cached-Perl inputs. `out` is
`/nix/store/p715bsngf3drwygs5n2adp1qlwvmgxm7-nix-2.34.9` with
`sha256-df6NhdiYiLY0bfbmCoy38E6DTdNvTHYRnBGS7+oGYjw=`, and both `nix` and
`nix-daemon` report `2.34.9`.

The aggregate finished too quickly to observe a live builder, so no live
builder observation is claimed for it. Its transient-unit limit checks passed
and its completed build log contains the sandbox `/build` path. Only the
functional run has a live observation of builder membership in the capped
cgroup.

`nix-perl-bindings` (`x3m582…`) was already realised locally **before** the
aggregate, so the aggregate reused it rather than running a fresh Perl test.
Its original log (`7zjhc0m2…`) reports 1 passed and 0 failed; it is reused
evidence, not a fresh host exercise.

### Container-only failure, and why it does not apply to the host

Only the T3 Code container saw functional failures, and only with
`sandbox = false`. There, the three `build-remote` tests failed on
`error: opening lock file "...": File name too long`. The name is the remote
store URI with the source and test-root paths flattened, and its length is set
by `TMPDIR` (`tests/functional/common/test-root.sh` derives `TEST_ROOT` from
`${TMPDIR:-/tmp}`) and by the source path (`$prog` in
`build-remote-trustless.sh`).

Reproduced with the real harness, unmodified test scripts and the pinned
binaries, under an isolated `TMPDIR` and store root:

| Layout | Lock-file name | Result |
| --- | --- | --- |
| the container build (`TMPDIR=/nix/var/nix/builds/nix-<pid>-<id>`) | 273 bytes | `File name too long` |
| A/B long path | 259 bytes | same error, same line |
| A/B short path | 173 bytes | the failing operation succeeds, the test advances |
| sandboxed layout (`/build/<derivation-name>`, the host default) | 231 bytes | fits |

The same comparison at the filesystem level: creating the 259-byte name
returns `File name too long`, creating the 173-byte name succeeds. Only the
path length changed between the two runs; the script, the binaries and the
store root layout are identical.

The container could not run the sandboxed case itself: `nix` refuses
`sandbox` and `build-dir` for an untrusted build user. The host build
resolved the question directly — with `sandbox = true` the same derivation
passes 200 tests. The container-only failure is therefore a property of the
unsandboxed test layout, not of the pinned source.

The `shell` failure is the same class: the nested build cannot produce its
`dev` output inside the unsandboxed build directory.

## Regression proofs

`packages/security-fixes/proofs.nix` holds the proofs. They read the pinned
sources and the built artefacts, and one of them exercises the fixed Podman
behaviour. None of them reproduces an exploit and none of them touches the
host.

| Proof | What it checks |
| --- | --- |
| `nixSourceVersion` | the pinned source `.version` matches the package version |
| `nixAllocationOverflowCheck` | the pinned evaluator source detects the allocation overflow (CVE-2026-110449) |
| `nixRepairRestriction` | the pinned daemon source refuses an unprivileged repair on the store paths (CVE-2026-110450) |
| `nixDaemonRepairPatchIdentity` | patch identity only: the built `nix-daemon` reports 2.34.9 and the store library it links carries the repair-refusal marker |
| `podmanCheckpointRunRemoved` | the pinned Podman source no longer restores a checkpoint image on run (CVE-2026-94603) |
| `podmanRejectsCheckpointImage` | the built Podman refuses to run a checkpoint image, and creates no container |

All six proofs build in this environment. The daemon proof reads the
component outputs (`passthru.nix-cli` for the daemon, `passthru.libs.nix-store`
for the library) rather than the aggregate `nix.out`, so it does not depend on
the aggregate's documentation outputs; `nix.out` links those same components
together with `lndir`.

The three vulnerability proofs were checked against the un-pinned releases as
well, so they are known to have teeth and not to be a label check:

| Proof | Against 2.34.8 / 5.8.6 | Against the pinned 2.34.9 / 5.8.8 |
| --- | --- | --- |
| `nixAllocationOverflowCheck` | fails: "the pinned Nix source does not detect the allocation overflow" | passes |
| `nixRepairRestriction` | fails: "the pinned Nix source does not refuse an unprivileged repair on the store paths" | passes |
| `podmanCheckpointRunRemoved` | fails: "the pinned Podman source still restores checkpoint images on run" | passes |
| `nixSourceVersion` | passes: the nixpkgs default is self-consistent | passes |

`nixSourceVersion` is a pin-consistency check rather than a vulnerability
check: it fails when the source is swapped without re-stamping the version.
The repair marker is the string `you are not privileged to repair store paths`,
because 2.34.8 already refused a repair on the verify path; the fix adds the
refusal to the three store-writing paths.

The behavioural proof builds a throwaway OCI image that carries the
`io.podman.annotations.checkpoint.runtime.name` annotation, loads it into a
storage root inside the build directory, and runs the built Podman against it.
The fixed Podman answers:

```
Error: e8611e03... is a checkpoint and must be started using `podman container restore` instead
```

and `podman ps -a` stays empty, because the refusal happens before the
container is created. The vulnerable 5.8.6 build was deliberately not run
against that image, and the behavioural proof is therefore not run in its red
form: exercising the affected path is the exploit reproduction that this work
is not allowed to perform. The source-level proof above covers the red form
for Podman.

### Isolation of the behavioural proof

The proof cannot reach any engine outside its build directory:

- `HOME`, `XDG_RUNTIME_DIR` and `TMPDIR` are set to `$PWD/...` inside the
  build directory.
- Every podman call passes `--root "$PWD/root"` and `--runroot "$PWD/runroot"`,
  so the storage and the state database are private to the build.
- The image is loaded with the `oci:` transport from `$PWD/oci-layout`, which
  is a local OCI layout directory: no registry, no network, no pull policy.
- `podman run` is called with `--pull=never --network=none`.
- `CONTAINER_HOST`, `CONTAINER_CONNECTION`, `CONTAINERS_CONF` and `DOCKER_HOST`
  are unset, so an inherited remote engine cannot be selected.
- The build sandbox does not expose the host's Podman socket or the T3 Code
  container's engine.

Recorded side effects outside the repository, from developing this proof by
hand before it was encoded as a derivation:

- `/home/t3code/.cache/opencode-tmp/opencode/podman-root/{root,runroot}`: a
  throwaway `vfs` storage root that received one locally built OCI image and
  no container. It was never pointed at the production store or socket.
- `/home/t3code/.cache/opencode-tmp/opencode/podman-home` and `podman-cfg`: a
  throwaway `HOME` with a permissive `policy.json` used only for those loads.
- `/tmp/nt` and `/tmp/nb`: scratch copies used for the path-length A/B.
- No prune, no image removal, no store deletion and no restart was run
  anywhere.

`tests/security-package-fixes.nix` holds the evaluation checks: the deployed
Nix and Podman are the pinned releases, their sources are the pinned upstream
trees, the Nix aliases that name the 2.34 line resolve to the pinned build, the
upstream test suite is still carried over, and every host in the repository
resolves the same two releases.

```
nix eval --impure --json --file tests/security-package-fixes.nix
```

## Activation impact

The following describes the evaluated configuration. It is not a report of a
deployment. Everything below was measured by evaluating the same host before
and after the change on the same nixpkgs input.

**Two impacts dominate and must be read together:**

1. **A switch stops and restarts 35 container units** — 35 of the 36
   `virtualisation.oci-containers` entries, because their unit `path` carries
   the podman package. `podman-t3code` is the one exception. Two further
   services that reference the podman package but are not OCI containers
   (`podman-prune`, `ghostship-podman-snapshot`) are listed below.
2. **The T3 Code container is recreated by the idle-deploy controller after
   any activation**, not by the switch. `restartIfChanged = false` protects
   the container during the switch only. See "T3 Code container and its
   controllers" below.

The switch implementation honours `X-RestartIfChanged=false` by skipping a
modified service. For a service it will change, `X-StopIfChanged=false`
selects restart rather than stop followed by start. The source comment saying
`stopIfChanged=true` is ignored describes activation-requested restarts, not
all unit changes (`switch-to-configuration-ng/src/main.rs`,
`handle_modified_unit`). These flags do not inhibit the separate image
controller.

### Units that carry the pinned packages

`podman.socket` is enabled (`wantedBy = [ "sockets.target" ]`), so the Podman
API socket is live on this host. `podman.service` is shipped by the podman
package itself (`systemd.packages = [ cfg.package ]`), so its `ExecStart` comes
from the packaged unit in the podman store path; the unit source changes with
the pin, and the API is served by the pinned binary after the service restarts.

| Unit | Pinned package | `restartIfChanged` | `stopIfChanged` | Effect of a switch |
| --- | --- | --- | --- | --- |
| `nix-daemon.service` | Nix | true | false | restarted, socket stays up |
| `nix-optimise.service` | Nix | false | true | skipped for a unit-content change; next independent start uses the new binary |
| `nixos-upgrade.service` | Nix | false | true | skipped for a unit-content change; next independent start uses the new binary |
| `t3code-deploy-when-idle.service` | — | false | true | not restarted; the timer keeps firing |
| `podman.service` (socket-activated) | Podman | true | true | restarts on the next socket activation |
| `podman-t3code.service` | Podman | false | false | **not** restarted or stopped |
| `podman-prune.service` | Podman | false | true | skipped for a unit-content change |
| `ghostship-podman-snapshot.service` | Podman | true | true | restarted |
| 35 of the 36 `oci-containers` units | Podman | true | true | stopped and restarted |

**`virtualisation.oci-containers.containers` has 36 entries in total,
including `t3code`.** 35 of them restart on a switch; `podman-t3code` is the
one exception. `podman-prune` and `ghostship-podman-snapshot` are separate
services that also reference the podman package and are not part of that
attrset.

The 35 restarting container units are: `agent-desktop`, `bazarr`, `chaptarr`,
`cloudflared`, `flaresolverr`, `ghostship-github-coordinator`,
`ghostship-hooks`, `ghostship-private-integrations`, `gluetun`, `grafana`,
`grimmory`, `grimmory-db`, `homepage`, `muximux`, `ntfy`, `nzbget`, `plex`,
`plex-auto-languages`, `prowlarr`, `pyload`, `qbittorrent`, `radarr`,
`recyclarr`, `romm`, `romm-db`, `seerr`, `sonarr`, `tautulli`, `tdarr`,
`uptime-kuma`, `victorialogs`, `victoriametrics`, `vmalert-logs`,
`vmalert-metrics` and `vmauth`.

None of these units declares an `ExecReload` in the generated fragment, so no
reload path is affected.

### Host nix-daemon

Read from the packaged unit together with the custom drop-in, on both sides:

| | LIVE generation | Candidate from the pinned build |
| --- | --- | --- |
| base `ExecStart` | `@/nix/store/yv6a1c6a…-nix-2.34.8/bin/nix-daemon nix-daemon --daemon` | `@/nix/store/v79w10yd…-nix-2.34.9/bin/nix-daemon nix-daemon --daemon` |
| `KillMode` | `process` | `process` |
| custom drop-in | `X-StopIfChanged=false` | `X-StopIfChanged=false` |
| `Before`/`After`/`Requires`/`Wants` naming the T3 bootstrap, container setup or user manager | none | none |

The `@` prefix is systemd's marker that the following path is the binary while
the next word becomes `argv[0]`, so the unit runs `<nix>/bin/nix-daemon` with
`argv0 = nix-daemon` and `--daemon`. The candidate resolves through the
`nix-cli` component output (`v79w10yd…`), not through the aggregate
`p715bsngf…`, which is why the two sides differ only in that path.

`config.systemd.units."nix-daemon.service".text` alone does not show this
`ExecStart`: the program line is inherited from the packaged unit that
`systemd.packages = [ nixPackage ]` installs, and the generated fragment only
carries the module's overrides. Both have to be read together. The generated
fragment is not evidence that the host has no `ExecStart`, and an earlier
revision of this document wrongly said so.

The daemon is selected for restart on a unit-content change
(`restartIfChanged=true`, `stopIfChanged=false`). The socket remains a
separate unit. `KillMode=process` describes how the main daemon is stopped;
continuity still needs validation against the loaded units and active builds.

This host unit has **no** dependency on the T3 Code bootstrap, container-setup
or user-manager units. The `nix-daemon.service` that carries those edges is a
different unit written inside the T3 Code image
(`After=`/`Requires=t3code-container-setup.service nix-daemon.socket`); it is
rebuilt as part of the image and is not part of the host unit set.

`restartTriggers` still points at `nix.conf` only.

### T3 Code container and its controllers

- The image embeds `${pkgs.nix}/bin/nix-daemon` in its own
  `/etc/systemd/system/nix-daemon.service` and `pkgs.podman` in the image
  closure, so the image is rebuilt and the deployment identifier changes.
- `podman-t3code.service` keeps `restartIfChanged = false`, which
  `switch-to-configuration-ng` honours by skipping the unit, so the switch
  itself does not restart the running T3 Code container. It also keeps
  `stopIfChanged=false`. Neither flag blocks a separate controller command.
- `t3code-deploy-when-idle.service` keeps `restartIfChanged = false` and
  `stopIfChanged = true`; its timer keeps `restartIfChanged = false`. It is
  therefore not restarted on a switch, and it keeps firing.

**The flags do not prevent a replacement.** The pin changes
`t3codeDeploymentId` (`hashString "sha256" (toString t3codeImage)`), and the
existing idle-deploy controller reacts to exactly that:

The source comparison confirms that the image deployment identifier changes.
Its literal values belong in protected activation evidence, rather than the
public procedure.

Read from the source, the chain after any activation that includes this
change:

1. `system.activationScripts.t3code-deployment` writes the new
   `t3codeDeploymentId` into `/var/lib/ghostship/t3code-deployment/desired`
   and runs `systemctl start --no-block t3code-deploy-when-idle.service`.
   `supportsDryActivation = false`, so it runs on every switch.
2. `t3code-deploy-when-idle.service` sees `desired != applied` and calls
   `is_live_idle`: the tool-update lock must be free, the activity probe must
   confirm idle, and the container's web endpoint must answer. It then waits
   `confirm_idle_seconds` (30 s) and re-checks.
3. On a sustained idle window it runs
   `systemctl restart podman-t3code.service`, which re-runs the unit and
   `podman run --replace` creates the container from the new image.
4. `t3code-deploy-when-idle.timer` repeats this every minute
   (`OnBootSec = 2m`, `OnUnitActiveSec = 1m`, `Persistent = true`), so the
   queue survives reboots and retries.

Consequence: **activating this change recreates the T3 Code container at the
first sustained idle window**, even though neither unit restarts on switch.
"Idle" here means the activity probe reports no work; it is a normal working
state, not a maintenance window, and an active session does not by itself
prevent the replacement once the probe reports idle between turns.

### Activation remains gated

No activation procedure is approved here. A normal switch would restart 35
other OCI containers and update the T3 image queue. Rebooting would interrupt
the active session; changing a boot default also changes profile/boot state.
Neither is a permitted workaround under the current continuity constraints.
Scoped activation is possible in principle, but requires its own exact
artifact, consumer, command and rollback review; a full switch is not the
only possible activation mechanism.

Before a package activation proposal can pass the shared coordinating gate:

1. Realise the effective NixOS Podman helper package and complete the
   packaged-unit plus drop-in comparison against the live generation and
   loaded runtime overrides. The plain Podman build is a different output.
2. Identify each unit and executable that would change. Preserve the T3
   container identity, start time, host/inner PIDs, image and current-generation
   expectations explicitly; do not invent a global no-restart flag.
3. Exclude an in-flight image replacement with the controller's existing
   exclusive `deploy.lock` lease. Reading `applying` and then stopping the
   controller races a new invocation; absence of that file is not proof that
   stopping is safe. Do not stop an in-flight controller.
4. Cover both the timer and the activation script's direct service start.
   Any temporary inhibition needs exact prior-state capture, ownership,
   failure behaviour and restoration instructions. No mask, timer change or
   shared systemd reload is performed by this document.
5. Preserve `desired`, `applied`, `applying`, `restart.pending` and `failures`,
   including changes queued during maintenance. Never mark a new image
   applied while the old one runs. Releasing an inhibition may allow a future
   idle replacement; it does not guarantee exactly one replacement or make
   that replacement safe for an active session.
6. Provide rollback for the exact scoped changes without rebooting or
   restarting T3, and recheck runtime versions and session identity. A later
   shared activation requires a fresh comparison after other coordinated
   work, including the monitoring rollout.

Shared systemd reloads and service activation remain coordinated with the
monitoring owner. Build success does not clear these activation gates.

### Measured closure change

| | Before (`903fc607`) | After (`c554813f`) |
| --- | --- | --- |
| `nix-daemon.service` `path[0]` | `gjb6szzx4bl00zd1cnvadhhycpjrnb38-nix-2.34.8` | `p715bsngf3drwygs5n2adp1qlwvmgxm7-nix-2.34.9` |
| `podman-t3code.service` `path[0]` | `cfgzw051sayng6bfb1cjxxrgibww30xg-podman-5.8.6` | `j6pv741dy1afcnbcysg0kym2h48r6h5s-podman-5.8.8` |
| `podman.service` unit source | podman 5.8.6 unit | `r01l6v4q219xd9vd88lv4z1vc082k1dd-unit-podman.service` |

The rest of each measured service `path` list is unchanged. This identifies
the package replacements, not the entire system closure blast radius. Image
and full-system output identities stay in protected integration evidence.

### Build inputs for the coordinator's sandboxed build

| Item | Path | Realised on the host |
| --- | --- | --- |
| `pkgs.nix` derivation | `/nix/store/w549lvx46kb0nxf14wrd8jh63495lyfv-nix-2.34.9.drv` | yes (aggregate, all four outputs) |
| `pkgs.nix.out` | `/nix/store/p715bsngf3drwygs5n2adp1qlwvmgxm7-nix-2.34.9` | yes |
| `pkgs.nix.dev` | `/nix/store/7circp9iggfd9l71ybv6nssiyrldvbn7-nix-2.34.9-dev` | yes |
| `pkgs.nix.doc` | `/nix/store/har7vh9g80iqifvn4zvmrlpwqxyqn6gv-nix-2.34.9-doc` | yes |
| `pkgs.nix.man` | `/nix/store/v35wp2jnah96naxqs1j0ismfvhpy34al-nix-2.34.9-man` | yes |
| `nix-functional-tests` | `/nix/store/8p41921m6byidlmid3zh35csf1gf5iy2-nix-functional-tests-2.34.9.drv` | yes (200 passed) |
| `pkgs.podman` (plain package) | `/nix/store/ql0md19nafvyzkwi1i4qafx8i2wyhz4a-podman-5.8.8` | built locally; not the effective unit package |
| effective podman for the units (NixOS helper override) | `/nix/store/j6pv741dy1afcnbcysg0kym2h48r6h5s-podman-5.8.8` | yes (bounded host build; install check passed) |
| `nix-nswrapper` (component) | built with the pinned scope | yes |

The pinned Nix is **not** in the binary cache: its derivation is built against
the dependency set of the pinned nixpkgs input, which predates the 2.34.9
bump, so no upstream build matches it. It **has been built on the host** with
`sandbox = true` (see "The full aggregate was built on the host"), along with
the functional suite and reused passing unit suites. The plain Podman build
does not establish cache availability for the effective NixOS helper variant;
the latter was absent from `cache.nixos.org` at the recorded check.

**All 12 packaged-unit sources were realised at the consumer readback.** The effective
NixOS Podman helper output was built from the immutable `as5ym3…` derivation
with its existing install check enabled; the build exited zero. Its output
NAR hash is `sha256-HnUrHyd6b/SoJOTsYJMfaFxWz8GHyG3Ci6nDhv9Qah4=`.
The plain Podman output remains a different package: the NixOS module applies
`extraPackages` and `extraRuntimes` through `pkg.override`.

The packaged consumer readback covered 53 files from those 12 sources. The
Podman service's actual `ExecStart` names the effective helper output, and
all 36 candidate OCI unit PATHs contain that output. This establishes those
consumers; it does not establish complete alias, dependency, runtime-override
or full-system activation readiness. The complete system unit tree and T3
image were not built by this step.

If a later change invalidates the aggregate, rebuild it with the sandbox
enabled, which is the host default (`nix.sandbox = true`). An unsandboxed
build hits the filename limit in the functional suite, as recorded above.

Build and daemon continuity: the pinned Nix and Podman are ordinary store
paths, so a deployment needs the effective builds present in the store (or
substitutable) before activation. The component and development-output layout
is preserved; that layout alone does not prove ABI compatibility or
uninterrupted daemon clients. Loaded unit behaviour and runtime continuity
remain activation checks.

### Reusing the build evidence

The recorded host runs built the immutable functional derivation's `out`,
then all four outputs of the immutable aggregate derivation listed above.
They used a direct local store inside a capped transient systemd unit,
not an unbounded daemon build: one job, two cores, sandbox enabled without
fallback, no remote builders, 6 GiB memory, no swap, 2048 tasks and 200% CPU.
Fresh memory/load checks and session/containment guards surrounded each run.
The first invocation failed before Nix executed because of PATH; the separate
second invocation passed. Reuse those successful outputs and passed checks.

The effective Podman target built in the final bounded run was
`config.virtualisation.podman.package`, derivation
`/nix/store/as5ym3aplvjq9bgi7wn03y4xs0z70x8r-podman-5.8.8.drv`
(SHA-256 `ace24255d437d4bd514e72d81f10a56b1bab3aac5200e882c5c97a1c982d6a23`).
It is not a substitute for the complete consumer review. No full toplevel
build or activation command was executed by these package builds. Future host
work must use the coordinated window and the same bounded-build and
[session preservation guards](container-workflow.md#preserve-the-active-t3-code-session).

### Activation dependencies of the affected units

- **Host** `nix-daemon.service` comes from the packaged unit in the Nix store
  path (`RequiresMountsFor` on the store and state dirs,
  `ConditionPathIsReadWrite` on the daemon socket). This host adds no
  `requires`, `after`, `before` or `wants` of its own; the generated
  `nix-daemon.socket` is wanted by `sockets.target`. On a switch the socket
  stays up and the service restarts.
- **Container image** `nix-daemon.service` is a different unit, written by
  `modules/self-hosted/t3code.nix` into the image with
  `After=`/`Requires=t3code-container-setup.service nix-daemon.socket` and
  `ExecStart=@<nix>/bin/nix-daemon nix-daemon --daemon`. It changes with the
  pin as part of the image, not as part of the host unit set.
- `podman.service` is socket-activated from `podman.socket`
  (`wantedBy = sockets.target`); it has no `[Install]` section, so it starts on
  the first socket connection after the switch, not at switch time.
- The `podman-*` container units order after `podman.service`,
  `init-ghostship-net.service` and, for `podman-t3code`,
  `mnt-share.mount`. Their restart does not restart `podman.service`.
- `podman-t3code.service` additionally requires
  `t3code-podman.socket`/`t3code-podman-ports.socket` when hardened, and keeps
  `restartIfChanged = false`, so the switch does not touch it.
- `t3code-deploy-when-idle.service` orders after `podman.service`; the timer
  is `Persistent = true`, so a missed run during the switch fires afterwards.
  This is the unit that recreates the T3 Code container.
- `t3code-nix-store-gc` orders after `podman-t3code.service` and never
  restarts the container.

### What changed across the unit set, and what is still pending

A source-integrated comparison of the custom unit fragments against the live
`overrides.conf` found **89 changed service fragments across 232 declared
units** (counting only fragments whose candidate text differs from the live
counterpart where an inherited upstream unit exists). That is the best
available count without materialising the full system-units comparison, which
this work does not do: the current dry plan has 6189 derivations, including
the full T3 Code image, and the cached functional-test result would appear
locally only because the host result has not been copied back.

The **packaged-unit and include/drop-in manifest is still pending**. The count
above covers custom fragments; it does not enumerate units whose content comes
wholly from a package (such as `podman.service`) or from `include`d drop-ins.
It must not be read as a complete manifest of every unit whose content changes.

Two classes of evidence are kept apart on purpose:

- **Source and metadata only** (cheap, does not build): the unit flag table in
  this section (read from `config.systemd.services.*`), the 89/232 fragment
  comparison, and the Nix packaged unit text read from the realised host output together
  with its drop-in, plus the effective Podman packaged unit from the completed
  helper build. The plain package cannot stand in for that helper.
- **Requires building, not done here**: a byte-exact comparison of every
  generated and packaged unit for the candidate against the live system. That
  would materialise the full system-units set (the current dry plan is 6189
  derivations, including the full T3 Code image), and the cached functional
  result would only appear locally because the host result has not been copied
  back. The host readbacks for that comparison are the coordinator's.

### Current runtime state

Nothing in this document has been activated. The host still runs Nix 2.34.8 and
Podman 5.8.6, no switch has been performed, the T3 Code identity, image and
generation are unchanged, the kernel deny hash is unchanged, and the
`security-package-fixes` build units are inactive. The activation window is
paused: no host build or activation is running now. The analysis above is
source and evaluation, plus the build evidence recorded earlier.

## Known limitation: the nixpkgs fallback paths file

Upstream nixpkgs keeps
`nixos/modules/installer/tools/nix-fallback-paths.nix`, a map from platform
to the store path of the released Nix tarball, and checks that it names the
same version as `nixVersions.stable`. In the pinned nixpkgs input that file
still names 2.34.8.

- The file belongs to the nixpkgs input. This repository does not own that
  input, and `flake.lock` is out of scope for this change, so the file cannot
  be repaired here.
- The file has **no runtime consumer in the pinned nixpkgs**. The installer
  takes Nix from `config.nix.package`
  (`nixos/modules/installer/tools/tools.nix`), and this change fixes exactly
  that option. The only readers of the file are the upstream check and the
  nixpkgs upgrade test.
- The upstream coherence check **cannot pass against a pinned input**: it
  reads a file of the input and compares it with the release this repository
  pins, so it is red by construction and stays red until the input moves.
  Carried over unchanged it would be a permanent failure that every consumer
  of the package set inherits, so it is **replaced by the check that decides
  whether the difference matters**:

  ```
  nix build .#nixosConfigurations.chill-penguin.pkgs.nixVersions.stable.tests.nix-fallback-paths
  ```

  The check reads the same file and the same NixOS module tree of the input,
  and it passes when the file names the installed Nix, or when the file names
  another release and nothing in the input's NixOS modules reads it. It fails
  when the file names another release **and** the input reads it, because
  then the difference reaches an installer that would fetch the release the
  advisory lists as affected. The failure message names the readers, so the
  state that needs the input to move is visible.

  This is not a check against a file this repository owns, so it cannot prove
  that the file matches itself, and it does not hide the drift: the build log
  prints the paths that are not up to date on every run.
- **Scope statement:** the installer fallback path is outside this host patch.
  This change fixes the installed Nix and the running daemon; it does not
  repair the nixpkgs input, and it does not claim that a fallback-path
  consumer would reach the fixed build.

## Other residual risk and scope

- `pkgs.nixVersions.latest` is still 2.35.2, which the same advisory lists as
  affected; the upstream fix for that line is 2.35.3. No host configuration in
  this repository references `nixVersions.latest`.
- The macOS Seatbelt escape and the macOS and FreeBSD daemon authorisation
  issues do not apply to this Linux deployment, but they are fixed by the same
  Nix release.
- The installer ownership issue does not affect NixOS installs. It is fixed by
  the same Nix release for any installer-based deployment.
- Rootless Podman is not affected by CVE-2026-94603. The host runs the rootful
  daemon, which is the affected case.
- The kernel is out of scope for this change. The Asahi kernel status is
  tracked separately.

## Known unverified coverage

- **No live aggregate-builder observation.** The aggregate finished too quickly
  to watch a live builder; the transient-unit limits, the cgroup and the
  live builder membership are observed for the functional derivation. The
  aggregate limit checks and completed `/build` log are recorded separately.
- **`nix-perl-bindings` was reused, not freshly exercised.** `x3m582…` was
  realised locally before the aggregate, and its original log (`7zjhc0m2…`)
  reports 1 passed and 0 failed. The aggregate reused it.
- The nixpkgs fallback-path check no longer fails by design. It proves that
  the drift between the input's fallback paths and the installed Nix cannot
  reach a runtime consumer, and it reports the paths that are not up to date.
  The drift itself is not fixed here and cannot be: the file belongs to the
  input.
- The `nix-misc`, `nix-upgrade` and installer tests that the upstream suite
  carries build NixOS test machines against the nixpkgs input's own Nix, not
  against the pinned build. They are carried over unchanged and are not a
  proof about the pinned build.
- The upstream suites run as part of building the pinned package. They are a
  regression signal for the pinned tree. The built aggregate executables
  `nix` and `nix-daemon` report 2.34.9; those version commands do not start or
  verify the running daemon. The evaluated unit path only shows
  which package the unit would run; it is not live evidence that a running
  daemon was patched, and nothing has been activated.
- The Podman behavioural proof was not run in its red form, against the
  vulnerable 5.8.6 build, because that is the exploit reproduction this work
  is not allowed to perform.
- A real multi-user daemon test that drives an unprivileged client into
  `AddToStore` with `repair = true` was not performed. The refusal is
  verified at the source and at the built artefact, not by exercising the
  daemon protocol.
- No deployment, switch, daemon restart or container restart was performed
  from this work. The activation analysis above is source and evaluation.

## Reverting

Remove the import of `./security-package-fixes.nix` from
`modules/common/default.nix`, or drop the overlay from
`modules/common/security-package-fixes.nix`. The pinned nixpkgs is unchanged,
so the reverted configuration resolves Nix 2.34.8 and Podman 5.8.6 again.

### Materialization after scheduled garbage collection

The midnight scheduled GC journal explicitly records deletion of the built
Nix component, aggregate, configured Podman and functional-test outputs.
A subsequent existence readback confirmed all four absent. Earlier build and
consumer checks remain historical evidence; the table above records that
build-time state, not current availability. No runtime activation occurred.

The daemon proposal now needs only the existing local fixed component and
its runtime closure restored, without rebuilding the aggregate or rerunning
passed tests. Its local registered identity is:

- output: `/nix/store/v79w10yddnaggxlvv8p6kwvv2d1zi47m-nix-2.34.9`;
- deriver: `/nix/store/33smi292kijbc6s3nfzykw0xrfhzi74p-nix-2.34.9.drv`;
- NAR: `sha256-hMAsjkcRlUZxnm5ykXHS+JR0t2EMtfAoaWIbd2R3Vwo=`.

The read-only closure inventory found 60 locally registered paths (about
179 MB of NAR data), with eight paths (about 18 MB) missing from the host.
An exact restoration proposal must verify this missing set again, create
an owned direct permanent GC root before importing those existing outputs,
and verify target registration, deriver, actual NAR hashes, full closure
and root ownership/inode before claiming current materialization. A dangling
root alone does not establish a valid output. Failed import leaves protected
ownership evidence for explicit recovery; no automatic root adoption or
broader rebuild is allowed. No restoration has been executed.

### Narrow host daemon mitigation proposal (not activated)

A host-only runtime override can select the fixed immutable `nix-cli` component
without switching the system generation or changing a profile. The packaged
unit resolves through this component, rather than executing the aggregate
directly. The proposed drop-in resets `ExecStart` and sets:

```ini
[Service]
ExecStart=
ExecStart=@/nix/store/v79w10yddnaggxlvv8p6kwvv2d1zi47m-nix-2.34.9/bin/nix-daemon nix-daemon --daemon
```

This remains a proposal requiring an exact guarded command and coordinating
review. Its consumers are the host daemon and new host daemon connections.
The socket remains active with its existing mode and inode; the host CLI,
inner image and other Nix branches remain unchanged. A socket connection may
queue during the restart; uninterrupted RPC service is not claimed.

The loaded host service uses `KillMode=process`. Restarting its main process
does not remove old per-client workers, so activation needs a fresh exclusive
maintenance window with no daemon workers, builders or connected clients,
followed by an old-executable scan. A main-process version alone is insufficient.
Postchecks must compare the executable of the running main process with the
fixed component and verify a fresh daemon-protocol connection, together with
socket, T3 identity, deployment-state and kernel-containment guards.

The latest read-only preflight found an existing pending image deployment.
The controller's existing `deploy.lock` can exclude it during maintenance,
but releasing that lease allows the pending replacement to resume. Queue
writers are not all serialized by that lease: the activation script writes
`desired` outside it, and `--safe-restart` writes `restart.pending` before
taking it. Compare bytes and existence before and after each maintenance
phase, abort on unexpected changes, and retain every newly arrived request.
Never restore an older queue snapshot over it.

Before releasing the lease, the reviewed plan must install and verify an
owned runtime start condition on the deploy service, covering both timer
and direct systemd starts. Preserve existing conditions and inhibitors. The
new inhibition stays installed after daemon maintenance until a separately
coordinated release reviews the pending destination and active sessions.
The existing daily/continuation campaign must report that retained hold;
no additional schedule is needed. Direct administrative `--force` execution
bypasses this service guard and remains excluded from the window. No timer
mask, queue edit or activation was performed.

A runtime override also needs the verified, explicitly owned GC root from
the restoration step for its fixed store path.
The reviewed operation must refuse foreign existing override/root paths,
install only its exact owned bytes atomically, and retain protected baseline
evidence. After interruption, reconcile those owned artifacts before retrying;
do not blindly restart the daemon again. Rollback removes only the matching
owned override, reloads the original unit and, in a fresh client-free window,
restarts only the host daemon. That rollback restores the vulnerable daemon;
it requires a concrete recovery decision, and must preserve the socket, queue
and active T3 session. This runtime overlay would not persist across reboot.
