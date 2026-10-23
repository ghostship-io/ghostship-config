# Container runtime updates

GhostShip service images contain base utilities and image parameters. Agent code,
service clients and worker tools are delivered separately from ghostship-agent.
`container-runtimes.nix` copies each runtime's closure into its own root-owned Nix
store and publishes an atomic `current` link. Containers mount only that private
store and link directory, read-only; they never mount the host store or another
container's store. This follows T3's separate tool-store delivery boundary.

The hooks, coordinator and private-integration entrypoints use that link. Their
publisher requests a restart only when the service's own content changes. A
release version, revision or unrelated agent source change leaves these runtimes
unchanged. The worker container only holds a sleeping base runtime: publishing
its tools does not recreate it. Its host-managed broker and scheduler own their
process lifecycle. Old closures remain rooted so updates cannot invalidate a
running process's imports or libraries.

Publishers and dashboard configuration services are ordered before containers
with `Wants`/`After`. They must not become `Requires`, `BindsTo` or `PartOf`
dependencies: restarting a required helper can stop a running container even
when its unit is unchanged. A failed initial publication fails container startup
because its entrypoint is absent. Publication errors preserve the previous link.
A rejected restart request stays retryable after link publication.

Homepage and Muximux reconcile configuration in independent host oneshots. App
registry, dashboard-sync and ghostship-config updates rewrite their configuration
files while the containers keep running. Nginx configuration changes still need
an intentional application reload when applicable.

The first activation of this change recreates the four GhostShip service
containers once to establish the new image and mounts. Later code publications
reuse those images. Dashboard units also change once when removing their
pre-start reconciliation. Cloudflared and Agent Desktop definitions are unchanged.
Podman upgrades remain accepted restart triggers.

Fast validation runs through `scripts/check` and includes image independence,
content-scoped source identity, publication retries and dependency propagation.
The post-merge suite also checks real SDK/runtime derivations; the fast gate
perturbs the authoritative source selector without evaluating that package graph.
To inspect the restart impact of two built generations, run on the machine that
has both store closures:

```sh
python3 scripts/check-container-restarts.py \
  /path/to/previous/etc/systemd/system /path/to/candidate/etc/systemd/system
```

It lists every Podman container, changed units, propagated dependency stops and
changed runtime publishers. A publisher change is a restart candidate: it checks
the actual code pointer before requesting a restart. The command fails on broad
agent-source references or dashboard reconciliation embedded in container units;
it follows referenced executable store scripts without reading secret files.
This report complements dry-activation; it does not predict imperative hooks,
image auto-update timers or manual restarts.
