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
   personal plugin/app binding before publication; plugin creation is forbidden.
   The existing publisher reconciles its current release before uploading and
   skips identical content. No retry is added after an uncertain acknowledgment.
3. Published archive verification must match content, skills, app binding and
   the returned release ID. A host-normalized semantic version is allowed;
   version normalization alone does not justify another upload.
4. Discovery and consumer acceptance require deployment-bound operator receipts
   in the existing private skills state directory. Without them, exit **3** and
   `manual_required` are explicit; the unit cannot report rollout completion.

`/var/lib/ghostship-skills/rollout.json` records `server_deployed`,
`plugin_published`, `discovery_refreshed`, and `consumer_verified` separately.
Only all four verified stages set `complete:true`. Whole-host activation and
controller safety are separate. Source/build success is not installed success.
There is no new service, database, scheduler, inference loop or credential.

## Discovery and consumer receipts

The existing release CLI has no supported automatic ChatGPT discovery-refresh
or conversation-catalogue acceptance operation. The supported host step remains
**Refresh tools** in the existing app's ChatGPT settings. Do not claim that
uploading a skills archive refreshes every already-open conversation. If the
consumer retains retired declarations, explicitly require a fresh conversation
with the existing app enabled. Do not restore a retired facade.

An authorized deployment operator records `discovery.json` after the supported
refresh and `consumer.json` after observing the **real consumer's** declarations
and one successful read-only `t3_project_list`. These are private deployment
evidence inputs, not identity assertions or authorization grants. Use named
non-symlink files, not group/world-writable files, and link the observed evidence
on existing issue #540. The tool does not infer a real consumer test from its
own private-socket readback or a simulated development fixture.

Both JSON receipts carry the following exact binding, copied from the current
rollout report: `connector_version`, `catalogue_hash`, `started_at`, `plugin_id`,
`app_id`, `release_id`, and `content_digest`. They also carry an RFC3339
`observed_at` at or after that deployment and a GitHub `evidence_ref` URL.
Discovery adds `"refreshed":true`. Consumer adds:

```json
{
  "native_tools": ["t3_project_list", "t3_thread_list", "t3_thread_read"],
  "retired_facades_absent": true,
  "read_tool": "t3_project_list",
  "read_outcome": "returned"
}
```

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

Rollback reverts this unit/tooling change; it does not roll back an independently
published plugin or a healthy native MCP server. Keep the existing plugin
identity and original receipts. No upload is needed to remove the added gate.
