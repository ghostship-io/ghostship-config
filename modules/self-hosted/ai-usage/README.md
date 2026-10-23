# AI usage collection contract

One host service, `ghostship-ai-usage.service`, refreshes a single
node_exporter textfile every five minutes. VictoriaMetrics scrapes it with the
rest of the host, and the Grafana dashboard in `dashboard.json` (provisioned
into the "Ghostship" folder by `modules/self-hosted/siem/ui.nix`) reads it
through VictoriaMetrics only.

Nothing here changes a provider, a container or T3 Code. The collector starts
no inference, rotates no credential, opens no account and writes nothing
outside its own output file and its own ranking state. There is no new
listener and no new port: the service is a oneshot job that writes a file.

## How it runs

* Unit: `ghostship-ai-usage.service` (`Type=oneshot`), timer
  `ghostship-ai-usage.timer` (`OnUnitActiveSec=5min`, `AccuracySec=1s`,
  `Persistent=false`).
* Command: `python3 <store>/collector/main.py --output
  /var/lib/ghostship-container-metrics/ai-usage.prom --state
  /var/lib/ghostship-ai-usage/state.json`. `--output` is the Prometheus
  textfile node_exporter reads; `--state` is the ranking's own JSON state
  (first seen, evaluation count, staleness). `--stdout` prints instead of
  writing, for a manual run. `--runtime-policy` is the runtime policy that
  carries the owner's static worker routes; the unit passes the pinned
  `ghostship-agent-policy` input's
  `config/agents/runtime-policy.json`. `--model-identities` is the model
  identities beside that policy, `--delegation-ledger` the ledger of the
  observed rounds and `--delegation-backfill` the rounds the ledger does not
  carry. All four are read only, and a file that is missing is an empty
  history.
* Directories: `/var/lib/ghostship-container-metrics` (0755) and
  `/var/lib/ghostship-ai-usage` (0700), both created by systemd-tmpfiles.
* The routing switch: `ghostship.aiUsage.routing.enabled` is the owner's
  switch, it is off by default, and the collector receives it as
  `--routing-enabled true|false`. The collector publishes the switch to its
  consumers and never acts on it itself.
* The collector is Python standard library only. The unit is hardened like the
  rest of this repository: `ProtectSystem=strict`, `ProtectHome`, no
  capabilities, `ReadWritePaths` limited to the two directories above, and
  read-only access to `/srv/apps/t3code/home`, `/run/ghostship-integrations`
  and `/run/ghostship-secrets`.
* The two request records are read from the container home, read only, and
  the OpenCode reader keeps its cache of the events in the state directory
  (`/var/lib/ghostship-ai-usage/opencode-events.json`). The reader's cache
  is its own state, and the path can be moved with `--events-cache`.

## Sources and what each one reads

Every source is read-only and every source reports its own outcome. A source
that cannot be read reports a status; it never reports a healthy zero.

| Source | What it reads | Where from |
| --- | --- | --- |
| `t3` | Provider limits: the subscription windows T3 Code knows about (Codex, Claude, Grok, OpenCode Go, Antigravity), their used share, their reset time and the time the provider checked them | T3 Code's read-only RPC (`server.refreshProviders`, `server.getConfig`) |
| `t3_usage` | The usage summary: daily and hourly token and cost buckets over `24h`, `7d` and `30d`, plus the records T3 could not price | T3 Code's read-only RPC (`server.getUsageSummary`) |
| `grok` | The credit billing of the Grok CLI account: used share of the current period and the period end | `cli-chat-proxy.grok.com`, with the Grok CLI credential |
| `opencode-go` | The Go subscription windows: rolling (session), weekly and monthly used shares, their resets, and the status the provider reports; the free Go routes the documentation lists as unlimited | `opencode.ai/zen/go/v1/usage`, with the credential OpenCode itself holds |
| `antigravity` | Both quota views Google exposes: the shared family windows (5-hour, weekly, shared) and the per-model quotas that T3 merges away | Google's `cloudcode-pa` quota endpoints, with the stored account token |
| `openrouter` | Credits, key usage per window, the spend cap, the free-tier flag, the free-model allowance as a daily window, and the published per-minute limit counted against our own requests | `openrouter.ai` credits and key endpoints, plus the T3 Code state for the count |
| `ollama` | The request counts of the Ollama Cloud account per window, and the session and the weekly window of the account | `ollama.com/api/usage` and `ollama.com/api/balance` |
| `free_pool` | The free inference pool: the provider states with the pool's own probe of each route and the reason it parks a candidate, the paged model catalog with geography, availability, selection, cooldown and admissions, the local admission limits, the health history, the observed latency, the concurrency, the recent jobs, and the quota amounts seen in provider headers | The broker's read-only status surface over its Unix socket, plus the pool's own reservation ledger |
| `opencode_events` | The request records of the routes the agents use, and the capacity they imply: the events of every request, and the window, the budget, the scope and the remaining share they add up to | OpenCode's own SQLite database, read only, with the collector's cache of the events in its state directory |
| `pool_events` | The request records of the free pool's routes, and the capacity they imply | The free pool's own reservation ledger, read only |
| `model_catalog` | The models that can be used at no cost right now and their per-million-token prices | OpenCode's cached copy of the public models.dev catalog |

The 3D reading is not a provider source: it is the measured use of our own 3D
printing projects. Only session history files inside a directory whose name
mentions `3dprint` are read, only for the last 30 days, and only a bounded
number of files.

## The OpenCode request record

OpenCode records every model request it makes: the provider, the model, the
tokens, the instant, and, when the request failed, the provider's own error.
That record is the primary evidence for a route that is used through
OpenCode, and the collector can infer a route's window and budget from the
limit failures in it (the owner rule is in ghostship-agent's
`config/agents/routing-policy.md`, "Usage measurement").

The reader is `collector/opencode_reader.py`. It reads the SQLite database
OpenCode keeps at `.local/share/opencode/opencode.db` inside the container
home. It is a source now: the collector reads it as `opencode_events`, and
the capacity it implies is published with the route it belongs to. What it
produces is fixed:

* `status` is `ok` or `unreadable`, and `reason` is a fixed code
  (`ok`, `database_missing`, `database_unreadable`, `database_corrupt`,
  `database_schema_missing`, `timeout`). A reading that cannot be made is
  never a reading of zero usage.
* `events` is one event per request: the collector's provider name, the
  model id as recorded, the instant in epoch seconds, the outcome
  (`success`, `limit` or `other`), the tokens used (`None` when the record
  has none), and the window the failure named (`None`, `5h`, `7d` or `1d`).
* `counts` holds the rows read, the rows whose provider is not in the
  mapping table, and the events per outcome.

Only a budget failure is a limit. A request that stopped for `stop`,
`tool-calls`, `length` or `content-filter` is a success. A refusal that
names the account's allowance is a limit, and the window it names is used
when it names one: a session usage limit is five hours, a weekly usage limit
is seven days, a daily limit is one day. A concurrency refusal, a per-minute
refusal, a transient upstream refusal, a request that was too large, an
expired key, an aborted run and a timeout spend no window, so they are read
as `other` and never as a limit. A request that carries a retry is one
event, with the outcome it ended on.

The provider table is committed, not guessed. The OpenCode provider ids
`ollama-cloud`, `opencode-go`, `opencode`, `openrouter`, `google`,
`requesty`, `nvidia`, `ovh`, `upstage`, `inception`, `groq`, `mistral`,
`cohere`, `zai`, `vercel`, `poolside` and `orcarouter` are mapped onto the
collector's provider names. Every other provider id is counted and not
emitted.

The read is read only and it is bounded: the database is opened with the
`mode=ro` URI, nothing in the reader writes to it, every query asks only
for the last 35 days, the whole read has a wall clock limit of 20 seconds
that aborts the query when it is reached, and the connection is closed on
every path so no read transaction is left open.

The query asks only for the fields the reader uses: SQLite extracts them
from the record with its own JSON functions, so the whole record, about
27 KB a row, never travels into Python. The error's own words come with
the extraction and are classified in memory.

The reader keeps its own cache: a file in the collector's state directory
that holds the compact events, the cursor and the instant the history is
complete from. A run reads only the rows the last run may not have seen,
with two hours of overlap, so a row OpenCode inserted at the start of a
step and completed later is read again; the events of that window are
replaced by the ones the run read, and the events older than the window
are pruned. The cache is written beside itself and renamed over the old
one, so a reader never sees half of it, and it never holds the text of a
provider's error.

The history is filled a slice at a time. With no cache, a run reads the
newest slice of three days. With a cache whose history starts later than
the window allows, a run reads one slice of at most three days, walking
back from the start of the history, inside the same cap. The reading is
`partial` until the history reaches the whole window, and it carries the
instant the history is complete from. A slice that runs out of time leaves
the cache as it was and is read again by the next run; the part that was
read still counts.

A cache that does not parse, or that does not carry the shape the reader
expects, is discarded and the backfill starts again. A cache is never
trusted for an event that is dated in the future: those events are
dropped.

The text of a provider's error is read in memory, to pick the outcome, and
it never leaves the process: it is not stored, not returned, not logged and
not in an event. A real limit message names the account it belongs to.

## The free pool's job ledger

The free inference pool records every request it dispatches in a durable
ledger: one reservation row per dispatched request, and one attempt per
attempted route on the job's receipt. A free route reports no usage of its
own, so the collector infers its capacity from its limit failures (the
owner rule is in ghostship-agent's `config/agents/routing-policy.md`,
"Usage measurement"), and the ledger is where the use of the route is
recorded. The pool's own limits are admission caps and are never a
capacity reading.

The reader is `collector/pool_reader.py`. It reads the SQLite ledger the
pool keeps at `.local/state/ghostship-agent/runtime/jobs.sqlite` inside the
container home. It is a source now: the collector reads it as
`pool_events`, and the capacity it implies is published with the route it
belongs to. What it produces is fixed, and it is the same
contract as the OpenCode reader:

