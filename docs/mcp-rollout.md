# MCP deployment completion

The existing `ghostship-skills-reconcile` unit owns post-deploy plugin delivery.
It now runs for changes to either the general agent source or the independent
native MCP source. It does not replace the native relay, restart T3, change
plugin identity/app binding/permissions, or launch a test worker.

Existing coverage was package → content-idempotent `publish-chatgpt` → archive
`verify-chatgpt`, enabled on the deployment host. Its trigger covered only the
general agent source. Neither discovery refresh nor real consumer acceptance
was checked. Publication was therefore not proof of a usable consumer catalogue.

The small native Go command in `packages/mcp-rollout` extends that same unit:

1. `begin` invalidates the previous completion and server snapshot before
   waiting for container readiness or reading its start time. After readiness,
   `snapshot` invalidates again before validating that time, then makes a private same-UID MCP
   connection through the existing socket proxy. It reads actual Go
   `integration_status` and all catalogue pages; no native work is sent. It
   records the actual container start time and rejects retired facades or a
   missing native project/thread read API. A failed snapshot invalidates the
   preceding completion report.
2. `reconcile` checks the expected content-scoped runtime revision and fresh
   snapshot, then runs the existing publisher with the **selected native MCP
   source**, not an incidental installed CLI default. It validates the existing
   personal plugin/app binding and the package record's source, archive digest,
   `ghostship-review` skill and `references/agent-interfaces.md` before
   publication; plugin creation is forbidden. Before a changed publication,
   the operator must retain the previous archive and source in the state
   directory as described below. The unit rebuilds and hashes that artifact,
   then verifies its content and app binding against the currently served
   plugin; missing, corrupt or mismatched evidence stops before upload.
   A target release already matching readback does not need another upload.
   Dirty checkouts and unknown
   source provenance outside the Nix store are refused. The command rehashes
   the ZIP and the two source files against the package record. The existing
   archive builder validates file contents and in-archive Markdown link closure.
   One exclusive lock serializes startup invalidation, snapshots and reconcile.
   A durable intent is written before invoking the publisher. If acknowledgment
   is lost, later attempts stay held and never resend, even if matching content
   appears: another publisher may have created it while the original is still
   in flight. The supported publisher exposes no per-request terminal receipt,
   so automatic recovery remains unavailable. An operator must establish the
   original request is terminal and cannot apply later before clearing the
   private intent; a timeout or matching projection alone is not evidence.
3. Published archive verification must match content, skills, app binding,
   returned release ID and published version. A host-normalized version may
   differ from the build version; both are recorded, and normalization alone
   does not justify another upload. `release-manifest.json` binds the selected
   source SHA, observed native schema catalogue hash and tool names, container
   start, package file/ZIP/content digests, plugin/app/release and both versions.
   `manifest_sha256` binds consumer receipts to those exact manifest bytes.
   For a Nix-store source, the manifest records that the revision-to-path
   mapping comes from the configured flake pin; the store path alone does not
   independently prove a Git revision.
4. Discovery and consumer acceptance require deployment-bound operator receipts
   in the existing private skills state directory. Without them, exit **3** and
   `manual_required` are explicit; the unit cannot report rollout completion.

`/var/lib/ghostship-skills/rollout.json` records `server_deployed`,
`plugin_published`, `discovery_refreshed`, and `consumer_verified` separately.
Only all four verified stages set `complete:true`. Whole-host activation and
controller safety are separate. Source/build success is not installed success.
There is no new service, database, scheduler, inference loop or credential.
The container and desktop bridge are wanted and ordered rather than required:
a failed dependency therefore still lets the unit invalidate its old report.
The startup script checks the bridge and container before publishing. A report
is a dated observation, not continuous health: check current unit and dependency
state before treating it as current, including if systemd could not start the
unit or a dependency failed after the last successful run.

## Discovery and consumer receipts

The existing release CLI has no supported automatic ChatGPT discovery-refresh
or conversation-catalogue acceptance operation. The supported host step remains
**Refresh tools** in the existing app's ChatGPT settings. Do not claim that
uploading a skills archive refreshes every already-open conversation. If the
consumer retains retired declarations, explicitly require a fresh conversation
with the existing app enabled. Do not restore a retired facade.

