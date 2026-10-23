# Independent T3 recovery

The host controller runs independently of the application container. It samples
health every 30 seconds and can request advice only after 300 seconds of
continuous, known downtime. Unknown observations reset continuity. Persistent
attempt records limit launches to three in a rolling day; a completed episode
rearms only after 600 seconds of continuous health. A restarted controller must
establish continuity again.

The owner's automation request dated 2026-10-23 authorizes eligible outage
remedies under this policy. The service configuration records its reference as
`owner-automation-request-2026-10-23`. The controller records that reference,
observations and outcomes in its durable ledger. A healthy application never
qualifies for an outage remedy. A failed HTTP request alone does not establish
that server and provider tasks have exited. Maintenance holds and deployment
activity suppress recovery. The controller implementation defines the exact
eligible remedies and rechecks its gates immediately before acting.

The static page and environment endpoint test HTTP reachability only. A separate
request to the native `/api/auth/session` endpoint validates the proxy's existing
private bearer session against the application's session database. The controller
reads that runtime credential without issuing or refreshing it and passes the
header over stdin, never command arguments or diagnostics. Timeouts and server
errors with static HTTP still responding are classified as `app-db-stalled`;
only advice is eligible, even if the advisor proposes a restart. A healthy native
authenticated check with a failed proxy is classified as `proxy-down`. Missing,
rejected or malformed authentication leaves health unknown and blocks repair.

## Operator controls

Use root SSH on the target host. Read `systemctl status t3code-recovery` and
`journalctl -u t3code-recovery -u t3code-recovery-advisor -u t3code-recovery-advisor-auth`
for the controller, advisor and credential preflight. Read the ledger and state
under `/var/lib/t3code-recovery` without publishing private runtime observations.
A missing proposal, invalid data or failed credential check consumes the attempt
and fails closed; it does not authorize a fallback command.

Create `/var/lib/t3code-recovery/hold` before maintenance. This persistent hold
survives reboots. `/run/t3code-recovery/hold` and
`/run/t3code-recovery/maintenance` are temporary holds. Remove the relevant hold
only after the application and maintenance state have been checked. Stopping
`t3code-recovery.service` disables the controller without stopping T3. Stop an
already running `t3code-recovery-advisor.service` as well when cancelling advice.
The advisor has no repair authority.

## Advisor boundary

The static advisor runs as UID/GID 3000 for at most 480 seconds with one CPU,
1 GiB memory and 256 tasks. It receives a fixed prompt and at most 64 KiB of
JSON diagnostics. Its proposal is at most 16 KiB and must match the controller's
schema. Model output is data; only the root controller chooses among fixed
operations. The controller itself has the same resource caps, a 1200-second
run bound and an unconditional restart with a 30-second delay.

A separate root preflight checks the real auth source before each advisor start.
It requires a regular file with mode 0600, UID 3000, one link, no symlink path
components, an access token valid for more than 1200 seconds and a refresh age
less than seven days. The sandbox checks that the bound auth inode matches the
preflight. The credential is never copied or printed. Its single read-only bind
retains the live inode, and the client refresh endpoint is overridden to the
closed local port `http://127.0.0.1:9`: an unexpected authorization failure must
fail closed rather than rotate the shared credentials. Refresh stale credentials
through the normal owner sign-in workflow, then wait for an eligible episode.

The advisor gets an empty private `CODEX_HOME`, no inherited secrets, user
configuration, MCP servers, skills or rule files. Shell, multi-agent, apps,
plugins, browser and web search capabilities are disabled. The filesystem masks
home directories, `/srv`, `/var`, `/workspace` and host `/run`. Only diagnostics,
schema, the auth identity record and the single auth file are bound read-only;
only the precreated proposal file is bound writable. All other writes stay in
private temporary filesystems. No Podman, systemd, D-Bus or SSH socket is passed.
The private temporary proposal is validated before overwriting the bound output
file in place. The controller treats even that validated output as untrusted.

## Process containment and deployment

The recovery module adds host units only. It does not alter the T3 image,
container definition or runtime process limits. Existing containment remains
owned by the hardening module and managed tooling.

Follow the [active-session deployment guard](container-workflow.md#preserve-the-active-t3-code-session).
The module exposes `system.build.t3codeRecoveryController`,
`system.build.t3codeRecoveryAdvisor`, `system.build.t3codeRecoveryConfig` and
`system.build.t3codeRecoveryUnits` for targeted builds and transfer. Updating these host recovery units must not restart
Podman, the application container or its inner server.

## Verification gates

`scripts/check` runs the fast controller and advisor input tests through
`scripts/check-unit.py`. The rendered Nix unit policy runs in
`scripts/check-integration` after merge. Tests use synthetic credentials and operations, never live service
restarts. Live advisor verification must use the exact pinned executable and
controller schema, read-only live credential binding, tool-free configuration,
and a synthetic healthy diagnostic that produces `action: none`. Confirm auth
metadata and credential contents remain unchanged without printing values.

The immutable client package is maintained in
[`codex.nix`](../packages/t3code/recovery/codex.nix). Client upgrades require a
fresh model/schema smoke and verification of the client's auth storage behavior.
The former host client 0.151.0 rejects the required model; substituting another
model is not an accepted fallback. A model/schema smoke alone does not verify
the rendered host sandbox. Until both gates pass, independent live recovery
remains unverified. A passing repository evaluation proves configuration and
unit policy, not host activation or recovery behavior under a real outage.

See [policy enforcement](policy-enforcement.md) for the rule-to-check mapping.
