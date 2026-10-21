# AI usage collection contract

Collect read-only snapshots into the existing node_exporter textfile directory,
then VictoriaMetrics and the provisioned Grafana dashboard. No T3 source changes,
new listeners, inference requests, key rotation, or automatic account changes.
Credentials stay inside the container-side collector. Metrics never carry emails,
keys, account IDs, paths, prompts, job IDs, or raw error messages.

Python collector modules return `list[tuple[str, dict[str, str], float]]`.
`provider_metrics.collect(home: Path, now: float)` reads non-T3 provider APIs.
`pool_metrics.collect(home: Path, now: float, rates: dict | None = None)` reads the
existing `agent free-inference` read surface, paging every model. Both may accept
keyword-only dependency injection for tests. No persistent public API clients or
service registry backends are needed; these are bounded, specialized collectors.

Metric names and labels (all gauges, not monotonic counters):

- `ghostship_ai_source_success{source,provider}` and
  `ghostship_ai_source_last_success_timestamp_seconds{source,provider}`.
  Emit success=0 on a missing/failed source. Never invent zero usage.
- `ghostship_ai_source_status{source,provider,status}` is 1 for the current bounded
  status code (`ok`, `missing_credentials`, `unsupported`, `error`, `partial`).
- `ghostship_ai_quota_used_ratio{provider,account,model,window,source}` and
  `ghostship_ai_quota_reset_timestamp_seconds` with identical labels.
  Account is `default` or a non-secret T3 instance alias; model `*` means shared.
- `ghostship_ai_account_amount{provider,account,kind,unit,window,source}` for
  reported balance, usage, caps and request counts; unit is `usd`, `requests`,
  or `tokens`. Omit unknown caps/balances. Never infer unlimited from null.
- `ghostship_ai_usage_tokens{provider,model,kind,window,source,basis}`;
  kind=`input`, `cache_read`, `cache_write`, `output`, `reasoning`.
  Reasoning is a subset of output and is never added to total tokens.
- `ghostship_ai_usage_cost_usd{provider,model,window,source,basis}`;
  basis=`api_equivalent`, `provider_reported`, or `ledger_estimate`.
- `ghostship_ai_usage_unpriced_records{provider,model,window,source}`.
  Windows are `24h`, `7d`, `30d` or the provider's reported billing period.
  Native T3 history and free-pool ledger can overlap: dashboard totals must not
  sum them together. Provider billing/credits are separate from API estimates.
  Free-only policy is not evidence of a provider-reported dollar charge.
- `ghostship_ai_pool_model_info{provider,model,family,developer_country,operator_country}`=1,
  `ghostship_ai_pool_model_available{provider,model}`,
  `ghostship_ai_pool_model_selected{provider,model}`,
  `ghostship_ai_pool_model_cooldown_until_seconds{provider,model}`,
  `ghostship_ai_pool_model_admission{provider,model,workload}`.
- `ghostship_ai_pool_limit{provider,model,limit,scope}`: scope=`account` or `model`;
  account-wide model label is `*`. These are local policy/learned admission caps,
  not independently verified provider allowances. Do not duplicate shared caps
  across model rows or invent per-model remaining balances.
- `ghostship_ai_pool_provider_state{provider,state}`=1,
  `ghostship_ai_pool_health_events{provider,model,result}` (success/failure),
  `ghostship_ai_pool_latency_seconds{provider,model}`,
  `ghostship_ai_pool_concurrency{provider,account,kind}` (`current`, `limit`),
  `ghostship_ai_pool_recent_jobs{provider,worker,client,status}`.
  Broker job listings are bounded recent history, not a complete queue census.
- `ghostship_ai_catalog_updated_timestamp_seconds{source="free_pool"}`,
  `ghostship_ai_collection_timestamp_seconds` and `ghostship_ai_collection_duration_seconds`.

Every source must distinguish observation time from exporter scrape time. Tables
must expose age/status and not present missing or stale values as healthy quota.
Keep all current free-pool models, including blocked or unselected ones.
Optional rates passed to pool collection map model IDs to USD per million tokens:
`{"input": number, "output": number, "cache_read": number?, "cache_write": number?}`.
Unmatched prices stay unknown. Pool ledger reservations may be estimates: label
those token totals with basis=`ledger`, and any priced cost with `ledger_estimate`.

Provider names: `codex`, `claude`, `grok`, `antigravity`, `opencode-go`,
`openrouter`, `ollama`, plus the free pool's existing provider IDs. Root collector
owns T3 snapshots and native usage history. External provider collector owns
OpenCode Go OAuth, OpenRouter, Ollama, and Antigravity model-level quotas so Flash
is visible independently of T3's partial family summary.