An authorized deployment operator records `discovery.json` after the supported
refresh and `consumer.json` after observing the **real consumer's** tool
catalogue, a successful read-only `t3_project_list`, discovery of
`ghostship-review`, and reads of its skill and interface reference. These are private deployment
evidence inputs, not identity assertions or authorization grants. Use named
non-symlink files, not group/world-writable files, and link the observed evidence
on existing issue #540. The tool does not infer a real consumer test from its
own private-socket readback or a simulated development fixture.

Both JSON receipts carry the following exact binding, copied from the current
rollout report: `connector_version`, `catalogue_hash`, `started_at`, `plugin_id`,
`app_id`, `release_id`, `content_digest`, and `manifest_sha256`. They also carry an RFC3339
`observed_at` at or after that deployment and a GitHub `evidence_ref` URL.
Discovery adds `"refreshed":true`. Consumer adds:

```json
{
  "native_tools": ["all names observed in the actual consumer catalogue"],
  "consumer_catalogue_sha256": "hash computed from the actual consumer schemas",
  "retired_facades_absent": true,
  "read_tool": "t3_project_list",
  "read_outcome": "returned",
  "discovered_skills": ["ghostship-review"],
  "skill_read_path": "skills/ghostship-review/SKILL.md",
  "skill_read_sha256": "digest of the content actually read",
  "skill_read_outcome": "returned",
  "reference_read_path": "skills/ghostship-review/references/agent-interfaces.md",
  "reference_read_sha256": "digest of the content actually read",
  "reference_read_outcome": "returned"
}
```

The consumer catalogue hash must be independently obtained from the consumer's
observed tool records using the connector's catalogue serialization, not copied
from server health. If the host does not expose the necessary schemas or skill
contents, that check stays pending; neither a socket probe nor archive readback
substitutes for real consumer observation.

The consumer observation must follow discovery. Changing the running revision,
catalogue, container start, plugin release or package content invalidates old
acceptance. A rerun of the same unchanged deployment can reuse its receipts;
no duplicate upload, test message, test worker or paid inference is necessary.
After supplying the missing receipt, restart only `ghostship-skills-reconcile`.

## Native development and rollback

Run `nix develop .#mcp-rollout -c ./tools/dev/mcp-rollout`. Pure validation and
parallel real-process scenarios cover publication/restart, lost acknowledgment,
wrong app binding, pending/stale consumer evidence and failed server readback.
Only the unchanged external publisher and connector are doubled. The private
proof directory includes actual stage/file effects, execution timings and the
unit plus instrumented-running-binary coverage union; development fixtures are
not installed acceptance. Run existing focused configuration checks with
`nix develop .#ci -c python3 -m unittest tests.test_mcp_runtime_entrypoint tests.test_private_integrations_desktop`.
The CI dev shell includes the same tested native package exposed by
`checks.<system>.mcp-rollout`; its normal Nix check phase runs the native tests.
Unchanged package sources reuse the normal cache. The fast check script does
not add a fleet evaluation or an inner Nix invocation.

Before a changed publication, retain the last-known-good ZIP under
`/var/lib/ghostship-skills` (mode 0600), and retain its clean source checkout or
Nix store source on the deployment host. Create mode-0600 `last-known-good.json`
in that same directory with `repo` (absolute source path), `source_sha` (full
40-character commit), `archive` (absolute path to that ZIP in the state
directory), and `archive_sha256` (its SHA-256). The unit rebuilds it using the
existing publisher and verifies it against the currently served plugin before
calling publish. It never deletes the retained artifact. A Nix-store source's
commit mapping must be checked against the prior deployed configuration by the
operator; a store path alone is not a Git revision receipt.

A published release with missing refresh or consumer evidence remains partial.
If actual availability fails, promptly notify the owner with the release ID,
report and retained-artifact paths; the owner alone decides and performs any
rollback. The operator observing the failure is responsible for that message.
The configured systemd failure hook routes failed unit status to the operations
notification service, but delivery to the owner and detection of failures in
an already-running consumer are not established. A pending receipt is not by
itself proof of an availability failure. Do not automatically restore. If an
upload outcome is unknown,
leave its intent intact and do not retry or start a competing rollback while
the original request may still apply. Establish its terminal outcome first.
The retained archive is a recovery aid; the host's ability to re-upload old
content and restore consumer availability has not been established. Restoring
this unit/tooling does not itself undo a published plugin version.
