# Announced usage-limit resets

The checker reads the primary account's visible X `with_replies` timeline and
each same-author post thread hourly through the persistent personal Agent
Desktop profile. It collects posts and replies published in the last 75 minutes,
so adjacent runs overlap. A sign-in wall or challenge records blocked, sends one
operations notice per blocked episode, and delays the next read eight hours. It
never handles or bypasses protection. A locked deadline covers timer/manual
starts; before classification, the batch is saved with its stable request key
so a process restart can resume the same durable free-pool job.

The whole public batch is classified once by the shared free-pool helper using
a strict JSON schema and request-key idempotency. Provider errors and invalid
JSON retry on other approved free routes with backoff. No paid route is used.
The worker returns a judgement for every supplied post and reply, including
non-reset items. Code validates the author, exact post URL, publication time,
source quote (at most 240 characters), scope and seven-day reset bound. Missing,
malformed or unanswered results stay unclassified and pending; no regex guess
can create an event. Notice receipts remain append-only and deduplicate by
primary status URL. Failed publications retry; at most twenty new-post
publications are attempted per run.

A confirmed event affects only its products, plans and windows. An unqualified
product-wide announcement covers that product's plans; an explicitly limited
plan requires a matching measured plan and does not apply to an unknown plan.
A weekly Codex reset cannot reset a five-hour window or ChatGPT. A scheduled
future reset changes that matching window's effective reset time. An earlier
provider reset wins. An owner-set custom reset remains authoritative.

After an explicitly announced reset has happened, it supersedes a matching
measurement only if that measurement predates the reset. The effective usage
starts at zero at the announced time, with the next reset derived from the
known window duration. The original provider usage, observation time and reset
remain separate provenance. Evidence is labelled `announced_reset`, never
provider-reported. A newer provider reading wins. Normal freshness applies at
the reset time, not discovery time; rediscovering an old post grants no fresh
capacity. Other or unknown limit windows continue to constrain the picker.

The Providers page can place this series next to the matching account's "% left"
bar (filter `provider="codex"` for Codex):

```promql
ghostship_ai_announced_reset_info{provider="codex"}
```

Each row has value 1 and labels `source_url`, `provider`, `scope`, `plans`,
`windows`, `published_at`, `quote`, `reset_at`, `confidence` and `label`.
Confidence is `high`, `low` or operator-set `confirmed`; low displays **announced (unverified)**.
`reset_at` is a UTC ISO timestamp or "time needs confirmation". The series emits
one row per product per event, with at most 100 retained events. `source_url`
is always the primary post link. The routing snapshot carries the same event
under `announced_resets.announcements`. Effective quota windows expose
`announcement_url`, `announced_reset_at`, `provider_used_ratio` and
`provider_check_at` beside their reset provenance.

## Monitor health

The routing snapshot carries `announced_resets.health` with `state` (`ok`,
`blocked`, `stale` or `unknown`), `last_read_at`, `last_success_at`,
`last_success_age_seconds`, `blocked_since`, `last_blocked_at` and `events`.
`ok` requires a successful read within three hours; a failed or blocked read
keeps the previous success time and is published as `stale` or `blocked`. The
state is also published as:

```promql
ghostship_ai_announcements_health{state,reason}
ghostship_ai_announcements_last_success_timestamp_seconds
ghostship_ai_announcements_events
ghostship_ai_announcements_classification_pending
```

`AnnouncementMonitorStale` fires after three hours without a successful read,
and `AnnouncementMonitorBlocked` fires when a sign-in wall or challenge is
recorded. Neither alert handles or bypasses the challenge: the monitor backs
off eight hours and sends one operations notice per blocked episode.

An operator can confirm an existing ambiguous event's reset time as root:

```sh
ghostship-ai-confirm-reset SOURCE_URL RESET_AT_WITH_TIMEZONE
```

This preserves its classified product, plans and windows; confirmation cannot
broaden an unknown scope to all Codex windows. The time must be timezone-qualified,
in the future and within seven days. The next collector run applies it.

The root-owned cache is `/var/lib/ghostship-ai-usage/announced-resets.json`.
Discovery, notice receipts and confirmation share its lock and atomic writes.
Only bounded public announcement evidence is retained; credentials and account
identity details are never read or stored.