* `status` is `ok` or `unreadable`, and `reason` is a fixed code (`ok`,
  `ledger_missing`, `ledger_unreadable`, `ledger_corrupt`,
  `ledger_schema_missing`, `timeout`). A reading that cannot be made is
  never a reading of zero usage.
* `events` is one event per request: the pool's provider name, the model
  id as recorded, the instant in epoch seconds, the outcome (`success`,
  `limit` or `other`), the tokens used (`None` when the ledger holds none),
  and the window a limit named (`None` or `1d`).
* `counts` holds the attempts read, the probes read, the attempts that had
  no reservation, and the events per outcome.

The attempt's category decides the outcome. A success is a success. A quota
exhaustion is a limit and names no window; the daily exhaustion of the free
allowance is a limit of the day. Every other category is not a limit of the
route: a rate limit, an upstream error, an unavailable model, a context
limit, a credential failure and an unexpected tool are all something else.

An attempt takes the reservation of its route: the k-th attempt of a job
and route takes the k-th reservation of that job and route, in time order.
An attempt with no reservation was never dispatched, and it is counted and
not emitted. A failed attempt contributes no usage, because the estimate
the pool writes before a dispatch is not consumption; only a success carries
the usage the pool settled onto its reservation. A probe - the pool's own
check of a route - has a reservation and no receipt, so it is an event of
its own: an `other` with the usage it consumed.

The read is read only and it is bounded: the ledger is opened with the
`mode=ro` URI and nothing in the reader writes to it, so the running pool
keeps its own ledger. Every query asks only for the last 35 days, the whole
read has a wall clock limit of 20 seconds that aborts the query when it is
reached, the busy timeout is 2 seconds, and the connection is closed on
every path so no read transaction is left open.

## The inferred capacity of a route

The providers that report no usage, and every free route, showed "Limits
unknown" on the Providers page. The owner rule reads their capacity from
their limit failures instead, and the collector now does that.

`collector/usage_inference.py` is the wiring between the two readers and the
inference (`collector/inference.py`, which does the computation and reads no
file). Every run reads both records at the same time, puts their events on
the routes of the collector's inventory, and infers the capacity of every
route they touch. The two reads run together and each of them caps itself
at twenty seconds, so the pair never holds the collector.

The rules:

* A reported reading always wins. A route that reports its usage keeps its
  reported window, and a route whose account already carries a window keeps
  that one. An inference is never published over a reading.
