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
  writing, for a manual run.
* Directories: `/var/lib/ghostship-container-metrics` (0755) and
  `/var/lib/ghostship-ai-usage` (0700), both created by systemd-tmpfiles.
* The collector is Python standard library only. The unit is hardened like the
  rest of this repository: `ProtectSystem=strict`, `ProtectHome`, no
  capabilities, `ReadWritePaths` limited to the two directories above, and
  read-only access to `/srv/apps/t3code/home`, `/run/ghostship-integrations`
  and `/run/ghostship-secrets`.

## Sources and what each one reads

Every source is read-only and every source reports its own outcome. A source
that cannot be read reports a status; it never reports a healthy zero.

| Source | What it reads | Where from |
| --- | --- | --- |
| `t3` | Provider limits: the subscription windows T3 Code knows about (Codex, Claude, Grok, OpenCode Go, Antigravity), their used share, their reset time and the time the provider checked them | T3 Code's read-only RPC (`server.refreshProviders`, `server.getConfig`) |
| `t3_usage` | The usage summary: daily and hourly token and cost buckets over `24h`, `7d` and `30d`, plus the records T3 could not price | T3 Code's read-only RPC (`server.getUsageSummary`) |
| `grok` | The credit billing of the Grok CLI account: used share of the current period and the period end | `cli-chat-proxy.grok.com`, with the Grok CLI credential |
| `opencode-go` | The Go subscription windows: rolling (session), weekly and monthly used shares, their resets, and the status the provider reports | `opencode.ai/zen/go/v1/usage`, with the credential OpenCode itself holds |
| `antigravity` | Both quota views Google exposes: the shared family windows (5-hour, weekly, shared) and the per-model quotas that T3 merges away | Google's `cloudcode-pa` quota endpoints, with the stored account token |
| `openrouter` | Credits, key usage per window, the spend cap, the free-tier flag and the free-model request allowance | `openrouter.ai` credits and key endpoints |
| `ollama` | The request counts of the Ollama Cloud account per window | `ollama.com/api/usage` |
| `free_pool` | The free inference pool: the provider states, the paged model catalog with geography, availability, selection, cooldown and admissions, the local admission limits, the health history, the observed latency, the concurrency, the recent jobs, and the quota amounts seen in provider headers | The broker's read-only status surface over its Unix socket, plus the pool's own reservation ledger |
| `model_catalog` | The models that can be used at no cost right now and their per-million-token prices | OpenCode's cached copy of the public models.dev catalog |

The 3D reading is not a provider source: it is the measured use of our own 3D
printing projects. Only session history files inside a directory whose name
mentions `3dprint` are read, only for the last 30 days, and only a bounded
number of files.

## Metrics

Every metric is a gauge. Labels never carry an email, an account identifier, a
path, a key, a prompt, a job id or a raw error message; provider names, model
ids, window names and non-secret account aliases are all that reach a label.

### Source health

* `ghostship_ai_source_success{source,provider}` - 1 when the source read
  cleanly, 0 when it failed. A failed source is never silently dropped.
* `ghostship_ai_source_status{source,provider,status}` - 1 for the current
  status of the source. `status` is one of `ok`, `partial`,
  `missing_credentials`, `unsupported`, `error`.
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
* `ghostship_ai_pool_recent_jobs{provider,worker,client,status}` - 1 for a
  recent job. The listing is bounded recent history, not a complete queue
  census.
* `ghostship_ai_pool_quota_amount{provider,model,kind,unit}` - a quota amount
  seen in a provider response header; `kind` is `limit` or `remaining`.
* `ghostship_ai_pool_quota_reset_seconds{provider,model,unit}` - when that
  observed quota resets.
* `ghostship_ai_pool_quota_observed_timestamp_seconds{provider,model}` - when
  that observed quota was seen.
* `ghostship_ai_pool_ledger_requests{provider,model,window}` - the requests
  the pool reserved over a window.
* `ghostship_ai_pool_catalog_updated_timestamp_seconds` - when the pool
  catalog was refreshed.

### The model ranking

The ranking is the collector's opinion layer. It turns the model inventory,
the public catalog, the subscription windows and the free model list into four
ordered tiers. It runs on every collection, never touches the network, keeps
no state beyond one small JSON file, and is deterministic: the same inputs
always produce the same ranks.

The four tiers, in the order the dashboard reads them:

* `frontier` - the best-value models, admitted automatically when a new model
  earns its place by quality, freshness and size.
* `bulk` - every other good, recent model.
* `free` - every model that can be used at no cost right now, including the
  promotional free models of paid providers.
* `3d` - the models worth using for 3D printing work. The 3D scores come from
  another component; the ranking never invents them.

How a model enters a tier:

* A model is in the inventory only if T3 Code offers it or the free pool
  serves it. A model that the free model list or the 3D scores mention but
  the inventory does not is reported as unavailable and is never ranked.
* `frontier` needs a quality of at least 95, a lineage prior of at least 97, a
  release within 180 days, and no size marker (`lite`, `nano`, `mini`,
  `flash`): a smaller sibling is never a frontier model. A promotional free
  model is never a frontier model either; it belongs to the free and bulk
  tiers. Only the newest model of a lineage may hold the frontier, so a new
  release takes over from its predecessor on its own.
* `bulk` needs a quality of at least 60. The free inference pool is not part
  of the bulk tier: the pool belongs to the free tier.
* `free` needs the model to be in the free model list.
* `3d` needs an eligible 3D score above zero, and the tier keeps the twenty
  best of them.

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
capacity bonus is the remaining share weighted by an urgency that halves every
six hours towards the reset, so an account that frees up soon is worth more
than one that stays used up for days. The frontier score is quality times one
plus twice the capacity bonus, the free score quality times one plus half the
bonus, and the 3D score the 3D quality and usage mix on its own: the 3D tier
is about 3D work, not about quota timing.

The bulk tier heavily weights the economy models, the cheap and fast ones
(the model id carries a whole `flash`, `mini`, `nano`, `lite`, `air`,
`haiku`, `luna`, `small` or `turbo` marker, or the catalog price is at most
0.5 US dollars per million input tokens and 1.5 per million output tokens).
An economy model is multiplied by 2 and any other model by 0.85, so the bulk
work goes to the models that cost little and the paid frontier accounts keep
their capacity for frontier work. The usage of the model itself is reported
but does not move a rank.

A model whose account has less than 5% left cannot be used at all and is not
ranked.

The rule that keeps the free models usable: a model that is wanted for 3D
work keeps its bulk capacity for the free models. When a model is eligible
for 3D work with a score of at least 0.6, its bulk score is reduced to 60%,
so the free models keep the headroom. The frontier score is never reduced.

* `ghostship_ai_model_rank{tier,provider,model}` - the rank inside a tier, 1 is
  best.
* `ghostship_ai_model_score{tier,provider,model}` - the ranking score inside
  a tier.
* `ghostship_ai_model_quality{provider,model}` - the quality score, 0 to 100.
* `ghostship_ai_model_available{provider,model}` - whether the model can be
  used right now.
* `ghostship_ai_model_capacity_remaining{provider,model}` - the remaining
  share of the model's account capacity, 0 to 1.
* `ghostship_ai_model_capacity_expires_in_seconds{provider,model}` - the
  seconds until that capacity expires; negative when the window is already
  past its reset.
* `ghostship_ai_model_tier{provider,model,tier}` - 1 for every tier a model
  belongs to.
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
| `coverage` | every source with its status, observation time, and age, plus whether a frontier prime is available right now and, when it is not, why a consumer has to wait for it |
| `policy` | the owner's direction: the prime frontier models, the GPT models that may run, the instance the background agents use, and the frontier review rule with its authority and its fail closed rule |
| `tiers` | the ordered members of `frontier`, `bulk`, `free`, and `3d` |
| `quota.accounts` | the measured windows, once per account |
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
| `quality` | the quality with its source: `prior` or `measured`. There is no numerical quality claim without a source |
| `capacity` | the remaining share, when it expires, and the pace against the line the window draws by now |
| `usage` | the token volume of the last seven days, labelled as a volume and not as a task success |
| `intelligence` | the Artificial Analysis record of the model: the indices, the cost per task, the median performance, and the token prices of the feed, with the version and the fetch time. A model the feed does not list is unknown, not bad |
| `frontier_surplus` | whether a frontier model may carry volume work: the entitlement it comes from (its kind, its length, its reset, its quota id), the surplus, the reserve the review keeps, and the pace. A weekly or monthly allowance that resets within a day is not the same thing as a session window that resets in a few hours, so the window is named |
| `three_d` | the 3D prior and the 3D usage, each with its source |
| `eligibility` | the policy flags, kept apart from the readings |
| `admission` | `settled`, or `pending` with the reason and the end of the evaluation window |
| `provenance` | where the reading came from and when it was observed |

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
performance. The feed is read once a day by the daily procedure and cached;
the collector only reads the cache, so the free request budget belongs to one
place. The cost per task and the token price are different things and are
never used for each other. The endpoint is the free one; there is no paid
plan and no account.

The role and the tier are explicit, and the rule fails closed: an
implementation by a bulk model needs a review by the frontier authority
before it is integrated, a bulk review is never a final approval, and a
required frontier that is unavailable is waited for instead of being
quietly replaced by a delegate. The snapshot says so in `policy` and in
`coverage.frontier`.

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
