# Announced Codex resets

The announcement checker uses the personal Agent Desktop profile at most once
per eight hours. A sign-in or verification wall is recorded as blocked. When X
is blocked, the checker searches the community announcements category for reset
topics, reads at most three matching topics, and records their source status.
It never bypasses a wall or fetches a mirror outside Agent Desktop.

The AI usage dashboard lists recorded announcements with their source links.
A community relay is **announced (unverified)** even when it includes a precise
time. It raises an operations notification and leaves pacing unchanged.
Notifications retry on subsequent checker runs until publication succeeds;
successful notices are remembered across rediscovery.

After inspecting the linked announcement and confirming that it resets global
Codex limits, run this command as root on the collector host:

```sh
ghostship-ai-confirm-reset SOURCE_URL RESET_AT_WITH_TIMEZONE
```

Use the exact source URL from the dashboard, including its announcement
fragment. Supply an ISO 8601 time with an explicit timezone. Confirmation
requires an existing recorded announcement and a future reset within seven days.
The next regular collector run publishes the confirmed reset and recalculates
pacing through the existing custom-reset path, labelled **announced reset**.
The provider's reported usage stays intact; an earlier provider reset wins,
and an owner-set custom reset remains authoritative. Expired announcements
remain visible as history and do not change capacity.

The root-owned announcement cache is
`/var/lib/ghostship-ai-usage/announced-resets.json`. Discovery, notice receipts
and confirmation share its lock and atomic replacement, so a scrape cannot
revoke a confirmation. Only URLs, scope, times, confidence and fixed reason
codes are retained; page prose is discarded.