* The window of an inferred route is keyed by the route when the limit is
  the model's own, and by the provider when the limit belongs to the
  account. A provider whose published rate limits apply per model has no
  account pool to share: Google's Gemini API documents its limits per
  project and per model (<https://ai.google.dev/gemini-api/docs/rate-limits>),
  and Groq documents its limits per model and per organization
  (<https://console.groq.com/docs/rate-limits>), so every refused route of
  either provider is its own model, with the window and the budget of its own
  events, whatever the evidence of another provider would say. For every
  other provider the scope of a limit with no other model in its span is the
  account, and it is labelled `unknown`.
* The window of a route that was never refused reads like the window of a
  route the provider publishes as unlimited: all of the allowance is left,
  there is no pace, and the headroom is never unknown.
* A route that was refused and has not worked since is spent for the learned
  window that holds the refusal: it has nothing left until that window ends.
  Once that window has rolled over the route reads available again, with all
  of its allowance and a window that starts at the rollover; a refusal in
  the new window spends it again.
* The quota id of an inferred window names the window it was learned from
  (`inferred:1h`, `inferred:5h`), not the state of the route. A refusal with
  no learned window reads `inferred:exhausted`, and a route that was never
  refused reads `inferred:no-limit-seen`.
* A window that ends inside the collector's own run interval of five
  minutes rolls. The collector reads the request record every five
  minutes, so the instant the inference measured is already past by the
  time the reading is published: the page showed "resets in 0m" for a
  window of a minute. Such a window keeps its length and carries no fixed
  reset, and the inference behind it says that it rolls.
* An event whose route is not in the inventory is counted and published as
  unmatched. A reading never invents a route. The model ids are matched
  exactly, and apart from their case: a provider may spell a route id in
  another case, and the case is not part of the route. Two routes that
  differ only in their case are never guessed between.
* A record that cannot be read is reported as unreadable with the reader's
  own reason code, contributes no events, and never fails the run. The
  routes it would have fed keep the basis they had.

## The windows and where their numbers come from

A window is only headroom when it carries three things: the share of the
window that is used, the instant it resets, and how long it runs. A window
without one of them is visible and it does not constrain a route, because an
unknown reading is not evidence that an account is exhausted.

Every window carries the basis of its numbers, and the bases are never mixed:

| Basis | What it means | Which windows |
| --- | --- | --- |
| `provider_reported` | The provider reported every number of the window | The Grok, Groq, Antigravity, OpenCode Go, OpenRouter daily and Ollama windows |
| `provider_reported+derived_length` | The provider reported the share and the reset, and the length of the window is derived | The Ollama session window, whose length is learned from the step between two successive resets |
| `promotion` | The provider's documentation publishes the allowance for a limited time, and no end date | The OpenCode Go free routes, which the documentation lists as unlimited "for a limited time" |
| `published+counted` | A published limit, counted against the requests we made ourselves | The OpenRouter per-minute limit of the free models |
| `inferred from N limit episodes` | The window was inferred from the limit failures of the route: the episodes, the window they ran over and the budget they reached | The routes of the request records the inference measured |
| `inferred: no limit failure in the records` | The route was never refused in the record, so nothing is measured: all of the allowance is left and there is no pace | The same |

The length of the Ollama session window is the one number no endpoint
publishes. The collector remembers the reset instants it has seen
(`/var/lib/ghostship-ai-usage/ollama-windows.json`, reset instants and
nothing else) and measures the length from the step between two successive
resets. Until two resets have been seen the length is a derived fallback, and
it is marked as derived: it is never published as a measurement.

The OpenRouter free models share one allowance: the number of free model
requests the key may make in the current UTC day. The key endpoint reports
how many of them are left, the day ends at midnight UTC, and a counter above
the limit means the day is spent. The per-minute limit of the free models is
published rather than reported, so the collector counts the requests we made
in the last minute in the T3 Code state and counts them against the
published number.

The Go free routes are a different thing from a route that costs nothing
because of a promotion. The Go documentation lists them as unlimited, and a
live probe confirmed it: a free route answered while the paid monthly
window of the plan was at 100% used, and the paid route of the same provider
did not. The same documentation says the free models are unlimited "for a
limited time", so the basis of those routes is `promotion` and the end of
the promotion is unknown: the documentation publishes no end date, and an
unknown end is never a guess. Each of those routes carries a window of its
own, the window says `unlimited (limited-time promotion)`, and the paid
allowance of the account does not gate them. The paid routes of the same
account are gated by it, as they were. A route the collector observed to be
broken is still unavailable: the observation of the route beats the
published listing.

The basis of a window and the end of its entitlement are published twice:
the row of the routing snapshot carries them beside the capacity, and the
entitlement series carry them as the labels `basis` and `ends_at`. An end
that the provider does not publish is an empty label, never a zero.

## Metrics

Every metric is a gauge: the collector reports the value it read at this
collection, and it never keeps a counter of its own. Labels never carry an
email, an account identifier, a path, a key, a prompt, a job id or a raw error
message; provider names, model ids, window names and non-secret account aliases
are all that reach a label.

### What a time range can answer

The dashboard has one time picker for every panel, so the meaning of a series
over a range has to be stated per series. There are four kinds, and none of
them is a monotonic counter:

| Kind | Series | Over a range |
| --- | --- | --- |
| Rolling provider window | `ghostship_ai_usage_tokens`, `ghostship_ai_usage_cost_usd` (window `24h`, `7d`, `30d`), `ghostship_ai_pool_ledger_requests`, `ghostship_ai_pool_health_events`, `ghostship_ai_three_d_usage_tokens` (last 30 days) | Each sample is the provider's rolling total at that moment. The series answers "what did the last 24 hours look like at 10:00" and "is the 7-day window growing", not "how much in the selected range". A decrease is the window moving, not a counter reset, so `increase()` and `rate()` are wrong. |
| Instantaneous quota | `ghostship_ai_quota_used_ratio`, `ghostship_ai_quota_reset_timestamp_seconds`, `ghostship_ai_quota_state`, `ghostship_ai_account_amount`, `ghostship_ai_account_flag`, `ghostship_ai_model_capacity_remaining`, `ghostship_ai_model_available` | An as-of reading of the provider's own window. A range shows how the window filled and when it reset; it does not sum. |
| Recorded observation | `ghostship_ai_source_*`, `ghostship_ai_collection_*`, `*_observed_timestamp_seconds`, `ghostship_ai_model_*`, `ghostship_ai_model_winner*`, `ghostship_ai_calculation_*` | A snapshot of the collector's own decision at that collection. The value is replaced each run, so a range is a history of decisions, never a sum. |
| Counter | none | The collector owns no counter. Every source reports a window or a state, so no `_total` series is published and `increase()` on any series here is invalid. |

Exact totals for an arbitrary selected range are therefore not available from
these series. The 24h/7d/30d windows are the provider's own rolling totals,
and a custom range needs the per-event usage history that T3 Code keeps, not
this textfile. This is a stated gap, not an approximation: a panel that wants
an exact range total must read the history source, and it must not add or
subtract rolling gauges. VictoriaMetrics does keep the recorded history, so
as-of and range queries over the gauges above (quota filling, resets, decision
changes) are correct.

### The AA-3D contract

The 3D tier ranks the measured Artificial Analysis AA-3D evaluation
(<https://artificialanalysis.ai/evaluations/aa-3d>), read from a separate,
bounded snapshot file passed with `--aa-3d-cache`. The collector opens no
socket, starts no poller and holds no credential for it: the root acquires
the public source through the existing client and drops the file.

Each record is validated before use: a finite non-negative Elo, its
confidence interval, the source, the observation date, the task count, the
benchmark conditions, and, where the source publishes it, the AA-3D cost per
task. A malformed row is refused, never read as zero. A snapshot older than
30 days, or one with no usable row, is not measured.

The Elo is not a 0..100 index. The root's policy is a relative min-max over
the **complete** board of the same snapshot, before any exclusion:
`(elo - min board elo) / (max board elo - min board elo)`. The bounds and a
fingerprint of the board are published with every use; if every measured Elo
is equal the component is 1 (equal relative performance), and the cost breaks
the tie. This is relative performance, not a win probability, an AA
intelligence index or a zero-ability claim. Raw Elo and its 95% interval stay
visible; a row with no published interval keeps the raw Elo and no interval.
A feed-level `normalization` (min-max or linear) and an explicit `normalized`
value are also accepted for other sources.

The 3D value is cost-aware and carries the capability beside the
intelligence: `0.45 * intelligence + 0.25 * normalized Elo + 0.30 * 1 / (1 +
cost per task)`. The cost is the AA-3D cost per task when the feed publishes
it (`cost_source: aa3d`); when it does not, the owner explicitly approved
the normal Artificial Analysis cost per task of the same model as a proxy,
published as `cost_source: artificialanalysis_intelligence` with
`proxy: true` and the statement that it is not a measured 3D cost. The AA-3D
page shows a cost graph without enumerated values, so nothing is read from it
or extrapolated. A missing input leaves the combined value unknown. The tier
is still gated by proven image input and excludes Astra and Fable from
selection.

The reader accepts only the snapshot file (`--aa-3d-cache`); no HTTP client,
poller, or credential. The whole board is accepted or refused: ranks must be
finite, unique and the complete sequence, an interval must contain its Elo,
and a duplicated, missing or malformed row rejects the snapshot. The published
attribution and source are fixed public values, and the file's own ids, slugs,
sources, release dates and free-form normalization are never forwarded.

### Native option descriptors

The collector keeps the option descriptors the stock orchestrator publishes:
the id, a current value only when one is published, and the allowed choices,
including the shape `options=[{id, label, ...}]`. A descriptor without a
current value is a real option, not a discard; the run setting is simply not
reported.

The AA record is selected independently of the native runtime setting.
`aa_bind.resolve(..., mode="reference")` ignores the native options: among the
exact records of one model it takes the best measured `0.70 intelligence +
0.30 cost per task` value, with both inputs required and no Max preference or
guess. The chosen condition is published as the reference, every other
measured condition is kept in `alternatives`, and two records of the same
condition are an ambiguity that is refused. Changing only the native current
value therefore cannot change the reference or the score, which a test
asserts.

Runtime reasoning is independent of the AA benchmark condition. The model
ranking uses the measured AA intelligence and cost per task; the runtime
policy is owner-defined: **medium by default, high for escalations**. One
explicit exception is approved: the exact DeepSeek V4.1 Flash models
(`deepseek-v4.1-flash` and `deepseek-v4.1-flash:1017`, after the provider
namespace) run **High by default**. The id is compared exactly, with no
substring, family or suffix rule; no other DeepSeek, MiniMax or similarly
named model inherits it, and a Flash model whose option does not list High is
a fail-closed capability mismatch. The exception is published in
`aa.condition` (`execution_default`, `execution_exception`, `execution_basis`),
`alignment`/`alignment_meta` and `runtime_policy`, and it never changes the AA
reference. The
alignment is a runtime recommendation: `alignment` names the option id and
`medium`, `alignment_meta.escalation` names `high`, and `alignment_meta`
carries `recommended`, `applied` and the actual current value. The AA
condition (for example Max) stays visible and is never presented as the
condition we run.

A model is selectable with a verified identity, its admission, and a published
option that supports the default. A model that lists levels without
`medium` (DeepSeek V4.1 Flash 1017 advertises `low/high/max`) is an explicit
`capability_mismatch`: no level is substituted, the supported list and the
option are published, and it is not selected until the owner resolves a
supported default. A model with no reasoning-level option is not subject to
the policy.

The snapshot reconciles its inventory with its candidates in
`coverage.ranking` (`inventory`, `candidates`, `excluded`, `excluded_models`),
so a model that is offered but not a candidate is named instead of silently
dropped.

### 3D evidence

The 3D tier has no prior and no blended score. A model enters it only with
two pieces of evidence: the catalog proves it accepts image input, and a
verified workload admission exists for 3D work. Until that admission exists
the row says `state: pending` and holds no 3D rank. Artificial Analysis
publishes an AA-3D evaluation of interactive 3D scenes
(<https://artificialanalysis.ai/evaluations/aa-3d>); it is a different
question from CAD and printable-geometry suitability, so it is cited as
future evidence and is not a score here. The collector opens no new client
and fetches nothing for it.

### Free-route quota scope

A free or promotional route is not exempt from the paid allowance of its
account by its zero price, a model suffix, or an observation that it was
usable while the allowance was spent. Only a scope the provider reports
separates it: a window keyed to that model, or an account window whose scope
names other models. The row publishes `capacity.scope` with the account, the
applied window count, whether a model window was used, whether the free route
was observed operational (`observed_free_route`), and `exemption` (false
unless a reported scope separates it). A spent account window therefore
reaches the free route and shows zero, and the route is not a winner.

The account of a model is the provider that serves it. A model id prefix is
a name and never an account: a free pool model called `gpt-oss-120b` is not
charged to the Codex account, and a pool `gemini` is not charged to
Antigravity. An exhausted paid allowance therefore never removes a healthy
pool route or the OpenCode route from a tier.

### Canonical entitlement display

The top cards read one canonical series family, one record per verified
entitlement:

| Series | Value |
| --- | --- |
| `ghostship_ai_entitlement_info{provider,account,model,window,quota,source,entitlement}` | 1, emitted even when no numeric reading is usable |
| `ghostship_ai_entitlement_used_ratio{...}` | the chosen reading's used share |
| `ghostship_ai_entitlement_reset_timestamp_seconds{...}` | that same reading's reset |
| `ghostship_ai_entitlement_expected_used_ratio{...}` | that same reading's even-spend line |
| `ghostship_ai_entitlement_pace_delta_ratio{...}` | that same reading's expected minus used |
| `ghostship_ai_entitlement_observed_timestamp_seconds{...}` | that same reading's observation |

The chosen reading is the current usable one (fresh, not reset, used known)
with the least remaining, ties broken by the freshest observation and then
the source; every numeric value comes from that one reading, never from
independent extrema. `quota` is the canonical window and `source` is the
reading that won. An entitlement with no usable reading emits only the info
series with `source=""`; unknown is never zero or one. The raw per-reading
series stay for the evidence table, and `quota.entitlements[].readings[]`
keeps every raw reading beside `display`.

### Quota entitlements

Two sources can report the same allowance. The OpenCode Go status surface
names its windows `go_monthly`, `go_rolling` and `go_weekly`, while the Go
usage endpoint names the same three windows `monthly`, `rolling` and `weekly`;
both can appear in one scrape under the same account and model scope.

The producer publishes the verified alias instead of dropping one: each
reading keeps its own `source` and `quota` id, and all readings of one
entitlement share `entitlement` (`provider:account:model:window:canonical
quota`) with `relationship` = `same_entitlement_independent_readings` and
`alias` = true. The snapshot lists them under `quota.entitlements`
(`readings[]` with source, quota, used ratio, reset and observation), and the
metric `ghostship_ai_quota_entitlement{provider,account,model,window,quota,
source,entitlement,relationship}` is 1 for every reading. A window with no
verified pair stays its own entitlement. Nothing is merged and nothing is
dropped, so a UI can group by `entitlement` and still show both readings.

### Provider capacity

`quota.provider_capacity{provider}` is the lowest applicable account window,
with the binding window's id. A spent window publishes zero and blocks the
provider; an unknown window suppresses a positive reading, because an
unknown window is not room. A model-scoped subordinate window constrains that
model only and never the provider's overall capacity. The metrics are
`ghostship_ai_provider_capacity_remaining_ratio{provider,binding}` (known
values only) and `ghostship_ai_provider_capacity_windows{provider,evidence}`.

### Account windows

The card of a provider holds one row per capacity window of the account.
The collector publishes those rows as gauges, read straight from
`quota.accounts`, so the page never recomputes a window:

| Series | Value |
| --- | --- |
| `ghostship_ai_account_window_remaining_ratio{account,kind,quota_id,label,evidence}` | the share of the window that is left |
| `ghostship_ai_account_window_expected_remaining_ratio{account,kind,quota_id,label,evidence}` | the share an even spend would have left by now: `clamp(seconds_to_reset / duration_seconds, 0, 1)`, with three decimals |
| `ghostship_ai_account_window_reset_timestamp_seconds{account,kind,quota_id,label,evidence}` | when the window resets |
| `ghostship_ai_account_window_check_timestamp_seconds{account,kind,quota_id,label,evidence}` | when the window was checked: the moment the provider reported it, in seconds. It is the moment of the reading the row is drawn from, so the age of a card is the age of its reading. A reading without a check time publishes none |
| `ghostship_ai_account_window_rolling{account,kind,quota_id,label,evidence}` | 1 for a window that rolls: a window shorter than five minutes with no reset |
| `ghostship_ai_account_window_order{account,kind,quota_id,label,evidence}` | the place of the row in the card: 1 session, 2 daily, 3 weekly, 4 monthly, 5 quota, 8 inferred, 9 other |
| `ghostship_ai_account_window_learning{account}` | 1 for an account that publishes no window of its own yet |

The labels of a row are the account, the kind of the window, the quota id
the provider gave it, the label the row draws, and the evidence of the
reading. The label is the kind of the window in title case, and a window
that names a narrower period than its kind says which one after a dot
(`Weekly · Fable`). The label is published exactly as it reads.

One window is read more than once. The OpenCode Go status names its
windows `go_rolling`, `go_weekly` and `go_monthly` while the Go usage
endpoint names the same windows `rolling`, `weekly` and `monthly`, and two
readings of one window arrive under one account. The window is published
once, and the reading that is published is the one that carries the length
of the window, then the one that carries its reset, then the freshest one,
then the one with the least left, and finally the one that resets first. A
reading that knows nothing never wins. The check time of the row is the
check time of that reading, so the age of a card is the age of the reading
the card draws.

A window with no length has no even-spend line, and a reading that could
not be read publishes no share: the row keeps its place in the card and
says that it is unknown. A reading without a check time publishes no check
time either, and the other series of the row are unchanged. The mark of an
account whose limit was never seen is not a window at all: the account is
learning, and the card says so.

An inferred window that rolls carries the mark of the inference, and the
collector publishes it as `ghostship_ai_account_window_rolling`, so the
page can say 'rolling'. The mark is carried as the inference published it:
a window of an inference that carries no mark publishes no rolling series.

### The availability of an account

An account whose limit was never seen used to reach the Providers page as a
bare "learning window" chip: the page could not say whether the account
could serve a request at all. The collector now publishes, per account,
whether the account can serve right now, why it cannot when it cannot,
whether its limit is unpublished or still being learned, and when that was
observed. Everything is read from the routing snapshot, and nothing is
recomputed.

| Series | Value |
| --- | --- |
| `ghostship_ai_account_availability{account,state,basis,reason}` | 1 for every account: whether it can serve right now, with the reason it cannot when it cannot, and the basis of its limit |
| `ghostship_ai_account_availability_check_timestamp_seconds{account}` | when the availability of the account was observed: the newest observation of the routes that were counted |

The account is every key of `quota.accounts` and every provider of the
candidates, so an account the snapshot knows only by its routes is published
too, and every account holds exactly one series.

The routes of an account that count are its free or promotional routes when
it holds any, and all of its routes otherwise. A paid route never stands in
for a free one, and a free route never stands in for a paid one: the
OpenCode Go account is counted by its five free routes and not by the paid
routes of the same subscription, and the check time of the account is the
newest observation of those free routes alone.

The state is `available` when one of the routes that count is available, and
`unavailable` otherwise. The reason belongs to an account that cannot
serve, and it is the reason its routes carry most often; a route that says
nothing does not count against a route that says something. When no route
says anything, a route that is in cooldown names the moment it cools down
(`cooling down until 04:48 UTC`), and an account that holds no route at all
says `no route available`. The reason is published exactly as it reads, and
it is empty for an account that can serve: an available account has no
reason to give.

The basis says where the limit of the account comes from, and the three are
never mixed:

| Basis | What it means |
| --- | --- |
| `learning` | a route of the account never saw a limit failure, so the account is still learning its window |
| `unpublished` | the account publishes no window with a number, so its limit is unknown and is never read as a zero |
| `published` | the account publishes a window of its own |

### The card order of the Providers page

The Providers page draws one card per provider account, and the cards come
in the order the owner approved. A Grafana variable keeps only the order of
the query that fills it, so the page cannot sort the cards itself: the
collector publishes the place of every account, and the page reads it.

| Series | Value |
| --- | --- |
| `ghostship_ai_account_card_order{account,scope}` | the place the card of the account takes: 1 is the first card |

The scope is `t3` if any candidate for that account has `native.mapped`
equal to true in the live T3 Code instance catalog; otherwise it is `free`.
An account with windows but no candidates is `free`. Dashboard consumers
can select cards by this label, with no provider exceptions. Removing a
provider from T3 changes its scope on the next collection.

The place is counted from one and holds no gap: the first card is 1, the
last card is the number of accounts, and every account holds exactly one
series.

The approved list is `APPROVED_CARD_ORDER` in
[`collector/card_order.py`](./collector/card_order.py): Claude, Codex,
Ollama, OpenCode Go, Antigravity, Grok and OpenRouter, in that order. The
page and this document point at that one list, so a change of the order is
one change in one place.

The accounts that are not on the list follow it. The ones that publish at
least one window with a number come first, by name, and the accounts that
publish none come after them, by name. A window with a number publishes a
share that is left or a share that is used, and a spent window holds the
number zero: a zero is a number. An account that is still learning its
window publishes no number, and it follows the accounts that do.

An account of the approved list that the snapshot does not hold is skipped,
and the cards behind it move up. The places are the places of the cards
that exist, and they never leave a hole.

The account is every key of `quota.accounts` and every provider of the
candidates, the same set of accounts the availability of an account
covers.

### The static worker table

While the routing switch is off, the selection in force is the owner's static
table, `worker_routes.entries` of
`config/agents/runtime-policy.json`. Each entry names a `task_type` and a
`scope`, and lists the routes to try in order; a route is an `instance_id` and
a `model`. The collector reads the policy passed as `--runtime-policy` and
publishes one row per model, in the order the page shows: the bulk routes by
their place in the bulk entry, then the large route, then the deploy routes,
then a route only research uses.

The provider and model of a route are the collector's own split. The OpenCode
instance carries the account in its model id (`ollama-cloud/...` is the
`ollama` account, `opencode-go/...` is `opencode-go`), which is the split
`t3source.split_model` already makes; any other instance is the provider
itself (`codex` with `gpt-6.1-sol` is the `codex` route).

The role is the first matching rule: `implementation`/`narrow` is `Bulk N`,
where N is the route's place in that entry; `implementation`/`large` is
`Large`; `activation` is `Deploys`; a model the table only names for
`research` is `Research`. `used_for` names every entry that carries the
model, in the role order above, each with the route's place in its entry:
`Narrow implementation (1st), Research (2nd)`.

The row's capacity is read from the routing snapshot's candidate of the same
route, never measured again:

* `ghostship_ai_static_route_info{row,role,provider,model,display_name,used_for}`
  - 1 for every model of the table. `row` is the display order, from 1;
  `display_name` is the name the collector already publishes for the model,
  falling back to the model id.
* `ghostship_ai_static_route_remaining_ratio{row}` - the candidate's
  `capacity.remaining_ratio`. A route the snapshot does not carry publishes
  no series, never a zero.
* `ghostship_ai_static_route_paced_availability{row}` - the candidate's
  `capacity.pace_delta`, the same number the page calls the Paced
  Availability. A promotion with no pace publishes no series.
* `ghostship_ai_static_route_pace_state{row,state}` - the band of the row
  against its own line, in `state`: `ahead`, `on_pace`, `behind`,
  `far_behind`, `spent` or `unknown`. One series per row. The line is the
  share left minus the row's Paced Availability, and the band is the value
  policy's: a row with no share, or with no pace to compare it with, is
  `unknown`, and a row with nothing left is `spent`.
* `ghostship_ai_static_route_reset_timestamp_seconds{row}` - the
  `capacity.capacity_binding.reset_at` of the candidate, in epoch seconds.
* `ghostship_ai_static_route_policy_ok` - 1 when the policy was read, 0 when
  it is missing or unreadable. A missing or unreadable policy publishes no
  static row at all; the rest of the collection is still written.

A model is one row even when several entries name it, and a model that is not
in `worker_routes` has no row.

### The free providers

The page lists every free provider: the model the provider selected for the
free tier, and the free routes it holds apart from its paid allowance. The
OpenCode Go case needs both: the monthly allowance of the account is spent,
and the free route of the provider still works.

Everything here is a projection of the routing snapshot, and nothing is
recomputed.

A provider is a free provider when it holds a free route, or when every
window of its account was inferred. An account that only learned its window
is a free account, and it is listed even when no route of it is in the
inventory. A route is free when its billing class says so: `free` for a
dedicated free route, `promotion` for a paid provider's route that costs
nothing right now. The class alone decides, and the access kind of a route
never does, so a subscription route of a paid provider is never a free model.

The selection of a provider is the provider's first entry in
`tier_winners.free`, in the order of the tier. The basis of the selection is
the capacity of the winning route, read from the candidate of that route:

* `ghostship_ai_free_provider_selection_info{provider,model,display_name,basis}`
  - 1 for every free provider. `display_name` is the name the collector
  already publishes for the model, falling back to the model id. `basis` is
  `reported` for a reading the provider reported, `inferred` for an inference
  from the limit failures of the route, `published` for a statement the
  provider publishes, `learning` for a route that never saw a limit failure,
  and `none` for a provider with no free winner.
* `ghostship_ai_free_provider_selection_remaining_ratio{provider}` - the
  candidate's `capacity.remaining_ratio`. An unknown capacity publishes no
  series, never a zero.
* `ghostship_ai_free_provider_selection_paced_availability{provider}` - the
  candidate's `capacity.pace_delta`, the same number the page calls the Paced
  Availability.
* `ghostship_ai_free_provider_selection_pace_state{provider,state}` - the
  band of the selection against its own line, in `state`: `ahead`,
  `on_pace`, `behind`, `far_behind`, `spent` or `unknown`. One series per
  free provider. The line is the share left minus the selection's Paced
  Availability, and the band is the value policy's: a selection with no
  share, or with no pace to compare it with, is `unknown`, and one with
  nothing left is `spent`.
* `ghostship_ai_free_provider_selection_reset_timestamp_seconds{provider}` -
  the `capacity.capacity_binding.reset_at` of the candidate, in epoch
  seconds.
* `ghostship_ai_provider_free_models{provider,state}` - the free routes of
  the provider, counted. `state` is `available` or `unavailable`, and the
  count is the candidate's own `available`. A provider that holds no free
  route publishes no count.

A provider with no free winner keeps its row with an empty model and no
basis. A paid provider has no row at all.

### Source health

* `ghostship_ai_source_success{source,provider}` - 1 when the source read
  cleanly, 0 when it failed. A failed source is never silently dropped.
* `ghostship_ai_source_status{source,provider,status}` - 1 for the current
  status of the source. `status` is one of `ok`, `partial`,
  `missing_credentials`, `unsupported`, `error`, and `unreadable` for the
  two request records, which cannot be read at all. The `reason` label
  carries the fixed code of the failure, and the two records have their own
  codes: `database_missing`, `database_unreadable`, `database_corrupt`,
  `database_schema_missing`, `cache_unwritten`, `ledger_missing`,
  `ledger_unreadable`, `ledger_corrupt` and `ledger_schema_missing`.
* `ghostship_ai_source_last_success_timestamp_seconds{source,provider}` - when
  the source last produced a reading.
* `ghostship_ai_source_observed_timestamp_seconds{source,provider}` - when the
  reported reading was observed, which may be older than the collection.
* `ghostship_ai_source_duration_seconds{source,provider}` - how long the source
  took to read.
* `ghostship_ai_provider_coverage{provider,source}` - 1 for every provider the
  dashboard covers, with the source its readings come from. A provider
  without a reader still gets a row, so nothing disappears.
* `ghostship_ai_collection_timestamp_seconds` and
  `ghostship_ai_collection_duration_seconds` - when the collection ran and how
  long it took.
* `ghostship_ai_routing_enabled` - 1 when the owner's routing switch is on, 0
  when it is off. The gauge carries no label: it is one switch for the whole
  snapshot.

### Quota and account

* `ghostship_ai_quota_used_ratio{provider,account,model,window,source}` - the
  used share of a subscription or quota window, 0 to 1. `model` is `*` for a
  window that covers the whole account and a model id for a per-model quota.
  `window` is the provider's own window name (`session`, `weekly`, `monthly`,
  `quota`, `shared`, ...).
* `ghostship_ai_quota_reset_timestamp_seconds{provider,account,model,window,source}`
  - when that window resets.
* `ghostship_ai_quota_observed_timestamp_seconds{provider,account,model,window,source}`
  - when that quota reading was observed.
* `ghostship_ai_quota_state{provider,account,model,window,source,state}` - 1
  for the state the provider itself reports for a window.
* `ghostship_ai_account_amount{provider,account,kind,unit,window,source}` - a
  reported balance, usage, cap or request count. `kind` is `balance`, `usage`,
  `cap`, `requests` or `free_models_used`/`free_models_limit`/
  `free_models_remaining`; `unit` is `usd`, `requests` or `tokens`. Unknown
  caps and balances are omitted, never inferred, and a null is never read as
  unlimited.
* `ghostship_ai_account_flag{provider,account,flag,source}` - 1 for a
  reported account flag, currently `free_tier`.
* `ghostship_ai_account_observed_timestamp_seconds{provider,account,kind,unit,window,source}`
  - when an account reading was observed.

### Usage

* `ghostship_ai_usage_tokens{provider,model,kind,window,source,basis}` -
  tokens used. `kind` is `input`, `cache_read`, `cache_write`, `output` or
  `reasoning`; reasoning is a subset of output and is never added to the
  total. `window` is `24h`, `7d`, `30d` or the provider's own billing period.
* `ghostship_ai_usage_cost_usd{provider,model,window,source,basis}` - cost in
  US dollars. `basis` is `provider_reported` (the provider priced it),
  `api_equivalent` (the public catalog's rate was applied) or `ledger_estimate`
  (the free pool's own ledger).
* `ghostship_ai_usage_unpriced_records{provider,model,window,source}` - the
  records no price could be found for.

The time a usage reading was observed is the source's observation time,
`ghostship_ai_source_observed_timestamp_seconds{source="t3_usage"}` or
`ghostship_ai_source_observed_timestamp_seconds{source="free_pool"}`.

The T3 history and the free pool ledger can cover the same work. They are
separate sources with separate labels and the dashboard never adds them
together. Provider billing and provider credits are not the same thing as an
API-equivalent estimate, and a free-only policy is not evidence of a
provider-reported dollar charge.

### Free models and the public catalog

* `ghostship_ai_free_model{provider,model,tier,source}` - 1 for a model that
  can be used at no cost. `tier` is `promo` (a promotional free model),
  `free_tier` (a provider's permanent free tier) or `free_pool` (a model the
  free pool serves).
* `ghostship_ai_free_model_available{provider,model,tier,source}` - whether
  that free model can be selected right now.
* `ghostship_ai_free_model_price_usd_per_mtok{provider,model,kind,source}` -
  the catalog price of a free model, per million tokens. `kind` is `input`,
  `output`, `cache_read` or `cache_write`.
* `ghostship_ai_free_model_observed_timestamp_seconds{provider,model,tier,source}`
  - when the free model list was read.

### The free inference pool

* `ghostship_ai_pool_model_info{provider,model,family,developer_country,operator_country}`
  - 1 for a model the pool may use, with the geography the pool catalog
  records.
* `ghostship_ai_pool_model_available{provider,model}` and
  `ghostship_ai_pool_model_selected{provider,model}` - whether the model is
  available, and whether it is the selected or preferred one.
* `ghostship_ai_pool_model_unavailable_reason{provider,model,reason}` - 1 for
  a candidate the pool marks unavailable, with the pool's own reason. `reason`
  is `suspended`, `account_policy`, `hosting_restricted` or `cooldown`.
* `ghostship_ai_pool_probe{provider,model,state,category}` - 1 for the pool's
  own probe of a route, with the state of the answer and its category.
  `ghostship_ai_pool_probe_timestamp_seconds{provider,model}` is when the pool
  checked it.
* `ghostship_ai_pool_model_cooldown_until_seconds{provider,model}` - when the
  model's cooldown ends.
* `ghostship_ai_pool_model_admission{provider,model,workload}` - whether the
  model is admitted for a given workload.
* `ghostship_ai_pool_limit{provider,model,limit,scope}` - a local admission
  limit. `scope` is `account` (with the model label `*`) or `model`. These are
  local policy and learned caps, not independently verified provider
  allowances: a shared cap is reported once, and a remaining balance is never
  invented.
* `ghostship_ai_pool_provider_state{provider,state}` - 1 for the current
  state of a pool provider.
* `ghostship_ai_pool_health_events{provider,model,result}` - the recorded
  successes and failures. `result` is `successes` or `failures`.
* `ghostship_ai_pool_latency_seconds{provider,model}` - the observed latency.
* `ghostship_ai_pool_concurrency{provider,account,kind}` - the current and the
  allowed concurrency; `kind` is `current` or `limit`.
* `ghostship_ai_pool_recent_jobs{provider,worker,client,status}` - the count
  of the recent jobs with these labels. The listing is bounded recent
  history, not a complete queue census.
* `ghostship_ai_pool_quota_amount{provider,model,kind,unit}` - a quota amount
  seen in a provider response header; `kind` is `limit` or `remaining`.
* `ghostship_ai_pool_observed_limit{provider,model,limit,scope}` - a limit a
  provider response header carried. `scope` is `model` when the provider
  reported the limit for that model alone, as Groq does, and `account`
  otherwise. The limit is a reading of the provider, and it never stands in
  for the pool's own admission cap.
* `ghostship_ai_pool_quota_reset_seconds{provider,model,unit}` - when that
  observed quota resets.
* `ghostship_ai_pool_quota_observed_timestamp_seconds{provider,model}` - when
  that observed quota was seen.
* `ghostship_ai_pool_ledger_requests{provider,model,window}` - the requests
  the pool reserved over a window.
* `ghostship_ai_pool_catalog_updated_timestamp_seconds` - when the pool
  catalog was refreshed.

### The reported-header capacity of a Groq model

The pool records the rate-limit headers of a provider's answer as
observations. For Groq, an observation whose `data.scope` is
`model_in_organization` is the capacity of that one model, and the collector
publishes it as a measured window of the model rather than only as a
diagnostic:

* `rpd` is requests per day: kind `daily` and a window of 86400 seconds.
* `tpm` is tokens per minute: kind `minute` and a window of 60 seconds.
* the used share is `1 - remaining / limit`. A limit that is not a finite
  number above zero, a remaining count that is boolean, not finite, or
  outside `0..limit`, an unknown unit, a scope other than
  `model_in_organization`, a missing reset and a missing observation all
  give no measured capacity. Nothing is filled in for them.
* the reset is `observed_at` plus the reset duration the provider reported,
  parsed only when the whole text is a duration: `1m26.4s` is 86.4 seconds
  and `2.227s` is 2.227 seconds, while `2s garbage` is not a reset. The
  collection time is never used as the reset, because the reset is the
  moment Groq said the window refills, not the moment the collector read it.
* a reading whose reset is at or before the collection instant, or whose
  observation is older than the quota freshness bound (1800 seconds), is
  not current headroom and not a lockout. It is left out of the measured
  windows, and its diagnostic series still publish what was seen.

The window is filed by the model (`quotaId` `rpd` or `tpm`, basis
`provider_reported`, `applies_to` the model id) and it survives the routing
snapshot's account section with that model scope. No Groq window is filed
for the whole account, so a model at zero remaining is spent while its
siblings keep their own headroom, and the provider's account capacity stays
unknown rather than being bound to one model. The pool's own `account_limits`
and `model_limits` remain `ghostship_ai_pool_limit` series: they are local
admission policy and never become provider capacity.

### The observed failures of a route

The T3 Code state records what happened when it ran a child. A failure is
scoped, because a failure is not always about one model: an account failure
reaches every model of that account, a route failure every model of that
provider instance, and a model failure only that model.

A refusal that says the account has no money left is an exhausted account,
not a broken route. The markers are "usage limit", "rate limit", "quota
exceeded", "quota exhausted", "upgrade for higher limits", "add usage
credits", "payment required" and "usage balance exhausted", and the status
of a refused payment in the shape a provider writes it: `HTTP 402`, `status
code: 402` or `402 Payment Required`. A bare "402" is not a status: a count
of processed items, a line number and a model id carry the same three digits
without anything being wrong, and reading them as a spent account would hide
every route of that provider. Every one of them is read as an account whose
allowance is spent, so every route of that provider is unavailable with the
reason `account_usage_limit` until a later run of it succeeds. The text of the
error is only read to pick the code; the provider's own words never reach a
metric, a label or a log line.

A model the provider retired is gone, and that is not a broken route and not
a spent account. The markers are "has been deprecated", "has been retired",
"free launch period", "reached its end of life" and "is no longer
available". Such a failure is scoped to one route: the model itself, on the
account that serves it. The other models of the same provider are not
affected by it. The route is not available, with the reason
`model_retired`, and it holds no tier at all - not the bulk tier, not the
free tier - whatever window it has, including the published unlimited
promotion of the Go free routes.

A retirement outlives the window of a failure. A failure older than 24 hours
is a past event, and a model that was retired yesterday is still retired
today, so the collector keeps the retired routes in its own state file, with
the provider, the model and the moment the retirement was first seen. A
later successful run of the same route clears it: the provider serves the
model again, and the route is usable once more.

### The model ranking

The ranking is the collector's opinion layer. It turns the model inventory,
the public catalog, the subscription windows and the free model list into four
ordered tiers. It runs on every collection, never touches the network, keeps
no state beyond one small JSON file, and is deterministic: the same inputs
always produce the same ranks.

The four tiers, in the order the dashboard reads them:

* `frontier` - the owner's workhorses, and nothing else.
* `bulk` - every other model with a measured value.
* `free` - the dedicated free routes: the free inference pool's own
  integrations and the routes a provider lists at no cost. A promotional
  zero-price route of a paid account is not one of them; it competes in
  bulk.
* `3d` - the models worth using for 3D printing work. The 3D scores come from
  another component; the ranking never invents them.

How a model enters a tier:

* A model is in the inventory only if T3 Code offers it or the free pool
  serves it. A model that the free model list or the 3D scores mention but
  the inventory does not is reported as unavailable and is never ranked.
* Every tier needs a measured value: the intelligence index and the cost per
  task, both required. A model the feed does not measure has no value and
  holds no tier, whatever it is called and whatever its listing costs.
* `frontier` takes the models the owner's policy names, and only those. A
  promotional free model is never a frontier model either; it belongs to the
  free and bulk tiers.
* `bulk` holds every other model with a measured value. The free inference
  pool is not part of the bulk tier: the pool belongs to the free tier.
* `free` needs the model to be a dedicated free route. A pool route needs a
  current admission for a workload before it may hold the tier; a native
  free route is a provider-native thread and needs none.
* `3d` needs an eligible 3D score above zero, and the tier keeps the twenty
  best of them. A model that qualifies for this tier is reserved for CAD
  work: it ranks last in the tiers it is reserved away from, and it is
  withheld from that work while its provider has less than half of its
  capacity left.

How quality is scored: the quality of a model is 0 to 100 and starts from the
prior of its lineage, matched on the catalog family first and on the model id
second. A model released within thirty days gains 3 and one released within
ninety days gains 1, a model with no release date loses 5, a model older than
a year loses 15, a context window of 200k or 500k tokens gains 1 or 3,
reasoning and tool calls gain 1 each, and a preview, experimental or beta
model loses 6.

How capacity and expiry drive the order: the window that matters is the one
that frees up soonest while it still has capacity, because that is the
compute worth using right now. The remaining share of that window is the
model's capacity, and the seconds to its reset are the model's expiry. The
capacity and the pace are reported beside the rank, and they order the
providers; they are never folded into the score of a model.

The score of a model in a tier is its measured value: the intelligence
index and the cost per task, with the weights of the owner's policy
(`0.70` intelligence and `0.30` efficiency for ordinary work, `0.45`
intelligence, `0.25` AA-3D capability and `0.30` efficiency for 3D work).
Nothing else is in it: a name suffix, a catalog price, a capacity term and
a pace term are all guesses, and a guess that moves a rank is not a
measurement. Both measurements are required, and a missing one leaves the
value unknown: nothing is renormalized. The usage of the model itself is
reported but does not move a rank.

A model whose account has less than 5% left cannot be used at all and is not
ranked.

The models that qualify for the 3D tier - an explicit visual input and a
measured AA-3D score - are reserved for CAD work. They rank after every
other member of the tiers they are reserved away from, and they are not
used for that work at all while their provider has less than half of its
capacity left. The reserve changes the order and the eligibility, never the
value.

### The trust of a model and the outcome it is worth

The order of a tier is the trust of its routes first, and the value of a
route second. The trust of a model is read for the task type of the tier it
holds: `implementation` for the frontier, the bulk and the free tiers, and
`cad-execution` for the 3D tier. The trust comes from the owner's runtime
policy (`model_trust.entries`) and from the delegation ledger, and the worse
of the two wins. The levels are `trusted`, `backup`, `untrusted` and
`excluded`; a model that nothing speaks about is trusted, and an excluded
level holds no tier at all.

The order of a tier is then:

* the trust of the route: a trusted route leads, a backup route follows, and
  an untrusted route comes last with the reason it holds;
* a route more than twenty points behind the line of its binding window
  (`far_behind`) follows every route of its trust group that is not, whatever
  the value of those routes: it goes to the back of the pool. An untrusted
  route stays last, and a route that is merely behind keeps its place in the
  value order;
* a provider reserved for another workload (`provider_reservations`) joins
  the backup group outside that workload's tier and follows every unreserved
  route of it; its winner names the workload in `reserved_for`;
* the 3D reserve, for the tiers a reserved model is held away from;
* the bulk tier reads the published value, and a free route leads it while
  its quality is within `0.10` of the best available route of its own
  trust level, free or paid; the 3D tier is valued by its own 3D value under
  the trust of the model;
* the pace of the account window, and a route with no window has no pace: it
  waits behind every route that has one.

Session, hourly, minute and daily windows are unpaced. They retain their
remaining share, reset and observation time, and still block availability at
zero. They publish no expected-use or numeric pace series. Positive short
windows publish the blue `on_pace` colour state without a pace line; zero is
red `spent`. Only weekly/monthly periods, including inferred periods of those
lengths, supply pace. Their own usage is compared with their own line even
when a short window binds the route's capacity. Short quota windows also stay
outside the model selection's displayed limiting window.

The pace state of a route is the band its Paced Availability falls in, the
share left minus the expected share left of the most constraining window, in
points, rounded to six decimals so that only the noise of the subtraction is
removed (`100 * (0.50 - 0.55)` is `-5`). A window with nothing left is
`spent` whatever its line; more than five points ahead of the line is
`ahead`; between five points behind and five ahead is `on_pace`; between
twenty points behind and five behind is `behind`; more than twenty points
behind is `far_behind`; and a route with no window, or no line to compare it
with, is `unknown`. The collector publishes the state as `pace_state` in the
`capacity` of every candidate row, as `pace_state` of every winner, as
`ghostship_ai_account_window_pace_state{account,kind,quota_id,label,evidence,state}`
for every window of an account, as
`ghostship_ai_static_route_pace_state{row,state}` for every static row, and
as `ghostship_ai_free_provider_selection_pace_state{provider,state}` for
every free provider, so the Providers page colours amber and red by the
collector's band instead of drawing its own. The collector half is the one
that publishes the two new series; the page keeps its own identical band
until it is switched to them.

The published value of a route is the outcome-weighted value: the measured
intelligence placed inside the range of the tier it competes in
(`p0 = 0.5 + 0.4 * (I - I_min) / (I_max - I_min)`), shrunk toward the rounds
that were actually observed (`p = (k * p0 + s) / (k + n)`, with `k = 10`), and
combined with the measured efficiency (`value = 0.70 * p + 0.30 * E`). The
rounds n and s are the model's own outcomes: a round of the environment, or
one whose cause is the `brief` or the reviewer, counts in neither. The
trust scales it: an untrusted route keeps half of it. The Artificial
Analysis value is published beside the published value, so the two cannot
disagree about what the order was made of.

The collector reads the trust and the outcomes from four files, and it never
writes any of them: the model identities (`model-identities.json` beside the
runtime policy), the runtime policy, the delegation ledger
(`--delegation-ledger`) and its backfill (`--delegation-backfill`). A file
that is missing, unreadable or empty is an empty history, and every model is
trusted.

The display quality score is one number per model, so every page - the
orchestrators, the workers, the 3D tier and the free tier - reads the same
comparable value. Its prior is global: the model's intelligence inside the
range of every ranked candidate, across every tier
(`p0 = 0.5 + 0.4 * (I - I_min_all) / (I_max_all - I_min_all)`, and `0.5`
without an index), and its counts are every task type of the model identity,
summed. The score is `round(100 * (k * p0 + s) / (k + n))` with `k = 10`: an
integer from 0 to 100. The basis is published with it: `AA + outcomes` when
the index and the rounds are both there, `AA only` with the index alone,
`outcomes + default prior` with the rounds alone, and `default prior` with
neither. The display score never orders a tier: the per-tier outcome above
does, and the score is published beside it, on every candidate row and every
winner.

* `ghostship_ai_model_trust_info{provider,model,tier,task_type,level,source,reason}`
  - 1 for the trust of a model in a tier, with the level it holds, where the
  level came from, and the reason it holds it.
* `ghostship_ai_model_outcome{provider,model,tier,task_type,field}` - the
  outcome of a model in a tier, field by field: `p0` the prior, `k` the
  strength of the prior, `n` the observed rounds, `s` the accepted rounds,
  and `p` the quality they produced.
* `ghostship_ai_model_quality_score{provider,model,basis}` - the display
  quality score of a model, an integer 0 to 100, with the basis it was built
  from. It carries no tier: the score is one number per model, across every
  tier and every page.
* `ghostship_ai_model_quality_rounds{provider,model,field}` - the global
  rounds behind the display score: `n` the rounds and `s` the accepted ones,
  summed over every task type and not read per tier.

* `ghostship_ai_model_rank{tier,provider,model}` - the rank inside a tier, 1 is
  best. Every ranked model keeps it, including the models that cannot be
  used right now: an unavailable model holds the rank 0 of the empty tier
  and is never dropped from the metrics.
* `ghostship_ai_model_score{tier,provider,model}` - the ranking score inside
  a tier.
* `ghostship_ai_model_quality{provider,model}` - the quality score, 0 to 100.
* `ghostship_ai_model_available{provider,model,reason}` - whether the model
  can be used right now, with the reason it cannot: a spent allowance, an
  unknown headroom, a route that failed, a route that is not offered, or a
  model the provider retired (`model_retired`). The reason is a fixed label
  or a fixed code, never the provider's own text.
* `ghostship_ai_model_capacity_remaining{tier,provider,model}` - the remaining
  share of the model's account capacity, 0 to 1. A spent allowance is
  published as 0; an unknown capacity is not published at all, because an
  unknown capacity is never a zero.
* `ghostship_ai_model_capacity_expires_in_seconds{tier,provider,model}` - the
  seconds until that capacity expires; negative when the window is already
  past its reset.
* `ghostship_ai_model_capacity_basis{provider,model,basis,state,window,scope,unit,weights}`
  - 1 for every ranked route, with the basis of its capacity: `reported` for
  a reading the provider reported, `inferred` for a capacity inferred from
  the limit failures of the route, `published` for a route the provider
  publishes as unlimited, and `unknown` for a route with no window at all.
  The other labels carry the inference behind it: the state
  (`in_window`, `exhausted` or `no_failure`), the window it was measured
  over, the scope (`model`, `account` or `unknown`), the unit (`tokens` or
  `requests`) and the weights (`assumed` or `fitted`). They are empty for a
  route whose capacity was not inferred.
* `ghostship_ai_model_capacity_budget{provider,model,unit}` - the budget an
  inferred capacity was measured against, in the unit it was measured in.
  It is published only when the budget is known.
* `ghostship_ai_model_capacity_episodes{provider,model}` - the limit episodes
  an inferred capacity was measured from.
* `ghostship_ai_inference_unmatched_events{source}` - the recorded events
  whose route is not in the collector's inventory. They are counted and
  never guessed.
* `ghostship_ai_model_quota_unknown{provider,model,reason}` - 1 for a model
  whose headroom is unknown, with the reason it is unknown.
* `ghostship_ai_model_tier{provider,model,tier}` - 1 for every tier a model
  belongs to.
* `ghostship_ai_model_info{provider,model,name}` - 1 for every candidate model,
  with its human name: the label T3 Code's model catalog gives the model, else
  the Artificial Analysis record's name without its reasoning condition, else
  the raw model id. The name is never empty, so a row of the dashboard always
  says what the model is. The `name` label carries the name exactly, with its
  spaces and its punctuation, escaped the way the text exposition format
  requires; every other label of this collector keeps its sanitised form.
* `ghostship_ai_model_evaluated_timestamp_seconds{provider,model}` - when the
  model was last evaluated.
* `ghostship_ai_three_d_prior{provider,model}` - how good a model is judged
  to be at 3D printing work, 0 to 1. This is a prior, not a measurement.
* `ghostship_ai_three_d_usage_tokens{provider,model}` - the tokens actually
  spent on 3D printing work.
* `ghostship_ai_three_d_score{provider,model}` - the combined 3D score: the
  prior and the measured usage, weighted 75/25.
* `ghostship_ai_three_d_observed_timestamp_seconds{provider,model}` - when
  the 3D reading was taken.

## A missing or stale reading is never healthy quota

Every reading carries the time it was observed, and the dashboard shows that
age next to the value. A quota that was not read has no series at all, which
is different from a quota that was read and is zero. A reading that is older
than the collection is stale and is shown as stale, not as a healthy window.

Concretely:

* A source that fails reports `ghostship_ai_source_success` 0 and a
  `ghostship_ai_source_status` of `error`, `partial`,
  `missing_credentials` or `unsupported`. It does not report zero usage and
  it does not report a zero quota.
* A quota value is only read together with its
  `ghostship_ai_quota_observed_timestamp_seconds`, so the panel can show how
  old the number is.
* A window with no reset time is shown without a reset, never with a
  fabricated one.
* An unknown cap or balance is omitted, never read as unlimited.
* The pool's local admission caps are labelled as local policy, never as a
  provider's own allowance.

## An unknown headroom always says why

An unknown headroom is not a gap in the reading; it is a state the
dashboard has to be able to explain. Every candidate row of the routing
snapshot therefore carries an `unknown_reason` beside its `quota_state`, and
the reason is one of two:

| Reason | What it means |
| --- | --- |
| `the provider publishes no quota window for this account` | The account has no window at all: nothing reports a limit for it |
| `the provider's window was not read, is stale, or has already reset` | There is a window, but its reading cannot be used |

The rule is enforced with tooling: the snapshot of the enabled providers
(`tests/fixtures/ai-usage/enabled-providers.json`) is checked, and a row
whose headroom is unknown without a reason fails the check. The same reason
is published as `ghostship_ai_model_quota_unknown`, so the dashboard can
list the unknown headrooms with the reason beside them.

## Privacy

No email address, no account identifier, no file path, no key, no prompt, no
job id and no raw error message ever reaches a metric label, a metric value, a
log line or a test. Account labels are `default` or a non-secret alias, model
labels are provider model ids, and the free model list and the pool catalog
carry only what their providers publish.

## The routing snapshot

The collector writes a second file next to its state:
`/var/lib/ghostship-ai-usage/routing.json`. It is the canonical answer for
anything that has to choose a model, and it is written atomically, so a
reader never sees half of it. The producer writes it; a consumer only reads
it. The file holds no service, no database, and no listener.

The contract, version 1:

| Field | Meaning |
| --- | --- |
| `schema` | `ghostship.ai-usage.routing` |
| `schema_version` | `1` |
| `generated_at` | the UTC ISO-8601 moment the snapshot was written |
| `max_age_seconds` | how long a consumer may trust it (900) |
| `partial` | true when a source failed or reported nothing |
| `routing` | the owner's routing switch: `enabled` is true only when the owner turned it on, and `source` says where the switch came from (`nixos-option`). The block is always there, so a consumer never has to guess whether it read a snapshot without a switch |
| `coverage` | every source with its status, observation time, and age, plus whether a frontier prime is available right now and, when it is not, why a consumer has to wait for it |
| `policy` | the owner's direction: the prime frontier models, the GPT models that may run, the instance the background agents use, and the frontier review rule with its authority and its fail closed rule |
| `tiers` | the ordered members of `frontier`, `bulk`, `free`, and `3d` |
| `quota.accounts` | the windows of each account, once per account: the ones the provider reported, and the ones learned from the limit failures of its routes (`evidence: inferred`, with the learned window, budget, unit, scope and episodes). A learned window that ends inside the collector's own run interval of five minutes carries no reset: it rolls, and the instant the inference measured is already past when the reading is published |
| `quality_feed` | the Artificial Analysis feed: its status, the intelligence index version, the fetch time, the age, and the attribution. A missing feed is a coverage gap, never an empty quality |
| `workload_policy` | the workload classes, their complexity ceiling, and the free route rule |
| `recommendations` | the recommended model per workload class, with its native identity, its role, and the reason |
| `candidates` | one row per model a consumer may act on |
| `pending` | the models that wait for their evaluation window |
| `counts` | how many rows were written and how many were left out |

A candidate row carries the native identity, the tier, the rank, the score,
the reasons, the quota state, the components, and the eligibility:

| Field | Meaning |
| --- | --- |
| `native` | the provider instance, the model id inside it, and the options that instance offers, copied from the live instance catalog. A model without a proven identity has `mapped: false` and is not eligible |
| `role` | `prime` for the frontier reasoning models, `delegate` for the volume work |
| `frontier_required` | true when the model holds the frontier and a delegate may not stand in for it |
| `tiers`, `rank`, `score`, `reasons` | where the model sits and why |
| `quota_state` | `available`, `exhausted`, or `unknown` |
| `probe` | whether the route answered its last live probe: `state` is `works`, `fails` or `unprobed`; `class` names the failure (`success`, `quota`, `auth`, `model_not_found`, `catalog_mismatch`, `policy_parked`, `timeout` or `upstream_error`, and empty when unprobed); `checked_at` is the UTC moment of the newest reading; `source` is `pool_probe` or `t3_probe`; `max_age_seconds` is 172800. The newer of the free pool's own probe and the latest OpenCode request of the route is the reading. A reading older than `max_age_seconds` is kept with its moment and its source, and the state falls back to `unprobed`: a route nothing probed reads `unprobed` with no moment and no source |
| `quality` | the quality with its source: `prior` or `measured`. There is no numerical quality claim without a source |
| `capacity` | the remaining share, when it expires, and the pace against the line the window draws by now. `capacity_basis` says where the capacity comes from: `reported`, `inferred`, `published` or `unknown`. `inference` holds the inference behind an inferred capacity: the window it was measured over, the budget, the unit, the scope, the weights, the episode count and the state. It is empty for a route whose capacity was not inferred |
| `usage` | the token volume of the last seven days, labelled as a volume and not as a task success |
| `intelligence` | the Artificial Analysis record of the model: the indices, the cost per task, the median performance, and the token prices of the feed, with the version and the fetch time. A model the feed does not list is unknown, not bad |
| `frontier_surplus` | whether a frontier model may carry volume work: the entitlement it comes from (its kind, its length, its reset, its quota id), the surplus, the reserve the review keeps, and the pace. A weekly or monthly allowance that resets within a day is not the same thing as a session window that resets in a few hours, so the window is named |
| `three_d` | the 3D prior and the 3D usage, each with its source |
| `eligibility` | the policy flags, kept apart from the readings |
| `admission` | `settled`, or `pending` with the reason and the end of the evaluation window |
| `provenance` | where the reading came from and when it was observed |
| `access` | how the route is reached and how it is paid for: the access kind (`dedicated_free`, `provider_promo`, `provider_paid`, `unknown`), the billing class, the price, and whether the route runs as a provider-native thread or as an inference job |

The probe is one reading, not two: the free pool's own check of a route and
the latest OpenCode request of it are both candidates for the row, and the
newer one is published. The pool marks a route `quota_or_cooldown` when it
sent nothing at all, which is not a probe. An OpenCode success works, a
limit fails as `quota`, and a retirement fails as `model_not_found`. A probe
of another model never answers for the row, and a reading older than two
days no longer counts even though its moment stays visible.

A free-pool route the ranking parked repeats the pool's own reason:
`hosting_restricted`, `account_policy`, `suspended`, or a `cooldown` that
names the moment it ends. A candidate the pool published without a reason
keeps the text the snapshot built before it, so no parked row is ever
unavailable without a reason.

Three kinds of statement never mix: a `policy` is what the owner decided, a
`measured` value is what a provider reported, and a `prior` is what the
collector believes from the catalog and the model name. A missing,
malformed, or stale reading stays `unknown`; it never becomes headroom and
never becomes zero. An exhausted window excludes its model. A reset in the
past is a stale reading, not a refill.

The model that is behind the line a window draws by now is preferred, so the
usage spreads across the reset limits instead of piling onto one account.

The workload classes bound what a route may take. A free route is the lowest
intelligence tier: it carries bounded research, cheap and easy tasks, and bulk
metadata updates with checks, and nothing else. It never holds the frontier,
never carries private work, and never decides a complex engineering,
security, or integration question, whatever its measured quality says. The
ceiling does not depend on the quality score.

The Artificial Analysis feed is the external quality input: the intelligence,
coding, agentic, and engineering indices, the cost per task, and the median
performance. It is pulled from the public pages with ordinary GETs once a
day by the `ghostship-ai-usage-feed` timer and cached; the collector only
reads the cache, so the read belongs to one place. There is no key, no
account and no paid plan. A page that is blocked is recorded as blocked and
the last good snapshot is kept. The cost per task and the token price are
different things and are never used for each other.

The role and the tier are explicit, and the rule fails closed: an
implementation by a bulk model needs a review by the frontier authority
before it is integrated, a bulk review is never a final approval, and a
required frontier that is unavailable is waited for instead of being
quietly replaced by a delegate. The snapshot says so in `policy` and in
`coverage.frontier`.

## The routing switch

Routing is off until the owner turns it on. The switch is the NixOS option
`ghostship.aiUsage.routing.enabled`, it is a boolean, and it defaults to
false. The unit passes it to the collector as `--routing-enabled
true|false`, and the collector publishes it in three places:

| Where | What |
| --- | --- |
| `routing` in the routing snapshot | `{"enabled": false, "source": "nixos-option"}`. The block is always present, so a consumer never reads a missing switch as an open one |
| every `--projection` file | the same bytes as the canonical snapshot, so the switch cannot differ between the file and its projections |
| `ghostship_ai_routing_enabled` | a gauge without labels: `1` when the switch is on, `0` when it is off |

The collector never acts on the switch. It publishes the owner's decision
and leaves the decision itself to the consumer, and nothing else in the
repository sets the option: turning routing on is the owner's action alone.

## How a route is paid for

Every candidate row and every winner carries an `access` record, and the
record carries a `billing` class. The class says how the route is paid for,
and it is derived from the access class the collector already keeps: the two
never disagree, and the class is never guessed from a price.

| Billing class | What it means |
| --- | --- |
| `subscription` | the route is covered by a subscription the owner already pays for |
| `free` | the route costs nothing by construction: the dedicated free inference pool, or a route the provider lists at no cost |
| `promotion` | the route is a paid route of a paid account that costs nothing right now |
| `pay_per_token` | the route is paid per token, and no subscription pays for it |
| `unknown` | the billing of the route is not known |

A dedicated free route is free, a promotional route is a promotion, and a
route with no known access is unknown. A paid route is a subscription only
when its provider is one the owner pays a subscription for (Claude, Codex,
Antigravity, Cursor, Ollama, OpenCode Go), and a pay per token route only
when its provider bills that way (Grok, OpenRouter, Vercel, Requesty). A
paid route of a provider we do not know how the owner pays for is unknown:
it never becomes a subscription.

## The daily evaluation

The quota and the eligibility are read every five minutes. The quality of a
model, and whether it may take a piece of work, is a separate question, and
the daily procedure answers it. It is described in
[EVALUATION.md](./EVALUATION.md): it researches the current line of models,
reads the free Artificial Analysis feed into the cache the collector reads,
reads the measured admission results of the free inference pool through its
own read surface, and runs bounded representative work on held out tasks.

A new model is provisional. It is never promoted for being new, for a high
token count, or for a good name, and a lineage prior stays the labelled
fallback for every model without a measurement.

## How to verify

Run the collector by hand, from the repository on the host, and print the
result instead of writing the textfile:

    sudo python3 modules/self-hosted/ai-usage/collector/main.py --stdout \
      --state /var/lib/ghostship-ai-usage/state.json \
      --snapshot /var/lib/ghostship-ai-usage/routing.json

Run it as the service does, and read what it reported:

    sudo systemctl start ghostship-ai-usage.service
    journalctl -u ghostship-ai-usage.service -n 50

Look at the textfile node_exporter scrapes:

    head -40 /var/lib/ghostship-container-metrics/ai-usage.prom

Read the routing snapshot a consumer uses:

    jq '.tiers.frontier, .candidates[0]' /var/lib/ghostship-ai-usage/routing.json

Check the timer:

    systemctl list-timers ghostship-ai-usage.timer

Query the metrics in VictoriaMetrics (it listens on loopback only):

    curl -sG 'http://127.0.0.1:8428/api/v1/query' \
      --data-urlencode 'query=ghostship_ai_source_success'

    curl -sG 'http://127.0.0.1:8428/api/v1/query' \
      --data-urlencode 'query=ghostship_ai_quota_used_ratio'

    curl -sG 'http://127.0.0.1:8428/api/v1/query' \
      --data-urlencode 'query=ghostship_ai_model_rank'

    curl -sG 'http://127.0.0.1:8428/api/v1/query' \
      --data-urlencode 'query=ghostship_ai_source_status'

The Grafana dashboard is in the "Ghostship" folder, next to the host,
container and security dashboards.

### Managed picker preferences

`model_selection` is the shared `ghostship.model-selection/v1` contract for
orchestrator and worker recommendations, grouped by provider. Native catalog
membership and quota availability govern favorites; short windows can make a
model unavailable but never become its displayed limiting window. The first
available native worker is the new-thread default. Effort follows the role's
supported native setting, with standard billing only.

The collector calls the policy input's authenticated picker reconciler on its
normal cadence. Incremental settings patches preserve unrelated favorites and
preferences. A durable ownership journal makes retries converge; partial
snapshots cannot retire omitted favorites. Existing threads keep their model.

An optional runtime file, `--custom-resets` (default
`/var/lib/ghostship-ai-usage/custom-resets.json`), contains
`{"schema":1,"windows":[{"provider":"example","quota_id":"weekly","reset_at":"2030-01-01T17:00:00Z"}]}`.
An optional `model` scopes an override to a per-model window. Only the matching
window's effective reset changes, until that time passes. Usage and observation
time remain provider measurements. Published windows and selection limits say
`reset_source: custom` and `reset_label: custom reset`, retain
`provider_reset_at`, and use the effective reset for pace. Invalid or duplicate
overrides fail visibly. Keep owner-specific reset times in runtime state.

### Announced resets

`ghostship-ai-usage-announcements` checks the public Codex announcement profile
through the agent identity's Agent Desktop browser tools, at most once per
eight hours (including retries and manual service starts). It owns and closes
one browser lease. A sign-in wall or challenge records `blocked`; the check
does not bypass it or use mirrors. Transport failures record `unavailable`.

The separate runtime cache, `--announced-resets` (default
`/var/lib/ghostship-ai-usage/announced-resets.json`), records reset time, scope,
source post URL, confidence and observation time. The published routing snapshot
includes this cache as `announced_resets`, including blocked-check status. Page
prose is never stored. Repeated post URLs update one record; up to 100 records
are retained and a failed check preserves previous announcements.

Only an explicit global Codex reset with a dated PT time is applied. Dates may
be ISO dates or `today`/`tomorrow` relative to the post's publication date in
Pacific time. PT observes daylight saving; contradictory PST/PDT is rejected.
Vague timing, deadlines, banked resets, unclear scope and other authors remain
ineligible. Announcements change neither usage nor freshness and never grant
capacity after the announced time. Future announcements within seven days use
the existing custom-reset application path; owner overrides take precedence.
Published quota windows, selection limits and dashboard metric labels say
`reset_source: announced` and `reset_label: announced reset`, retain the provider
reset, and pace against the announced reset. The collector reads the cache on
its usual five-minute cadence; it never browses or restarts T3.

### Exact worker builds

`ghostship.aiUsage.workerBuilds` maps a provider to an exact native model ID.
The configured Ollama choice is `ollama-cloud/deepseek-v4.1-flash:1017`. An
undated alias keeps its own measured quality and outcomes, but cannot replace
that build. Missing or spent configured builds yield no worker for that provider;
other providers remain available. Orchestrator choices are independent.

The generated versioned preferences reach the collector through
`--model-selection-preferences` and are published as `model_selection.worker_builds`.
Candidate `selection_eligible` and `selection_reason` explain the choice separately
from quota availability and Quality.

The Providers page uses raw MetricsQL strings for repeated model regexes,
so punctuation in exact model identities survives Grafana interpolation.
Capacity repeat freshness timestamps each selector directly; a timestamp of a
composite expression introduces an implicit subquery and can hide live cards.
Source health is visible above the model panes. It labels missing/stale
collections and T3 usage/provider failures independently of model quota data.
Historical T3 usage scans use the bounded sixty-second transport budget;
failures preserve their fixed reason (including timeout), never server text.
