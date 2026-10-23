# Changelog

## [3.17.136] - 2026-10-23

- ai-usage: every static route and every free provider's selection publishes its pace state, so a reader of those series no longer draws its own band. `ghostship_ai_static_route_pace_state{row,state}` holds one series per row of the owner's static worker table, and `ghostship_ai_free_provider_selection_pace_state{provider,state}` holds one per free provider. The state is the band of `value_policy.pace_state`: the left is the remaining ratio of the route, the expected left is that share minus the route's Paced Availability, and the band is read from the two, so left `0.4129` with a Paced Availability of `-0.033` reads `on_pace`, and left `0.9712` with `0.3306` reads `ahead`. A row or selection with no Paced Availability is `unknown`, one with nothing left is `spent`, and a row the snapshot does not carry is `unknown` rather than drawing a band. The modules call the value policy and never re-implement the band. This is the collector half; the Providers page keeps its own identical band until a separate change switches it to these series.

## [3.17.135] - 2026-10-23

- t3: OpenRouter leaves T3 Code (owner request: "we should remove openrouter from t3"). The trimmed OpenCode catalog no longer carries the `openrouter` provider at all, so T3's model list and configuration stop offering it, and a pinned default or small model cannot keep an OpenRouter model in the list. A configured `enabled_providers` loses `openrouter`, `provider.openrouter` is removed, and a `model` or `small_model` naming it is repointed to `ollama-cloud/deepseek-v4.1-flash` and `ollama-cloud/minimax-m3.1-flash`. The config is rewritten only when something changes, atomically and mode 0600; a missing config or one that is not JSON is left untouched with one log line and a zero exit. The free-inference pool is unchanged: it reads the untrimmed models.dev cache and keeps its OpenRouter credential.

## [3.17.134] - 2026-10-23

- ai-usage: the collector publishes the place of every provider card. The Providers page draws one card per provider account in the order the owner approved, and a Grafana variable keeps only the order of the query that fills it, so the page could not sort the cards itself: the collector now publishes the place of every account, and the page reads it. The new series `ghostship_ai_account_card_order{account}` holds the place of every card, counted from one, with no gap between the places and one series per account. The order is the approved list of the owner, `APPROVED_CARD_ORDER` in `collector/card_order.py`: Claude, Codex, Ollama, OpenCode Go, Antigravity, Grok and OpenRouter, in that order. The accounts that are not on the list follow it: the ones that publish at least one window with a number come first, by name, and the accounts that publish none come after them, by name. A spent window holds the number zero, and a zero is a number, so an account whose window is spent keeps its place ahead of the accounts that are still learning theirs. An account of the approved list that the snapshot does not hold is skipped, and the cards behind it move up, so the places are the places of the cards that exist and they never leave a hole. The accounts are every key of `quota.accounts` and every provider of the candidates, the same set of accounts the availability of an account covers.

## [3.17.133] - 2026-10-23

- ai-usage: one display quality score per model, so the orchestrator panes, the workers, the 3D pane and the free pane all read the same comparable number. The prior is global (`p0 = 0.5 + 0.4 * (I - I_min_all) / (I_max_all - I_min_all)`, min and max over every ranked candidate with a known index, across every tier; `0.5` without an index) and the counts are the rounds of every task type of the model identity, summed. The score is `round(100 * (k * p0 + s) / (k + n))` with `k = 10`, an integer 0 to 100, and its basis is published with it: `AA + outcomes`, `AA only`, `outcomes + default prior` or `default prior`. Every candidate row and every winner gains `quality_score`, `quality_p0`, `quality_n`, `quality_s` and `quality_basis`. The new series are `ghostship_ai_model_quality_score{provider,model,basis}` and `ghostship_ai_model_quality_rounds{provider,model,field}`; neither carries a tier, because the score is one number per model. The tier order is unchanged: the per-tier outcome still orders a tier, and the display score is published beside it.

## [3.17.132] - 2026-10-23

- Merge freeze: main can require a `ghostship/freeze` commit status, so a freeze set with `agent freeze set` refuses every merge, including `gh pr merge`, `--admin`, the merge API and the web button, not only `agent pr land`. The new `Merge freeze` workflow marks each pull request head from the repository variable `GHOSTSHIP_FREEZE` through `scripts/freeze-status`: success when no freeze runs or it has expired, failure while it runs, and failure for a record it cannot read. It runs as `pull_request_target`, so a pull request cannot mark itself unfrozen. `docs/fleet-operations.md` names the commands, the one-time protection and the marked-tip force-push a history rewrite needs.

## [3.17.131] - 2026-10-23

- ai-usage: every candidate row of the routing snapshot says whether its route answered its last live probe. `jq '.candidates[0].probe' routing.json` read null: the row carried the availability of the quota window and nothing about the last check of the route. The row now carries a top-level `probe` with `state` (`works`, `fails` or `unprobed`), `class`, `checked_at`, `source` (`pool_probe` or `t3_probe`) and `max_age_seconds` of 172800. The reading is the newer of the free pool's own probe of the route and the latest OpenCode request of it. A pool probe that answered works; the category `rate_limited`, `quota_exhausted` or `free_daily_exhausted` fails as `quota`, `credentials_or_access` as `auth`, `model_unavailable` as `model_not_found`, `no_verified_free_route` as `catalog_mismatch`, `awaiting_approval` as `policy_parked`, `timeout` as `timeout` and anything else as `upstream_error`; the pool's `quota_or_cooldown` sent nothing and is unprobed. An OpenCode success works, a limit fails as `quota` and a retirement as `model_not_found`. A probe of another model never answers for a row. A reading with `now - checked_at > 172800` is unprobed with an empty class, and still publishes the moment and the source it had; a route with no reading publishes `unprobed`, an empty class, and no moment or source. The collector reads the pool's probe as `ghostship_ai_pool_probe` and `ghostship_ai_pool_probe_timestamp_seconds`. A free-pool route the pool parked now repeats the pool's own `unavailable_reason` from the paged catalog: `hosting_restricted` reads "the owner's hosting rule keeps this route to research work", `account_policy` "the account's data policy or workloads do not allow development work", `suspended` "the account is suspended", and `cooldown` the cooldown text with its moment. A candidate without the field keeps the text it had, and the ranking order, the tier winners and the trust are unchanged.

## [3.17.130] - 2026-10-23

- ai-usage: the Model selection panel colours the pace in the owner's bands and draws the capacity cards' icon. The pace read a ten-point band and a grey "on pace", so a route six points off the ideal read as if it were on it. The delta is the collector's Paced Availability in points, rounded to six places before the band is read, so the float artefact of a boundary (100 x (0.50 - 0.55) is -5.000000000000004) stays on its boundary: ahead over +5 (green "▲ N ahead"), on pace from -5 to +5 (blue "● on pace"), behind from -5 to -20 (amber "▼ N behind"), far behind under -20 (red "▼ N behind"), and spent at nothing left (red "✕ spent · resets in …"); the number is the rounded size of the delta, and a row with no pace series has no pace word. The muted grey is left to a row with no pace at all. The reset is one minute count carried into hours together, so 59.6 minutes reads `1h 0m` and 18 h 59.7 minutes reads `19h 0m`; live the panel printed `18h 60m`, and no output of the panel can print sixty minutes now. The provider icon is the capacity cards' icon at every width (22 × 22 px, radius 6, 13 px glyph, never shrunk), and on a phone the model name's line is the icon's height at the top of the cell, so the icon is centred on the name rather than on the name and the provider line under it; the measured row centre is 0 px off the name's at 1568 px and at 358 px, and the Left cell keeps 140 px beside the model cell at 358 px. The taller rows need four more grid rows: the panel is 34 rows, and its body of 1232 px holds the measurement of the five static rows, the Free divider and sixteen free rows in Playwright in Inter, 1196 px at 358 px and 946 px at 1568 px, so 286 px stay empty at 1568 px and the panels below move down with it. The info tooltip states every band and its colour.

## [3.17.129] - 2026-10-23

- ai-usage: a route more than twenty points behind the pace of its binding window goes to the back of the pool. The collector now publishes one pace state per route and per account window, and the Providers page reads it for amber (behind) and red (far_behind, spent) instead of drawing its own band. The state is the band of the Paced Availability of the most constraining window in points, the share left minus the expected share left, rounded to six decimals so that only the noise of the subtraction is removed (`100 * (0.50 - 0.55)` is `-5`): more than five points ahead is `ahead`, between five points behind and five ahead is `on_pace`, between twenty points behind and five behind is `behind`, more than twenty points behind is `far_behind`, a window with nothing left is `spent` whatever its line, and a route with no window or no line to compare it with is `unknown`. The order of every tier gains one element right after the trust group: a `far_behind` route follows every route of its trust group that is not, whatever the value of those routes. An untrusted route stays last, and a route that is merely behind keeps its place in the value order. The candidate row and the winner carry the state as `pace_state`, and every account window publishes `ghostship_ai_account_window_pace_state{account,kind,quota_id,label,evidence,state}`, with the labels of the remaining-ratio series plus the state.

## [3.17.128] - 2026-10-23

- ai-usage: a round the lead caused is not the model's outcome. A ledger round whose cause is `brief` or `chief` is counted by neither n nor s, exactly like a round of the environment, so the quality p reads only the outcomes the model caused (owner rule, 2026-10-23). A backfill row records no cause, and its summary is never read as one.

## [3.17.127] - 2026-10-23

- host activation: `scripts/activate-host` holds the deploy slot for the whole deploy. An activation without a holder exits 3 before `nix-env` or the switch and names `agent deploy slot acquire`; a check that names another holder exits 3 with the slot tool's output, and a missing tool or a check error exits 1 with nothing activated. The holder comes from `--holder NAME` or `GHOSTSHIP_DEPLOY_HOLDER`, and reaches the slot tool as one argument. The slot stays held after the switch, so the deploy's own checks run inside it. `--verify-only --holder NAME` verifies the generation once more and releases the slot, with `--generation N` read from the system profile link name (`system-413-link` -> 413), or without it when the link names no generation; a refused release exits 3 with the tool's output. `--verify-only` without a holder never calls the slot tool.

## [3.17.126] - 2026-10-23

- change control: a deploy slot the host enforces records who may deploy, so a release no longer depends on a lead relaying it between sessions. A lost release message cost twenty idle minutes last night, and two sessions then raced for the same host. `scripts/deploy-slot`, a root-run tool of the Python 3 standard library, keeps one record in `$GHOSTSHIP_DEPLOY_SLOT_DIR` (default `/var/lib/ghostship-deploy-slot`, 0700): `slot.json` names the holder, its purpose, when it acquired, when it was last seen and the system generation it started from, read from the link `$GHOSTSHIP_SYSTEM_PROFILE` names (`system-412-link` records 412); `ledger.jsonl` keeps one line per acquire, release and takeover; and `lock` holds one exclusive flock for every operation, so two sessions can no longer both believe they hold the slot. A write is a temporary file and a rename. `acquire` refuses a fresh slot held by another and can queue the caller behind it, a queue entry lives for 180 seconds and the one that queued first goes first, and a slot idle for `$GHOSTSHIP_DEPLOY_SLOT_STALE_MINUTES` minutes (default 60) is stale and is taken over only with `--force --reason`, which the ledger records with the previous holder. `release` records the generation it closed, `check` refreshes the clock of the holder, and `status` names the state, the holder and the live queue. Every command prints one JSON object and exits 0 when it acted, 3 when the slot refuses, 2 on a usage error and 1 when the record cannot be read or written. The tests pin each case on temporary directories and a pinned clock, including two real processes racing for a free slot, exactly one of which wins.

## [3.17.125] - 2026-10-23

- AI usage: the collector publishes the availability of every account, so a provider that publishes no limit of its own reaches the Providers page as "Available", or as unavailable with its reason, instead of a bare "learning window" chip. The new series `ghostship_ai_account_availability{account,state,basis,reason}` holds one series per account: whether the account can serve right now, the reason it cannot when it cannot, and the basis of its limit (`learning` for an account that never saw a limit failure, `unpublished` for an account that publishes no number, `published` for every other account). `ghostship_ai_account_availability_check_timestamp_seconds{account}` holds when the routes that were counted were observed. The routes of an account that count are its free or promotional routes when it holds any, and all of its routes otherwise, so a paid route never stands in for a free one: the OpenCode Go account is counted by its five free routes and not by the paid routes of the same subscription, and its check time is the newest observation of those free routes alone. The reason is the one the routes carry most often, and a route that says nothing does not count against a route that says something; when no route says anything, a route that is in cooldown names the moment it cools down, and an account that holds no route at all says "no route available". The reason is published exactly as it reads, and an available account carries no reason. Every value is read from the routing snapshot, and nothing is recomputed.

## [3.17.124] - 2026-10-23

- ai-usage: the Free group of Model selection lists only the providers that hold an eligible free model. A provider whose `ghostship_ai_free_provider_selection_info` reads basis `none` is not a row any more, and the "no eligible free model" sentence is gone with it: live on generation 412 the eight providers Cohere, Mistral, OpenCode Zen, Orcarouter, Poolside, Requesty, Vercel and Zai stopped taking a row, and they come back by themselves once `routing.json` gives them a free-tier winner. The filter is the panel's own; the collector keeps publishing those rows, which the capacity cards' "Free models" line and the other readers of the free selection still read. Rows that are learning their window and rows with a published, reported or inferred share stay as they were. The panel is 30 grid rows, measured in Playwright in Inter with the five static rows, the Free divider and sixteen free rows: 1049 px at 358 px and 820 px at 1568 px, so the body of 1084 px holds both without an inner scroll, 264 px stay empty at 1568 px, and the panels below move up by the 10 rows it shrank. The review fixture holds the live set of nineteen free providers, eleven with a model and eight without.

## [3.17.123] - 2026-10-23

- ai-usage: the tiers are ordered by the trust of a model and by the outcome it is worth. The Providers page put a bad model on top: Beam Free led the bulk tier because a route with no window counted as a pace of zero, and no trust spoke about any model. The trust of a model is now read for the task type of the tier it holds (`implementation` for the frontier, the bulk and the free tiers, `cad-execution` for the 3D tier) from the owner's runtime policy and from the delegation ledger, and the worse of the two wins: a trusted route leads a tier, a backup route follows it, and an untrusted route comes last with the reason it holds. An excluded level holds no tier at all. The value that decides the rest is the outcome-weighted value: the measured intelligence placed inside the range of the tier (`p0 = 0.5 + 0.4 * (I - I_min) / (I_max - I_min)`), shrunk toward the rounds that were observed (`p = (k * p0 + s) / (k + n)`, `k = 10`), combined with the measured efficiency, and halved for an untrusted route. A free route leads the bulk tier while its quality is within `0.10` of the best available route of its own trust level, free or paid. A route with no window has no pace and waits behind every route that has one. The Artificial Analysis value stays the value of a candidate row and is published beside the published value of every winner, which carries the trust level, the reason, and the outcome it was built from. The collector reads the trust and the outcomes from the model identities, the runtime policy, the delegation ledger and its backfill; all four are read only, and a file that is missing is an empty history. The 3D tier keeps its own value (intelligence, the AA-3D Elo and the cost) under the trust of the model. The model identities default to the `model-identities.json` beside the runtime policy. A route of a provider the runtime policy reserves for another workload (`provider_reservations`: Claude and Codex for the review roles, Grok for 3D) is not a worker of the tiers outside that workload: it joins the backup group, follows every unreserved route of it, stays ahead of an untrusted route, and its winner names the workload in `reserved_for`. The new series are `ghostship_ai_model_trust_info` and `ghostship_ai_model_outcome`.

## [3.17.122] - 2026-10-23

- ai-usage: the Model selection panel fits both widths and reads only the newest scrape. Live on generation 412 the table clipped about 100 px at 1600 px, and a row on a phone could run through the Left cell. Measured in Playwright with the panel's helpers and styles in Inter, the five static rows, the Free divider and twenty-four free rows are 1440 px at 358 px and 1096 px at 1568 px; the panel is 40 grid rows, so the body of 1454 px holds both without an inner scroll, and the panels below move down by the 16 rows it grew. Under 520 px the hidden Provider column's name moves into the Model cell, in muted text under the model and on its own when the model is empty; a model name is one line ending in an ellipsis, and its title holds the full id. Every series the panel reads, static and free selection and the routing gauge, counts only from the newest scrape: the newest timestamp of `ghostship_ai_static_route_policy_ok`, less 15 s. The old guard was 90 s wide while a scrape is 30 s, so after a policy edit the rows of the policy before it stayed on the table for about two minutes.

## [3.17.121] - 2026-10-23

- AI usage: a free provider and a static route carry the name of their model. The name of a model is published with the model id the exposition format allows, and the id a provider gave is not always one of them: a slash and an at sign are not. The free selection and the static table looked the name up by the raw id of the route, so six of the nineteen free rows of the Providers page read a raw id where the collector publishes a name, and the Groq, OpenRouter, NVIDIA and Cloudflare Workers AI models of the free tier read 'qwen/qwen3.8-27b', 'thinkingmachines/inkling-small:free' and '@cf/openai/gpt-oss-120b' instead of 'Qwen3.8 27B', 'Inkling Small (free)' and 'GPT-OSS 120B'. The name is looked up by the id of the route first, and by the published form of that id after it. The provider is part of the key, so the name of another provider's model is never used, a model that is published nowhere still falls back to its own id, and no other label of a row changes.

## [3.17.120] - 2026-10-23

- ai-usage: a free pool route the pool parked says why it is unusable. The routing snapshot rebuilt `availability.reason` from the quota windows alone, so a pool route the pool reports as unavailable read `available: false` with an empty reason whenever the quota of its account was available; the live pool providers held 23 such candidates. The ranking already knows that the pool parked the route, and the snapshot now reads that judgement: a route whose pool cooldown has not run out says "cooling down in the free pool until <the moment the cooldown ends>", and a route without a cooldown says "the free pool does not offer the route for development work". The pool publishes no reason of its own, so those two cases are the whole of it. The availability state, `available`, `quota_state` and the capacity are unchanged, and so is every other reason.

## [3.17.119] - 2026-10-23

- AI usage: the age of a capacity reading is published, so a card of the Providers page can be compared with the provider's own site. The check time of the record the row is drawn from is published in seconds as `ghostship_ai_account_window_check_timestamp_seconds`, with the labels of the row, and a reading without a check time publishes none: the other series of the row stay as they are. Two readings of one window are one row, and the check time of that row is the check time of the reading that won. An inferred window that rolls carries the mark of the inference, and the collector publishes it as `ghostship_ai_account_window_rolling`, so the page can say 'rolling'. The mark is carried as the inference published it, and a window of an inference that carries no mark publishes no rolling series.

## [3.17.118] - 2026-10-23

- ai-usage: the Providers page lists every free provider under the static rows, and every capacity card says how many free models its provider holds. The static selection ends in a Free divider and one row per free provider in the order of the cards: the model the provider selected for the free tier, with the share left and the collector's Paced Availability, "learning window" for an account that never saw a limit failure, and "no eligible free model" for a provider with no winner. The numbers are the collector's free selection series, so the page never builds a row out of the candidates or out of an account window. OpenCode Go reads both at once: its monthly allowance is spent, and its card says "Free models · available · 2 models" in green under it, while a provider whose free routes are all out says "none available" in grey, and a provider that holds no free route has no line at all. The review fixture holds the live set of sixteen free providers and the free routes of six. The Free divider is five cells rather than one spanned cell, because a spanned cell takes the room the hidden columns leave on a phone and squeezed the model name into 56 px. The selection panel is sized for the headroom of twenty free providers: 883 px at 390 px (24 rows) and 861 px at 1600 px. The capacity cards grow by two rows for the free line: 1798 px at 390 px (49 rows) and 538 px at 1600 px.

## [3.17.117] - 2026-10-23

- Providers page: the Model selection panel renders again. Live it read "An unexpected error happened": its `externalStyles` option was an empty string, and Business Text 6.3.0 maps that option as a list (`e.externalStyles.map is not a function`). It is a list now, and its query reads as one table like every other section. A test holds every Business Text panel to list-valued `externalStyles`, `editors` and `contentPartials` and table-format queries.

## [3.17.116] - 2026-10-23

- flake: the AI usage collector's policy input moves to ghostship-agent 5381c015. The runtime policy there declares `model_trust`, the owner's trust levels: Beam is untrusted for implementation, Gemini 3.8 Flash for implementation and CAD execution, and Claude Haiku 5.5 and GPT-6 Luna are backup. `model-identities.json` declares the routes of those models, and DeepSeek V4.1 Flash 1017 is its own model. The static worker table now routes narrow implementation to DeepSeek V4.1 Flash 1017 first. The T3 Code agent input is unchanged. The wiring test no longer names one revision: it requires an exact 40-hex pin and a lock that holds the same revision, so a pin moves without a test edit and a stale lock still fails.

## [3.17.115] - 2026-10-23

- ai-usage: a published window series carries a quota id of its own. The card of a provider keys its rows by the account, the kind and the quota id, so a provider that publishes one quota id for several model families drew one row of the card for all of them: the Antigravity account publishes 'quotaInfo' for the Gemini, the Claude and the GPT models, and the card showed one of the three. The scope of the window is named after the id when the id does not name it already, so the quota of the Gemini models is 'quotaInfo@gemini' and a window of two families is 'quotaInfo@claude+gpt'. A window whose id names its scope keeps it: '3p-5h' names the Claude and the GPT models of the third-party group, and 'seven_day_fable' names the Fable models of the Claude account. A window of the whole account keeps its id, an inferred window keeps the name of the window it was learned over, and the account records of the routing snapshot keep the quota id of the provider.

## [3.17.114] - 2026-10-23

- ai-usage: the collector can read the observed outcomes of the delegation rounds. A new module reads the rounds the ledger holds, per model and task type: the count of the rounds of work (n), the count of the accepted ones (s), the fabrications that were seen, and the trust of the model with the reason it holds. The model identities are read from the `models` map of `model-identities.json`, where every key is the id of a model and every entry holds its label and its routes. The identity of a route is one model on every provider: a route of an identity names the provider and the model, the normalized model is the id of an identity or the model of one of its routes, and the normalized model is the identity itself; a checkpoint tag such as `:1017` is kept, so a tagged model never pools with the untagged model of the same name. The ledger is opened read only, a backfill row replaces the verdict of the round it names unless the verdict of the ledger is a manual one, and the trust of a model is the worse of the level the owner's runtime policy gives it and the level the ledger gives it: a model is not trusted again until three accepted rounds follow its last fabrication. Nothing calls the module yet.

## [3.17.113] - 2026-10-23

- ai-usage: the capacity cards are sized for the live set and read the age of a reading. The panel took a fixed height from an eight-card fixture, so a phone clipped about 576 px behind an inner scroll while a desktop left about 800 px empty. The review fixture now holds twelve cards with twenty-two windows and seventeen learning accounts, the live set with the headroom of the next collection, labelled with the scope of a window ("Session · Claude & GPT", "Weekly · Claude & GPT", "Quota · Gemini", "Weekly · Fable"). Under 520 px a row of a card is the label, the bar and the share on one line and the pace with the reset under it, with the reset clock dropped and nothing wrapped, and the accounts that are learning are one wrapped line instead of a grid of chips. The share left keeps one decimal, a reset that is due reads "resets now", a window the collector marks as rolling reads "rolling 1m" with no reset, no tick and no pace, the header of a card dates its oldest reading ("read 2m ago"), the repeated inner heading is gone, and the account "opencode" is read as OpenCode Zen. The panel takes the taller of the two measured readings in whole 37 px rows: 1713 px at 390 px (47 rows) and 577 px at 1600 px.

## [3.17.112] - 2026-10-23

- AI usage: a route the T3 instance does not offer says why it is unusable. The routing snapshot rebuilt `availability.reason` from the quota windows alone, so an unavailable route whose headroom was known read `available: false` with an empty reason; the live Go free routes `cat-jam-free` and `step-5-preview-free` were the example. The snapshot now reads the ranking's own judgement: the reason reads "not offered by the T3 instance", and a catalog entry marked deprecated appends "(deprecated in the catalog)". The availability state, `available`, `quota_state` and the capacity are unchanged, and so is every other reason.

## [3.17.111] - 2026-10-23

- AI usage: an inferred route that was refused reads "spent" only for the learned window that holds its last refusal, and it becomes available again once that window rolls over, with all of its allowance and a reset one window later. A refusal in the new window spends it again; a route with no learned window keeps its spent state with no reset. The quota id of an inferred window now names the learned window (`inferred:1h`, `inferred:5h`) rather than the state, so a spent route with a known window no longer reads `inferred:exhausted`; a refusal with no learned window keeps that id.

## [3.17.110] - 2026-10-23

- ai-usage: a learned window that ends inside the collector's own run interval is published as a rolling window. The collector reads the request record every five minutes, so the instant the inference measured was already past by the time the reading was published, and the Providers page showed "resets in 0m" for a window of a minute. A window shorter than five minutes keeps its length and carries no fixed reset now, and the inference behind it says that it rolls. A window of an hour and longer keeps the reset it was measured with, an exhausted short window has no reset either, and a route that was never refused is unchanged.

## [3.17.109] - 2026-10-23

- The Providers page shows the owner's static model selection under the capacity cards: one row per route of the runtime policy in the collector's row order, with the role, the model and its blue bulk tag, the provider with the icon of its capacity card, the work the route is used for, and the share that is left with the Paced Availability beside it. A spent route reads zero, spent, and how long until it resets; a route the routing snapshot does not carry says no reading and never zero; a route with no pace series keeps its share alone. The chip reads the routing gauge and says that the static table is shown for reference while the routing is on. The old Providers table goes, since the cards above it replace it.

## [3.17.108] - 2026-10-23

- ai-usage: a capacity window keeps the scope the ranking gives it. The account records of the routing snapshot dropped the scope of a window, so the session and the weekly window of the Antigravity third-party group read as the capacity of the whole account, the per-model quota readings of that account merged into one row of many models, and a spent Fable week of Claude blocked every Claude route. A measured window is filed under the scope the ranking gives it, a reading the provider reports for one model is filed under the family of that model, and a model id that names no family is not a window of the account at all. The label of the row names the scope: 'Session · Claude & GPT', 'Weekly · Claude & GPT', 'Quota · Gemini', 'Quota · Claude', 'Quota · GPT'. The provider capacity of an account counts the windows that cover the whole account only, and the ranking, the candidate rows and the windows they carry are unchanged.

## [3.17.107] - 2026-10-23

- AI usage: a Go free route keeps its free capacity when the live instance does not offer it. The unlimited window of the free routes was built from the instance inventory alone, so a free route the catalog lists but the instance did not offer that moment was left to the paid monthly allowance of the subscription and reported exhausted in `routing.json`. The window is now built from the inventory and the catalog's free list together; the catalog still keeps a "-free"-named route it prices on the paid allowance, and the OpenRouter free routes keep their daily free-models allowance. The status the Go usage endpoint reports for each window ("ok" or "rate-limited") also reaches the `quota.accounts` records of the snapshot, and a window without a status carries no status key.

## [3.17.106] - 2026-10-23

- AI usage: the Providers page lists every free provider, the model it selected for the free tier, and the free routes it holds apart from its paid allowance. The monthly allowance of OpenCode Go is spent, and its free route still works, so the two are published apart. Everything is a projection of the routing snapshot, and nothing is recomputed: the selection is the provider's first entry in `tier_winners.free`, and the free routes are the candidates whose billing class is `free` or `promotion`, split by their own availability. The class alone decides, so a subscription route of a paid provider is never a free model. A provider whose account only learned its window is a free provider even when it holds no route, a provider with no free winner keeps its row with an empty model and no basis, and a paid provider has no row at all. The basis of a selection is the capacity of the winning route: reported, inferred or published, `learning` for a route that never saw a limit failure, and none when nothing was measured. The new series are `ghostship_ai_free_provider_selection_info`, `ghostship_ai_free_provider_selection_remaining_ratio`, `ghostship_ai_free_provider_selection_paced_availability`, `ghostship_ai_free_provider_selection_reset_timestamp_seconds` and `ghostship_ai_provider_free_models`.

## [3.17.105] - 2026-10-23

- AI usage: the value policy carries the outcome maths the ranking is about to be valued by, and nothing calls it yet. The quality is an outcome-weighted *p*: a prior *p0* places the measured intelligence index inside its own tier (0.5 when the index is missing, 0.9 when the tier holds one model, clamped to [0.5, 0.9]), and *p* shrinks that prior toward the outcomes actually measured, at a prior strength of ten outcomes. The value is `0.70 * p + 0.30 * E` through the existing weights, so *p* takes the intelligence slot and a missing component leaves the value unknown. The trust levels order the tiers (trusted, backup, untrusted, excluded, with an absent or unknown level ranking as trusted) and an untrusted route keeps half of its value. A free route leads while it is within 0.10 of the best paid quality. The published policy states the formulas, the prior strength, the margin, the untrusted factor and the trust order, and the measured `value_score` and the existing policy sections are unchanged.

## [3.17.104] - 2026-10-23

- AI usage: an inferred window on the Providers page names only the window it was learned over. The suffix of an inferred quota id is a window when it is a length of time, so the row of a five hour window reads 'Inferred · 5h'. A suffix that names a state of the inference is not a period, so the row of an exhausted account reads 'Inferred', and no longer 'Inferred · Exhausted'. The label of every other window is unchanged.

## [3.17.103] - 2026-10-23

- The Providers page opens with the capacity cards: one card per provider, with a small icon and every capacity window the account has, and a chip for every provider that publishes no window of its own yet. The numbers of a card are the collector's account window gauges, read in one query, so the page never recomputes a window: the share that is left, the even-spend line, the reset, and the place the row takes in the card. The pace of a row reads the difference between the share that is left and the share the window expects to be left, a window that is spent says so, and a window the provider did not report carries the tag that it was inferred. The card order, the names, the icons and the notes are the presentation the owner approved.

## [3.17.102] - 2026-10-23

- ai-usage: a Requesty request counts toward its learned limit. OpenCode records the request as "vendor/model", while the collector's route is the model alone, so every such event was unmatched and dropped, and the limit failures of the route never reached the inference. The matching now falls back to the model alone when the whole id is unknown, exactly and folded, within the same provider: the prefix is never taken from another provider, never added, and only one segment of it is ever stripped.

## [3.17.101] - 2026-10-22

- AI usage collector: the owner's static model selection is published for the Providers page. While routing is off, the selection in force is `worker_routes.entries` of the runtime policy, and the collector now reads it through `--runtime-policy` and publishes one row per model: the role the table gives it (Bulk 1, Bulk 2, Large, Deploys, Research), every entry that names it with the route's place in that entry, and the share left, the Paced Availability and the reset the routing snapshot already measured for that route. A model listed twice is one row and a model outside the table has none; a route the snapshot does not carry keeps its row with no capacity; a missing or unreadable policy publishes no rows and `ghostship_ai_static_route_policy_ok 0` while everything else is still written. The policy has its own flake input, `ghostship-agent-policy`, so the T3 Code input and its lock entry are unchanged.

## [3.17.100] - 2026-10-22

- AI usage: a provider whose routes hit limit failures now shows its learned window and budget, instead of "no limit seen", in the ranking and in `routing.json` `quota.accounts`. A route of the provider that was never refused filed its own no-failure window under the provider key and hid the refused route's learned window; the quiet route no longer stands in for a refused one of its provider.
- AI usage: the inferred windows reach `quota.accounts` at all. The account section was filled from the provider-reported windows only, so a learned window never arrived, and a refused route lost its record as soon as it had no ranked row. Each inferred record carries `kind: inferred`, `evidence: inferred`, its basis, and the window, budget, unit, scope, episode count and state it was measured from; a model-scoped limit keeps its model in `applies_to`, and an inferred window with a known share now counts as the provider's remaining capacity instead of an unknown window.

## [3.17.99] - 2026-10-22

- ghostship-agent is pinned to 5fb39a15, the rewritten main with the Google account settings read at runtime (#101, #125, #130). The previous pin, 7f8d9fda, is the rewritten 2318134e, whose Google tooling held the addresses that the privacy rewrite replaced.
- The MCP container reads its account settings (the owner's and the agent's Google accounts, and the health document folders) from `/etc/ghostship/mcp-identity.env`, outside the repository.

## [3.17.98] - 2026-10-22

- The Providers page draws one card per provider with every capacity window. The collector publishes the windows of every account as gauges, read straight from the routing snapshot: the share that is left, the even-spend line, the reset, and the place the row takes in the card. The page never recomputes a window. One window is read more than once (the OpenCode Go status and the Go usage endpoint name the same windows), and the window is published once: the reading that carries the length of the window is the one that is published. An account that publishes no window of its own says that it is learning.

## [3.17.97] - 2026-10-22

- ai-usage: the free providers are read under the free pool's names. OpenCode reaches the free pool through an integration of its own (kilo-free, groq-free, cf-workers and the other "-free" ids), and the reader's map named none of them, so their requests were counted unmapped and never emitted, and the inferred limits never saw their usage. The map now carries the aliases of the pool's provider registry, and the event cache is at version two: a version one cache holds no free row, so it is discarded and the 35 days are read again.

## [3.17.96] - 2026-10-22

- chill-penguin: model routing is off (`ghostship.aiUsage.routing.enabled = false`), by the owner's decision. The static worker table in ghostship-agent's runtime policy governs until the owner approves the selection framework; routing.json, the `ghostship_ai_routing_enabled` gauge and the page chip read off.

## [3.17.95] - 2026-10-22

- chill-penguin: model routing is on (`ghostship.aiUsage.routing.enabled = true`). The owner approved turning it on once the Providers page and its data passed live validation; the evidence is in the AI-usage program's morning summary. The route picker reads the switch from routing.json, and the page's chip reads Routing ON.

## [3.17.94] - 2026-10-22

- Providers page: the 3D panel has room for its four live winners at 390 px (the fourth row was cut at the panel edge), and the Bulk panel loses the empty space under its winners. The panels below move with them; a test keeps the top-level panels from overlapping.

## [3.17.93] - 2026-10-22

- Providers page: the header renders again. Business Text runs panel helpers as `new Function("context", code)`, so a helper registers through `context.handlebars`; the header's helper used a bare `handlebars` and the panel showed "handlebars is not defined". The test now runs the helper exactly that way.
- Providers page: every reset time reads in UTC ("resets 13:00 UTC"), like the header; the date helper rendered the viewer's local time. Frontier keeps only its two role rows, now that capacity is read per model.

## [3.17.92] - 2026-10-22

- Providers page: the Bulk and Free tables list the ranked winners and the routes that are out, as the concept shows. Live, every tier member followed the winners, so Bulk ran to about thirty rows and scrolled inside its panel; the other members remain in the collapsed "Why this order" rows.
- Providers page: capacity is read per model, not per tier. The collector publishes a model's capacity once, labelled with its first tier, so the 3D table (asking for tier="3d") showed "Limits unknown" for every model; GPT-6.1-Sol's capacity is labelled frontier.
- Providers page: Frontier lists Chief then Backup, as the concept shows; the "3D reserve" tag is shown only in Bulk and Free, where the reserve applies; the 3D table lists its winners and the routes that are out.

## [3.17.91] - 2026-10-22

- Providers page: the header's "live data … UTC" time is now UTC. Grafana's date format renders in the viewer's own time zone, so the header showed a local time under a UTC label. A small panel helper formats the end time from its UTC fields only.

## [3.17.90] - 2026-10-22

- The Keep broker's agent account address is supplied by the deployment (`GHOSTSHIP_KEEP_AGENT_EMAIL` in `/etc/ghostship/owner-identity.env`), like the personal account, so the repository names no account address.

## [3.17.89] - 2026-10-22

- Providers page: a provider without a capacity reading sorts below every provider with one, as the page says ("exhausted and unknown last"), whichever series made it appear; before, a provider with only an entitlement reset sorted among the readings.
- The Providers page reads like the page the owner approved. The page is one line of header, then five sections: Bulk, Free, Frontier, 3D and Providers, each with a ranked table of one row per route. The order of a tier is the collector's own winner position, never a ranking made in the dashboard, and the routes that are not winners follow the winners, with the spent and refused ones sunk to the bottom, dimmed, with their reason. The fill of a capacity bar is the share left now and the line in it is the share the window expects to be left now, and the pace reads the difference: ahead of the pace, on it, or behind it. A route whose limits are unknown says so in italics; it never shows a zero and never a red bar. A route the provider publishes as unlimited for a limited time reads as a promotion, a route reserved for 3D work keeps its tag, and a route in the free quality band keeps its own. The four tier gauges, the provider cards and the tall header are gone; the detailed evidence stays, in collapsed rows below. The routing chip of the header reads the routing state of the collector: Routing ON when it publishes the routing as enabled, and Routing OFF · awaiting your approval when it publishes it as off or publishes nothing at all.
- The Grafana Business Text panel is vendored by hash. The panel (`marcusolsson-dynamictext-panel`, 6.3.0) is fetched by `fetchurl` with a fixed sha256, the same pin nixpkgs carries, and unpacked into the read-only plugin bundle next to the VictoriaLogs datasource, so the UI never downloads a plugin at runtime. The artifact is the signed release, so Grafana's signature check still passes.
- A route that cannot be used now comes after every route that can run. The order of a tier was the collector's winner position and its rank, and nothing else, so a route whose allowance is spent kept the place the collector gave it: the exhausted route of the free pool held the seventh place, above the route that is not a winner at all, and a reader met a spent route before a route that could have taken the job. The order of a table reads the flag of the route that cannot be used now: the place of the collector is the place of the route, and a route that is spent or refused sinks below every route that can run, whatever its position says. The order of the providers is the same: the spent accounts come after the accounts that can run, and the accounts that publish no window come last.
- The basis of a route is the basis the collector publishes. The column read the limit of the provider (`ghostship_ai_provider_limit`), so a route whose capacity the collector inferred read "unknown" next to the route that publishes no window at all. It reads the basis of the capacity of the route (`ghostship_ai_model_capacity_basis`) now: "published" for a route the provider publishes as unlimited for a limited time, "inferred" for a route whose capacity the collector inferred, "reported" for a route whose allowance the provider reported, and "unknown" only when the basis is unknown.
- The narrow screen of the page reads correctly. A column that goes away under 520 pixels takes its cells with it, so the columns of the free table line up again. A tag of a route — the 3D reserve, the quality band, the inferred capacity — keeps its whole text: the name of the model is cut with an ellipsis and the tag goes under it, never an empty grey box. The pace of a route that is on the pace carries its number too, "● 0", so every pace of the page has one.

## [3.17.88] - 2026-10-22

- The Artificial Analysis pull cannot outlive its unit: every read has a limit, and the run has a deadline. The feed was killed at its timeout again, after the AA-3D board had been written: the run started at 12:39:44, the board was written at 12:39:48, and then a read waited about 596 seconds before the unit was killed at 12:49:44, with 4.36 seconds of CPU and 9.1 MB downloaded. The read was not using the CPU: it was waiting. The per-read timeout was the socket timeout, and a socket timeout bounds one blocking operation and not the read, so a page that trickles or that stalls keeps the read alive for as long as the page keeps trickling. Every read now has a hard limit of 60 seconds for the whole read: the connect, the headers and the body. The read is done apart and the wait for it is bounded, so a read that is not finished in time is abandoned, reported as a failed read with the error `deadline`, and never retried. The body is read in chunks, so an abandoned read stops at the next chunk and lets go of its socket and its memory. The run has a deadline of 480 seconds from the start of the process, and it covers every read, the source pages included: a read that could not start with a whole read's time left is skipped and counted, and when the deadline passes the run stops reading, writes what it has under the rules it already had, prints its line and exits zero, because a run that ran out of time is not a failure. Every read is logged with the page key or the model slug, the time it took, the bytes it brought and how it went, and never with any page content. The final line says how long the run took and how many reads were skipped.

## [3.17.87] - 2026-10-22

- AI usage collector: every model of the Providers page carries a human name. The collector publishes one `ghostship_ai_model_info{provider,model,name}` series per candidate model, and the name is the first one that exists: the label T3 Code's model catalog gives the model, else the Artificial Analysis record's name without its reasoning condition ("GLM-5.3 Flash (High)" is the model "GLM-5.3 Flash"), else the raw model id. The name is never empty, so every row says what the model is. The Artificial Analysis name comes from the exact identity binding, the same record the quality score comes from: a record whose name only starts with the model id is a different model, and its name is never borrowed. The name label is published exactly, with its spaces and its punctuation, escaped the way the text exposition format requires; every other label keeps the sanitised form it has today.

## [3.17.86] - 2026-10-22

- AI usage collector: a route whose model the provider retired is read out of OpenCode's request record as well as T3 Code's run history. The reader flags a request that says the model was deprecated, retired, past its free launch period, at its end of life or no longer available (the flag only; the text is never stored). A route whose latest flagged request has no success after it joins the collector's retirement record: it is unavailable with the reason `model_retired`, holds no tier, and stays retired until the record shows a later success. On live data this marks the deprecated `opencode-go/minimax-m3.1-flash-free` and the retired OpenRouter `minimax/minimax-m3.1-flash:free`, which only the request record reports.
- The AI usage collector reads the capacity of the routes that report nothing out of their own limit failures. The providers with no usage API, no balance and no rate-limit headers, and every free route, showed "Limits unknown" on the Providers page. The owner rule reads their capacity from the limit failures instead, and the collector now does that: it reads the two request records it holds - OpenCode's own database of the requests the agents made, and the free pool's ledger of the requests it dispatched - puts their events on the routes of its inventory, and turns the limit failures of a route into the window of that route, the budget it reached, the share it has left and the pace it is at. The computation was already in the collector; this wires it to the records and publishes it.
- A reported reading always wins. A route that reports its usage keeps its reported window, and a route whose account already carries a window keeps that one: an inference is never published over a reading, and the basis of every route says which one it has - `reported`, `inferred`, `published` or `unknown`. The window of an inferred route is keyed by the route when the limit is the model's own and by the provider when the limit belongs to the account, and the window of a route that was never refused reads like the window of a route the provider publishes as unlimited: all of the allowance is left, there is no pace, and the headroom is never unknown.
- The two records are read at the same time and each of them caps itself at twenty seconds, so the pair never holds the collector. Both are read read-only through their own readers, and nothing else touches those files. A record that cannot be read is reported as unreadable with the reader's own reason code, contributes no events, and never fails the run: the routes it would have fed keep the basis they had. The status of both is published as `opencode_events` and `pool_events` beside the other sources.
- An event whose route is not in the collector's inventory is counted and published as unmatched, never guessed. The model ids are matched exactly, and apart from their case: a provider may spell a route id in another case, and the case is not part of the route. Two routes of a provider that differ only in their case are never guessed between.

## [3.17.85] - 2026-10-22

- The inferred capacity of a route no longer merges the routes that were never refused into the account of the provider. A route that was never refused has no limit of its own: it is measured on its own, with its whole allowance and no pace, and its use never ends the episode of another route. On live data the free routes of the Go provider were refused by nothing and still came out of the account of their paid models, which are refused and never recover.
- The refusals of a route that never recovered are now evidence for its scope. The scope of a route is read from the episodes of its account group, the open one included, so another model of the provider that works right after the refusal shows that the limit was the model's own. The paid models of the Go provider were refused, never recovered, and the free route of the same provider worked seconds later: they came out as one account with a minute long window and a budget of a few thousand tokens, and they are now the models that were refused, with no window read out of their failures.
- A refusal that opens the record of a group is the refusal of the group itself, so the episode of the group starts at that refusal. A record that began with a refusal produced no episode at all, because the scan looked for the first refusal after the first use: a route that was refused before it ever came back had no open episode, its scope came out unknown, and it was measured across the account, so the refusal of one model looked like the refusal of the whole provider.
- The span of an open episode runs from after its refusal to the reading, so the refusal itself is never evidence of the scope by itself. Two routes of a provider that were refused at the same instant have nothing in that span, and the scope of each is unknown.

## [3.17.84] - 2026-10-22

- SIEM UI: Grafana stops logging the missing provisioning directories at every start. Grafana reads `/etc/grafana/provisioning/plugins` and `/etc/grafana/provisioning/alerting` on every start and logs an error for each one it cannot find, and the container mounts the whole provisioning tree from one read-only store path, so Grafana could not create them itself. The tree held the datasources, the dashboards and the dashboard JSON, and nothing else, so every start of every container logged two errors about directories that were never there. The tree now holds both directories, empty: they are created in the same store path as the datasources and the dashboards, so they are mounted read-only with the rest of the tree, and no plugin and no alerting configuration is provisioned through them. Grafana's own settings are unchanged. A configuration test reads the store path the way the build runs it and holds the invariant: the tree the container mounts is the whole tree, it is mounted read-only, it has a plugins and an alerting directory, and both are empty.

## [3.17.83] - 2026-10-22

- The AI usage collector marks a retired model unavailable. A provider that retires a model does not serve it again, but the collector read the refusal of a retired model as a generic provider error, and it forgot every failure that was older than 24 hours. A model the provider had deprecated was therefore published as available, with an empty reason, and it ranked first in the bulk tier and in the free tier. A failure whose text names a retirement - "has been deprecated", "has been retired", "free launch period", "reached its end of life" or "is no longer available" - is now read as the reason `model_retired`. The retirement is scoped to that one route, on the account that serves it: the other models of the same provider are not affected by it. A retired route is not available and holds no tier at all, whatever window it has, including the published unlimited promotion of the Go free routes, and its candidate says why with the reason code `model_retired`. The other failures are read as before: a refused endpoint is still a provider error, a bad request is still a refusal of that model, and a spent allowance is still an exhausted account.
- A retirement outlives the window of a failure. A failure older than 24 hours is a past event, and a model that was retired yesterday is still retired today, so the collector keeps the retired routes in its own state file, with the provider, the model and the moment the retirement was first seen. The next run reads that memory, and a route that is not offered any more keeps its record. A later successful run of the same route clears the retirement: the provider serves the model again, the route becomes available and the state file forgets it.

## [3.17.82] - 2026-10-22

- The agent desktop update canary starts. The desktop API binds the address it is given, and the image's default is the address the production container owns on the desktop network. That address exists only in production's network namespace, so the canary could never bind it: its API failed on every start with "cannot assign requested address", and the canary never became ready, so the daily update unit failed before it could test any candidate. A canary now binds the API on loopback, an address every container namespace has, including the network-less profile canary, and the readiness probe asks the API for its health on exactly that address instead of waiting out the timeout. Production is untouched: it keeps its own address, its own environment, its own container definition and its own image; only the updater changed.

## [3.17.81] - 2026-10-22

- The owner identity values are supplied by the deployment, not by this repository. The account names and addresses the services log in as (the retired container registry account, the personal Google account the Keep broker verifies, the uptime kuma and ntfy administrator accounts and the account the private inputs were transferred from) are read from a root-owned file outside the repository, `/etc/ghostship/owner-identity.env`, and reach the units through their environment. A missing value fails with a clear message instead of a fallback, and the regression tests pin the same behaviour with synthetic names. The rendered configuration is unchanged once the deployment supplies the values.

## [3.17.80] - 2026-10-22

- CI parses every AppArmor profile the host loads. The check parsed six profiles of the thirty-five in the repository, so a policy the kernel would refuse could pass CI: PR #167 named a thirteenth transition in the agent desktop policy, `apparmor_parser` refused the whole policy, the reload failed, and the kernel kept the previous rules. The check now evaluates `nixosConfigurations.chill-penguin` and parses every policy the host loads, exactly as the host renders it, with the include tree the host resolves `<tunables/global>` and the abstractions against. All thirty-six loaded policies parse.
- The include tree is read the same way on every machine. The host pins its own platform, so the AppArmor package its parser searches is a store path of that platform: on the x86_64 CI it could not be built, `nix build` ended in nothing without an error, and the check failed on a directory that was never there. The check reads the copy of the machine it runs on instead, the same profile sources, realises it before reading it, and refuses a package version that is not the host's.
- The named transition budget is held. `apparmor_parser` 5.x keeps at most twelve distinct named exec transition targets in one profile block, and the limit lives in that block's exec table, not in the file. The check counts the transitions of every profile block, fails above twelve, and prints the count of every policy so an author sees the budget before it runs out. The agent desktop policy names twelve of them, which is the whole budget.
- Every profile file in the repository belongs to a policy or to an allowlist with a reason. A new file that no policy loads fails the check until it is declared, so a profile cannot be added without a policy to load it.

## [3.17.79] - 2026-10-22

- `ghostship-security-check` re-baselines one drift category or one flow finding. The single `--accept` cleared every drift baseline (listeners, SSH keys, persistence, SUID files) and accepted every current flow finding, so a reviewer who had verified one change (an intended SSH key rewrite, say) could not accept just that one: running `--accept` also silenced unreviewed listeners, SUID files and flows, including deliberately visible ones. `--accept-drift CATEGORY` (listeners, sshkeys, persistence, suid; repeatable) drops only the named baseline, so the checker records it again on that run and leaves every other baseline to keep alerting. `--accept-flow KEY` (repeatable) accepts only the named flow finding and refuses an unknown key, exiting non-zero and leaving the state file untouched. `--accept` cannot be combined with either scoped flag, and its help now spells out that it re-baselines every category and accepts every current flow finding.

## [3.17.78] - 2026-10-22

- SIEM log redaction: a secret name is redacted in every shape a log carries it. The `=` rule needed an unquoted value and the `:` rule covered six header names, so `{"password":"…"}`, `{"token":"…"}`, `{"cookie":"…"}`, `password: …`, `client_secret: …` and `password="…"` reached VictoriaLogs, which keeps them for 180 days and serves them to every Grafana user. The secret names (token, api_key, apikey, access and refresh token, client_secret, auth, password, passwd, pwd, secret, session, signature, sig and cookie) are now redacted as `key=value`, `key="value"`, `key: value`, `"key":"value"` and `"key": "value"`, and the scheme-less `{"authorization":"…"}` with them. The key itself is kept, so a reader still sees which field was secret. A name must stand alone, so `session_count: 3`, `password_policy` and `signal` keep their value and `sig` is not matched inside a longer word, while a prefixed name such as `db_password` is still a secret. The Vector test suite proves both directions now: every leaking shape is redacted, the shapes that were already sealed stay sealed, and three benign lines are unchanged.
- SIEM log redaction: a quoted secret value is redacted through its closing quote. The rules above ended the value at the first space, so `{"password":"two words"}` was stored as `{"password":"[REDACTED] words"}`, `password="two words"` as `password="[REDACTED] words"`, and the quoted authorization value kept everything after the scheme. The rest of the secret reached VictoriaLogs, which keeps it for 180 days and serves it to every Grafana user. An escaped quote ended the value early as well, so `{"token":"a\"b c"}` was stored as `{"token":"[REDACTED]"b c"}`, and a name behind a prefix leaked entirely in the quoted shape, because the separator follows the name directly: `{"db_password":"two words"}` matched no rule at all. A quoted value is now redacted through its closing quote, spaces and escaped quotes included, for a name on its own, for the same names behind a prefix and for the authorization value, whose scheme belongs to the quoted value. The unquoted forms keep their end set, and `session_count: 3` and `password_policy` keep their value.
- SIEM UI: Grafana creates no administrator. Grafana created the default `admin`/`admin` account on the first start, and the account outlives the login paths that are closed (the login form, basic auth and anonymous access are all off), so it waited on the internal network for a password path to be reopened. `GF_SECURITY_DISABLE_INITIAL_ADMIN_CREATION` is now true: the browser signs in through the auth proxy as a Viewer, and the dashboards and datasources are provisioned, so nothing needs an administrator. A new configuration test asserts the setting and the auth-proxy flow around it.


## [3.17.77] - 2026-10-22

- Two kernel module denials are now durable in the configuration. The running 6.19 kernel is affected by CVE-2026-31431 (`algif_aead`) and CVE-2026-53266 (`ebt_snat`), both in the CISA KEV feed, and the running kernel carries neither fix: no 6.19.x release carries the `ebt_snat` fix. The `algif_aead` deny existed only as a file placed by hand on the host, outside Nix, so it did not survive a rebuild and was never reviewed with the configuration that produced it. The host configuration now blacklists both modules and hands each of them to a false command in the generated `modprobe.d/nixos.conf`, which stops the automatic hardware probing and an explicit `modprobe` alike. The check `tests/kernel-module-deny.nix` evaluates the host configuration and holds the blacklist and the install rules in place.
- The denials are containment, not a fix. A privileged direct `insmod`, `modprobe --ignore-install` and an already loaded module stay outside them, and only a patched kernel removes the exposure. Nothing on the host uses ebtables, so the `ebt_snat` deny takes away no service the host depends on. CVE-2026-53362 (the IPv6 fragment path) is in the KEV feed and names no module: it has no module-level containment and needs a kernel upgrade.

## [3.17.76] - 2026-10-22

- The AI usage collector learns the capacity of the routes that report nothing. The providers with no usage API, no balance and no rate-limit headers, and every free route, showed "Limits unknown" on the Providers page. The owner rule reads their capacity from the limit failures instead, and this adds the computation of that rule: a route that runs until it is refused shows the window of its limit failures, the budget it reached, the share it has left, the share an even spend would have left, the paced availability and whether the limit was the model's own or the account's. The module takes the events of a record and returns the capacity per route. It reads no file, no database and no network, and it is not wired into the collector yet: the readers and the publication come later against this interface.
- A budget that an account shares between its models is fitted only when the episodes of the account involve at least two models with usage and there are more episodes than those models. An account that carries usage in a single model is never fitted: it has nothing to share between its models, its weights stay equal with the basis "assumed", and its budget is the median usage of its episodes in its own unit, exactly like the budget of a route that carries its own limit.

## [3.17.75] - 2026-10-22

- The AI usage collector publishes the free pool's recent jobs as a count. The pool published one `ghostship_ai_pool_recent_jobs` sample per recent job, so two jobs that shared a provider, a worker, a client and a status were the same metric series twice. The renderer dropped the repeat and kept the first value, so the published number was one where it was two, and the collector's own duplicate counter reported the repeat on every run. The series is now the count of the recent jobs that share its labels and it is published once per label set. The labels and their defaults are unchanged, a job without a provider is still skipped, and a status that repeats a job publishes no duplicate series at all.

## [3.17.74] - 2026-10-22

- The AI usage collector can read the free inference pool's job ledger. The pool records every request it dispatches in a durable ledger: one reservation row per dispatched request, and one attempt per attempted route on the job's receipt. A free route reports no usage of its own, so its capacity is inferred from its limit failures, and the ledger is where the use of the route is recorded. The new reader turns that ledger into the events the collector infers a route's window and budget from: the provider, the model, the instant, the outcome (`success`, `limit` or `other`), the tokens and the window a limit named. The attempt's category decides the outcome: a quota exhaustion is a limit and names no window, the daily exhaustion of the free allowance is a limit of the day, and every other category - a rate limit, an upstream error, an unavailable model, a context limit, a credential failure and an unexpected tool - is not a limit of the route. A failed attempt contributes no usage, because the estimate the pool writes before a dispatch is not consumption. A probe, the pool's own check of a route, has a reservation and no receipt, so it is an event of its own with the usage it consumed. The reader is not a source yet: the collector does not read it and no metric carries it.
- The read is read only and it is bounded. The ledger belongs to the running pool, so it is opened with the `mode=ro` URI and nothing in the reader writes to it. Every query asks only for the last 35 days, the whole read has a wall clock limit of 20 seconds that aborts the query when it is reached, the busy timeout is 2 seconds, and the connection is closed on every path. A ledger that cannot be read is reported as unreadable with a fixed reason code, never as a reading of zero usage.

## [3.17.73] - 2026-10-22

- The AI usage collector can read OpenCode's own request record. OpenCode writes every model request it makes into its SQLite database, with the provider, the model, the tokens, the instant and, when the request failed, the provider's own error. The new reader turns those records into the events the collector infers a route's window and budget from: the provider, the model, the instant, the outcome (`success`, `limit` or `other`), the tokens and the window the failure named. Only a budget failure is a limit: a session usage limit is a five hour window, a weekly usage limit is a seven day window, a daily limit is a one day window, and a concurrency refusal, a per-minute refusal, a transient upstream refusal, a request that was too large, an expired key, an aborted run and a timeout are read as `other`, because they spend no window. The reader is not a source yet: the collector does not read it and no metric carries it.
- The OpenCode reader reads incrementally, and it keeps its history in a cache of its own. The reader read the whole window on every run, and the live window is about three gigabytes: the read could not finish inside the twenty seconds it is allowed, so every run timed out. The reader now keeps a cache in the collector's state directory that holds the compact events, the cursor and the instant the history is complete from. A run reads only the rows the last run may not have seen, with two hours of overlap so a row OpenCode inserted at the start of a step and completed later is read again, and it replaces the events of that window with the ones it read.
- The OpenCode history is filled a slice at a time. With no cache a run reads the newest slice of three days; with a cache whose history is not complete a run reads one slice of at most three days, walking back from the start of the history, inside the same cap. The reading is partial until the history reaches the whole window, and it carries the instant the history is complete from. A slice that runs out of time leaves the cache as it was and is read again by the next run, and the part that was read still counts.
- The OpenCode read is read only and it is bounded. The database is opened with the `mode=ro` URI and nothing in the reader writes to it, so the running T3 workers keep their own database. The query asks only for the last 35 days and only for the fields the reader uses: SQLite extracts them from the record with its own JSON functions, so the whole record, about 27 KB a row, never travels into Python. The whole read has a wall clock limit of 20 seconds that aborts the query when it is reached, the busy timeout is 2 seconds, and the connection is closed on every path so no read transaction is left open to hold back the writer's checkpoints. A database that cannot be read is reported as unreadable with a fixed reason code, never as a reading of zero usage.
- The OpenCode cache is written atomically and is never trusted blindly. It is written beside itself and renamed over the old one, so a reader never sees half of it. A cache that does not parse, or that does not carry the shape the reader expects, is discarded and the backfill starts again, and a cache is never trusted for an event that is dated in the future.
- The text of a provider's error is read in memory, to pick the outcome, and never leaves the process: it is not stored, not returned, not logged, not in an event and not in the cache. A real limit message names the account it belongs to, and that name stays in the process.

## [3.17.72] - 2026-10-22

- The AI usage collector says which metric series it dropped as a repeat. The renderer dropped a repeated name with the same labels and logged only how many series it dropped, so a run that dropped one or two series said nothing about them, and the emitter that published a series twice could not be found. Every dropped series is now named in the run's log, with its labels in the order they appear in the text file, and the line says whether the repeat carried the value that was kept or a different one. A run names at most twenty dropped series and then says how many it did not name, so the log stays a log. The first value is still the one that is published, the file still holds every series once, and `ghostship_ai_collection_duplicate_series` still counts every repeat.

## [3.17.71] - 2026-10-22

- The kernel audit backlog holds 131072 records. A container restart burst overflowed the previous 32768 and the kernel dropped 70811 audit records, and a dropped record is a detection that never happened. The limit rises on both paths that reach the kernel: `security.audit.backlogLimit`, which NixOS writes into the generated audit rules and the kernel command line, and the `ghostship-audit-backlog` unit, which runs `auditctl -b` after those rules were loaded and therefore decides the value the kernel ends up with; the unit now carries that option instead of repeating the number. Nothing else moves: the failure mode stays printk, the rate limit stays unlimited, the rules and the log rotation are untouched, and no backlog wait time was configured, so none was added. A check evaluates the host configuration and holds every path to the new limit and the unchanged failure mode.

## [3.17.70] - 2026-10-22

- The AI usage collector publishes the owner's routing switch. A consumer of the routing snapshot could not learn whether routing was on: the snapshot carried no switch at all, and a missing field is not an answer. The new NixOS option `ghostship.aiUsage.routing.enabled` is off by default and nothing else in the repository sets it, the unit passes it to the collector as `--routing-enabled true|false`, and the collector publishes it in the routing snapshot, in every projection of that snapshot, and in the new gauge `ghostship_ai_routing_enabled` (1 or 0, no labels). The collector never acts on the switch itself: it publishes the owner's decision and leaves the decision to the consumer.
- Every route says how it is paid for. The snapshot said how a route is reached but never what it costs the owner, so a consumer could not tell a subscription from a pay-per-token route. Every candidate row and every winner of every tier now carries `access.billing`: `subscription`, `free`, `promotion`, `pay_per_token`, or `unknown`. The class is derived from the access class the collector already keeps, so the dedicated free routes and the promotional routes are not detected a second time, and a paid route of a provider we do not know how the owner pays for stays `unknown` instead of becoming a subscription.

## [3.17.69] - 2026-10-22

- The Artificial Analysis pull finishes inside its unit, and the AA-3D board is written before the model pages are read. The feed was killed at ten minutes on the host, after 5.6 seconds of CPU and 9.2 MB downloaded: the pull read up to ten model pages of about four megabytes with a sixty second timeout each, and it never reached the end of them, so `/var/lib/ghostship-ai-usage/aa-3d.json` was never written and every model read "no usable AA-3D snapshot". The board is now read first and written as soon as the page is parsed, so a slow model page, a timeout or a failure cannot lose it, and the 3D tier gets its data. The pull has a total budget of 480 seconds, measured from the moment the board has been written: a model page is started only while at least ninety seconds of the budget are left, so a page that is read at the last moment still has the time to finish. The pages that are not read are counted, and the quality cache is written either way: a model whose cost was not read keeps no cost, which is unknown, never zero. A run reads four model pages at most, and the weekly refetch of a model that is not deprecated stays. A board that could not be read keeps the last good board and does not hold the quality cache back: the board is not the quality data. The board is written only when the page carries the whole board, that is, when the rows the page renders and the models it scores are the same ones and their names are unique: the ranks and the normalisation of the 3D tier are computed over the board, and a partial board would be normalised over a part of it. The 3D reader accepts the whole snapshot or refuses it, so a file it refuses leaves the tier empty.

## [3.17.68] - 2026-10-22

- AI usage collector: a metric series is published once. The free pool published the account limits of a provider once per model of that provider, so a provider with two models published the same limit twice and the node exporter dropped the repeat. The account limits belong to the account, and they are published once per provider now. The renderer holds the same rule for every series: a repeated name with the same labels is dropped and counted, and the count is published as `ghostship_ai_collection_duplicate_series`, so a duplicate never passes unnoticed.
- AI usage collector: the free tier is ordered by the routing policy instead of by name. The eligible routes within five Artificial Analysis intelligence points of the best eligible free route form the quality band, and the band comes first, ordered by the most remaining headroom of the route, with the least recently used route breaking the ties. The rest of the tier follows by intelligence, and a route without an intelligence record comes last. The headroom is the remaining share the collector measures for the route, and the moment the pool last used it is published as `ghostship_ai_pool_route_last_used_timestamp_seconds`, so the rotation is visible. The band is published with the position of the free tier as the label `band`, and the other tiers keep their own order.

## [3.17.67] - 2026-10-22

- SIEM alert bridge: a re-fired alert is no longer silenced forever. The 6-hour renotify window throttles repeat notices of one occurrence, but a resolve-then-fire cycle inside the window was dropped and its notification timestamp was never advanced, so the fingerprint stayed silent for good while the topic said "resolved". A re-fire inside the window is now deferred rather than dropped: it is recorded as pending and announced on the first poll after the window has elapsed, if the alert is still firing by then, and at most once per window. A re-fire outside the window still announces immediately.
- SIEM alert bridge: a failed resolution publish is no longer lost. The retry covered firing alerts only, so a resolution that ntfy refused left the topic showing a critical alert that was never resolved. A resolution is now published again on the next poll until it is delivered, like a firing alert, and an alert whose resolution has been undelivered for a day becomes a dead letter, listed by `--list` and counted by the `ghostship_siem_bridge_dead_letters` and `ghostship_siem_bridge_resolution_retries` metrics.


## [3.17.66] - 2026-10-22

- The 3D tier gets its AA-3D evidence. The public pull returned early whenever the main Artificial Analysis cache was fresh, so the AA-3D file it writes was never created and every model read "no usable AA-3D snapshot": the 3D tier was empty, and the 3D reserve could not apply, so a 3D-qualified model led the bulk tier. The pull now skips only when both caches are usable.

## [3.17.65] - 2026-10-22

- Pin ghostship-agent 2318134e (0.43.2): capability handlers import on first call, so the MCP browser tools work again. 0.43.1 left registration importing every handler, and the GitHub handlers' missing package still failed every MCP call.

## [3.17.64] - 2026-10-22

- Pin ghostship-agent af089700 (0.43.1): restores the MCP server's agent browser; GitHub review capabilities are CLI-only.

## [3.17.63] - 2026-10-22

- The AI usage collector publishes real headroom for the accounts that showed "Unknown headroom". The Ollama Cloud account had no window at all, so the balance endpoint is read now: `included.session` and `included.weekly` become the session and the weekly window of the account, the used share is the rest of the remaining percentage, the reset is the instant the provider published, and the scope is the account, so the windows gate every `ollama-cloud` route. The provider publishes no length for the session window, so the collector remembers the reset instants it has seen and learns the length from the step between two successive resets; until two resets have been seen the length is a derived fallback and it is marked as derived. The OpenRouter account published an amount and no window, so the key endpoint becomes one: `free_model_daily_requests` is the daily allowance of the free models, the day ends at the next midnight UTC, and a counter above the limit means the day is spent. The per-minute limit of the free models is published rather than reported, so it is a minute window with the basis `published+counted`, counted against our own requests in the T3 Code state. The OpenCode Go free routes were published as exhausted because the plan's monthly window was spent, even though the Go documentation lists them as unlimited and a live probe confirmed it: each of those routes now carries a window of its own, the window says `unlimited (limited-time promotion)`, and the paid allowance of the account does not gate it. The same documentation says the free models are unlimited "for a limited time", so the basis of those routes is `promotion` and the end of the promotion is unknown: no end date is published, and an unknown end is never a guess. A paid route of the same account is still gated by it. Every window carries the basis of its numbers now, and the bases are never mixed.
- An unknown headroom always says why. Every candidate row of the routing snapshot carries an `unknown_reason` beside its `quota_state`: the provider publishes no quota window for this account, or the provider's window was not read, is stale, or has already reset. The same reason is published as `ghostship_ai_model_quota_unknown`, and the dashboard lists the unknown headrooms with the reason beside them. The owner rule is enforced with tooling: the snapshot of the enabled providers is checked against a committed fixture, and a row whose headroom is unknown without a reason fails the check.
- Every ranked model stays in the published metrics, including the ones that cannot be used right now: an unavailable or exhausted model keeps its capacity series (zero when the allowance is spent), its availability with the reason it is not usable, and its rank. Only the winners are allowed to exclude a model.
- A provider that refuses a request with `402 Payment Required` and a spent balance has an exhausted account, not a broken route, so every route of that provider is unavailable with the reason `account_usage_limit` until a later run of it succeeds. A model without a prefix is charged to the account of the instance that serves it, so a Grok route is the Grok account and not the OpenCode one.

## [3.17.62] - 2026-10-22

- Pin ghostship-agent f6a415dd (free-pool grant removal and conservative unknown limits). The revision descends from the pinned `cb003746`, so nothing on the pinned line is dropped and no `pin-regression-approved` line is needed. It carries the free-pool fixes: a route's eligibility no longer depends on a workload grant, an expired grant or its dates, so an account with no grant at all is routed whenever its limits have headroom; a route whose provider exposes no applicable window starts on the conservative default window (one request a minute, fifty a day, basis unknown) and is learned up or down from the responses; a workload routes only to pairs its bench admitted, and the package ships the research bench the research workload names; the routes rotate by quality band and remaining headroom, with the least recently used route breaking ties; and a cooldown is a bounded duration in seconds, so a provider-wide park no longer lands in the year 31745. It also reads the rate-limit headers of every provider that sends them (#73). It carries the merged policy tooling (#55), the review gate, role order, agent marker and hygiene policies (#61), and the GitHub coordinator's repository-alias handling (#64), which the organisation rename depends on.
- Repository references follow the organisation move. The private agent input, its lock owners, the private-source CI import, the auto-upgrade and agent-desktop update remotes, and the desktop promotion target now name the `ghostship-io` organisation and the renamed repositories. The pin moves with the owner: the lock names `f6a415dd`, so its revision, content hash and timestamp change too. The private-source importer reads the owner from one constant, accepts the organisation's namespace and the previous account while a lock still names it, refuses any other owner, and derives the fetch URL from the lock it just validated. The coordinator's repository map, its incident repository and the webhook receiver's allowlist use the canonical names, and a repository alias map keeps existing issue owners, queued deliveries, CI issue mappings and pull request links across the transfer. Local checkout paths, T3 project identifiers, the Actions environment reviewer and the container image registry paths are unchanged.

## [3.17.61] - 2026-10-22

- Grafana dashboards lead with graphics: Providers (four tier columns of % left, T3-style provider cards, collapsed Why this order), Overview, Host, Security and Pipeline. Shared navigation is Overview, Work, Providers, Host, Security, Pipeline. Allowance bars show remaining ("% left") coloured critical below 10%, warning below 30%, otherwise good. The ordering measure is labelled **Paced Availability**. Freshness keeps series whose timestamp is within 90s of the newest collection, so entitlement and fact cards stay filled when sample timestamps are a few seconds apart. Frontier bars are labelled Chief (Claude Opus 5.5) and Backup (Codex GPT-6.1-Sol); order inside the tier stays Paced Availability. Every ranked route of a tier is listed with the % left of its lowest applicable window: the available routes by Paced Availability, the exhausted and unavailable ones below them, greyed, with the reason they are spent. An unknown allowance is grey and reads Limits unknown, never a red bar that looks like 0%. The model names are the names a person would say, not the provider's own id.

## [3.17.60] - 2026-10-22

- The SSH command guard's refusals reach the journal. The guard passed the message to `systemd-cat` as an argument, and `systemd-cat` runs its arguments as a command, so every refusal failed to journal and the caller also saw a "Failed to execute" line after the refusal. The message now goes on stdin and the journal tool's own output is dropped.

## [3.17.59] - 2026-10-22

- The GitHub coordinator's hold lives in the host configuration. It was held off with a runtime drop-in under `/run`, and an activation clears runtime unit overrides, so the 2026-10-22 deploy started it and it replayed part of the deployment backlog before it was stopped again. `ghostship.githubEngineering.coordinatorAutoStart` (default on) now decides whether boot or an activation starts it, and chill-penguin sets it off until the replay fix passes a backlog replay. The webhook receiver keeps spooling while the coordinator is held.

## [3.17.58] - 2026-10-22

- Main's Fleet checks are green again. The regression tests run inside the Nix check derivation, whose sandbox holds the store and little else, and two assumptions broke there. The activation helper starts with `#!/usr/bin/env bash`, and the sandbox has no `/usr/bin/env`, so the kernel could not resolve the shebang and the test reported the helper as missing although it was in the tree. The test now runs the helper with the interpreter its shebang names. The agent SSH command guard started every session in the login shell of the account the session ran as, and that account names a shell the sandbox does not have, so every session the guard started failed. The guard now falls back to a shell that exists when the account's shell is missing, and it accepts the shell the host pins.
- Private-source environments: neither `private-source-ci` nor `private-source-main` asks for a reviewer. The owner removed that gate on 2026-10-22, because it should only hold back other people, and the environment-scoped read-only agent key is released without an approval. Only the `main` branch may deploy to `private-source-main`, and a pull request from a fork gets no environment secrets at all, because GitHub withholds them from a fork. The fleet operations document records that state, and the unused `GHOSTSHIP_PRIVATE_SOURCES` environment secret is gone.

## [3.17.57] - 2026-10-22

- Test fixtures hold no personal identifier. The command guard's test used the owner's key line, with the owner's handle and home host, in a public repository; it now uses a role placeholder with synthetic key material, and the agent pin fixture uses a synthetic organisation. The command guard's regression tests also prove that the `nix-daemon --stdio` command of the `ssh-ng` transport and an interactive session, which sends no command at all, both pass the guard.

## [3.17.56] - 2026-10-22

- Test fixture lint: the tests read only committed fixtures. `scripts/check-test-fixtures.py` fails the check when a test reads a scratch path such as `/tmp`, `/var/tmp`, `/home` or `/workspace`, which exists on the machine that runs the test rather than in the repository, and which is how pull request #190's `test_ai_usage_aa_pull.py` read `/tmp/aa-pull/raw` and failed in CI. A test that needs such a path builds it in a temporary directory, or states on the line why the reference is harmless with a `# fixture-path-ok: <reason>` comment.

## [3.17.55] - 2026-10-22

- T3 restart guard: T3 Code is never restarted unless it is idle, except when the owner has asked for work to be activated or deployed. A forced restart bypasses the idle gate and interrupts the work in flight, so `t3code-safe-restart --force` now requires `--owner-request "<short quote or reference of the owner's instruction>"` and refuses without one. Every forced restart is recorded in `/var/lib/t3code-restarts/ledger.jsonl` with the time, the actor, the reference, and the container identity before and after the restart, and in the journal under the `t3code-restart` tag. The queued restart still waits for the activity probe to confirm idle and defers while T3 Code is busy, and the evaluation check asserts that a switch has no unit to restart, so `podman-t3code` keeps `restartIfChanged = false`.

## [3.17.54] - 2026-10-22

- Agent pin guard: a pull request that moves the `ghostship-private-agent` pin to a revision that does not descend from the pinned one silently dropped everything on the pinned line. `scripts/check-agent-pin.py` now compares the pull request's pinned revision with the base branch's and fails unless the new revision descends from the old one, which git answers in the fetched agent source, or the pull request body or one of its commits carries an explicit `pin-regression-approved: <reason>` line. The check runs in the Fleet checks job, where the read-only agent key is available, and skips outside a pull request. The shared private-source access moves to `scripts/private_source.py`, which the CI import now uses as well.

## [3.17.53] - 2026-10-22

- Host activation helper: `scripts/activate-host` records the system generation before switching. It runs `nix-env -p /nix/var/nix/profiles/system --set <toplevel>`, then `<toplevel>/bin/switch-to-configuration switch`, then compares `readlink -f /run/current-system` with `readlink -f /nix/var/nix/profiles/system` and exits non-zero when they differ. A bare `switch-to-configuration switch` on a built toplevel leaves the two apart, so a reboot reverts to the profile's generation. The repository had no activation script, so the helper is new; the deploy flow in the operating notes and the fleet operations document use it.

## [3.17.52] - 2026-10-22

- Boot generation drift check: a new `ghostship-boot-generation-drift` timer compares `/run/current-system` with `/nix/var/nix/profiles/system` every five minutes. An activation that does not record the system generation leaves the two apart, so a reboot reverts to the profile's generation. A mismatch that lasts more than ten minutes reaches operations through `ghostship-notify` with the `boot-generation-drift` dedupe key, and a recovered generation resolves the alert. The check reads two symlinks and never searches the host.

## [3.17.51] - 2026-10-22

- Agent SSH command guard: the agent workspace key now runs `ghostship-ssh-command-guard` as its forced command on `chill-penguin`. A recursive content read rooted at `/etc`, `/root`, `/home`, `/var/lib` or `/` is refused with exit status 126 and a journal line under the `ghostship-ssh-command-guard` tag, and every other command runs unchanged, including interactive sessions, `scp`, `sftp`, `nix-store --serve` and `ssh-ng` transfers. The owner's own keys are authorized without a forced command. A copy of the agent key outside the managed authorized keys file is removed at activation, because sshd stops at the first file that holds the key. The regression tests use the commands agents actually ran on 2026-10-22, including the `grep -rl` over `/etc` and `/root` that opened a SIEM investigation.

## [3.17.50] - 2026-10-22

- Agent desktop browser stage: a stage-control restart re-pairs the windows it finds. Sway does not re-announce the windows it already has, so the anchor titles (the run id in a window's title) were only learned from new window events; after the restart that `run-chrome` loops on, every window stayed unpaired and `browser_window` `screenshot` and `ui` failed with `not_found` until the page titles happened to differ. The stage now reads the sway tree once at setup and seeds the anchor titles from it.
- Agent desktop browser stage: only the focus lease's holder may release it. The viewer released a window's lease whenever its last client left, so a person closing the viewer closed the Chrome menu an agent was working with, and the agent's next click landed on the page behind it. The release now carries its actor (the viewer speaks for a person, the agent's CLI for an agent), a lease that belongs to someone else is left alone, an idle lease still expires on its own, and an explicit admin request (never from an agent) forces it down.

## [3.17.49] - 2026-10-22

- GitHub-launched threads lead with the chief reviewer (Claude Opus 5.5), with Codex GPT-6.1-Sol as the backup, per the owner's role policy.
- Make Grafana the autonomous-work landing page, with direct navigation among work, host, security and pipeline dashboards. Read bounded T3, broker, runtime and systemd observations into the existing Victoria stores, with source/freshness limits and no transcripts or new orchestration service.
- Configure revision-bound security/integration review in existing repository owners and approved usage-aware model routing. Prefer the owner's OpenCode MiniMax Flash Free route; preserve provider-specific options and explicit deployment approval. Correct the canonical ROM repository name and use actual NixOS CI check names for proof.
- Close observed newsletter failure episodes independently of ntfy resolution delivery. A relapse gets a fresh persisted incident ID and a firing notification after the pending resolution succeeds. A compact sequence retains every unacknowledged handoff across repeated recovery/relapse cycles, retries one per observation even while healthy, and preserves existing episode IDs. Real-notifier and pinned-coordinator fault injection covers the relapse, bounded pending state, and a lost durable acknowledgement.
- Pass the pinned agent source into sandboxed configuration tests. Newsletter incident integration tests no longer need a Nix executable or nested flake evaluation inside the builder; they continue to exercise the real pinned coordinator.
- Separate newsletter incident acknowledgement from ntfy delivery. The notifier's incident-only operation acknowledges an fsynced spool write; the monitor persists one event ID per episode before sending and retries it independently. Notification outages do not enqueue recurrence messages, and spool failures remain retryable after ntfy succeeds. Regression tests exercise the real notifier and pinned coordinator with local fake edges, including lost acknowledgements and persistence failures.
- Observe Ghostship AM outcomes from a host timer, using the newsletter's runtime-only monitor as its unprivileged user. Missing delivery, stale/invalid daily artifacts, or an unavailable monitor raise an operations alert and the existing bounded coordinator incident; recovery sends one resolution. No new sender, repair loop or T3 restart path is added. Requires newsletter 0.5.18 or later in the canonical checkout.
- The AI provider decision page reads the canonical entitlement family for its allowance and limit cards, so one entitlement is one card: the two alias readings of the same window (the T3 status names the OpenCode Go windows go_monthly/go_rolling/go_weekly and the provider names monthly/rolling/weekly) are no longer shown as two allowances, and the shared parent window gate matches the placeholder model scope the collector publishes. The quota table keeps every raw reading with its quota and source. No routing or dispatch decision consumes the ranking; the owner reviews and approves it.

## [3.17.48] - 2026-10-22

- Antigravity: restore the native GCC library path when the emulated ACP server launches its native harness. T3 MCP children inherited only the x86 guest glibc path and failed to load ARM64 `libatomic.so.1`. A QEMU regression check exercises the guest-to-native harness and MCP child boundary.

## [3.17.47] - 2026-10-22

- AI usage collection: expose one canonical display reading per verified quota entitlement, so a top card cannot double-count the same allowance. The new `ghostship_ai_entitlement_{info,used_ratio,reset_timestamp_seconds,expected_used_ratio,pace_delta_ratio,observed_timestamp_seconds}` family carries `provider/account/model/window/quota/source/entitlement`; the reading is the current usable one with the least remaining, and its reset, expected line, pace, observation and source all come from that same reading rather than independent extrema. The info series is emitted even when no numeric reading is usable, with `source=""`, so an unknown entitlement stays visible and is never shown as zero or one. The raw per-reading series and `quota.entitlements[].readings[]` are retained, the fixed Go alias proof is the only merge, and unpaired entitlements, different accounts and unrelated windows keep their own identity. No dashboard file, service, scorer or client is added.

## [3.17.46] - 2026-10-22

- AI usage collection: every applicable parent limit gates a model together with its own model window. A model-scoped quota reading no longer replaces the shared account cap; the shared windows that name the model (or name no model) and the model windows are combined, and an unrelated family window is still excluded by its scope. An exhausted weekly parent with a model window at 5% now leaves the model at zero and unavailable, and `capacity.scope` publishes `parent_windows` and `model_windows` beside the exemption flag (still false unless the provider reports an independent entitlement). A model-scoped candidate no longer raises an unbound name when it is ranked first or alone; a single-model first-loop regression covers it. Free and promotional routes stay bound to the paid account allowance unless a scope is reported.

## [3.17.45] - 2026-10-22

- AI usage collection: the owner approved a High execution default for the exact DeepSeek V4.1 Flash models. `deepseek-v4.1-flash` and `deepseek-v4.1-flash:1017` (after the provider namespace) now run High by default, while every other model keeps medium with high escalation. The id is compared exactly: no substring, family or suffix rule, so other DeepSeek models, MiniMax and similarly named ids do not inherit it, and a Flash model whose option does not list High is a fail-closed capability mismatch with its supported list published. The exception is visible in `aa.condition` (`execution_default`, `execution_exception`, `execution_basis`), in `alignment`/`alignment_meta` and in `runtime_policy`, and the AA best-80/20 reference and its Max condition are unchanged.

## [3.17.44] - 2026-10-22

- AI usage collection: a promotional or free route is no longer exempt from its account's paid allowance by observation alone. The ranking previously removed the paid allowance windows from a free route when the route was seen operational while that allowance was spent; that is an inference, not a reported scope. On the same account and provider (OpenCode Go's monthly/window set, where the free MiniMax Flash shares the `opencode-go` account), the measured window is now attached, the model shows the spent remainder and is not a winner. `capacity.scope` publishes the account, the applied window count, whether a model window was used, the observed free route, and `exemption` (false unless a reported scope separates it). A provider-reported model window remains the separate scope. Tests cover both the same-account block and the operational observation no longer removing the window. Routing stays off.

## [3.17.43] - 2026-10-22

- AI usage collection: reconcile duplicate allowance readings without dropping an identity. The T3 status surface's `go_monthly`/`go_rolling`/`go_weekly` windows and the OpenCode Go endpoint's `monthly`/`rolling`/`weekly` windows are published as one entitlement per verified alias: each reading keeps its own source and quota id, and all of them share `entitlement` with `relationship=same_entitlement_independent_readings` and `alias=true`. The snapshot exposes `quota.entitlements` with every reading, and `ghostship_ai_quota_entitlement` is emitted per reading with the shared id and the exact source. Different accounts or model scopes stay separate entitlements, and an unpaired window keeps its exact key. Nothing is merged or dropped, and no dashboard is edited.

## [3.17.42] - 2026-10-22

- AI usage collection: the AA record selection is now independent of the native runtime setting. The resolver takes the best measured `0.80 intelligence + 0.20 cost per task` value among the exact records of a model, with both inputs required, no Max preference and no dependence on a native current value; changing only the native option from low to medium leaves the reference, indices and score identical (covered by a test). The chosen measured condition is the published reference, every other condition is retained in `alternatives` with its own value, and two records of the same condition are an ambiguity that is refused. A record without both inputs has no reference and the model is not selected, while its raw record stays visible. The runtime reasoning policy (medium default, high escalation) remains separate, and the DeepSeek V4.1 Flash 1017 medium mismatch stays an explicit capability mismatch until the owner answers.

## [3.17.41] - 2026-10-22

- AI usage collection: model selection and runtime reasoning are separated. The model ranking stays the measured AA intelligence and cost per task, while the runtime policy is owner-defined and independent: medium by default, high for escalations. The alignment is the runtime recommendation (`alignment` names the option id and medium, `alignment_meta.escalation` names high, with the actual current value and whether it is applied), and the AA benchmark condition stays visible without ever being presented as our run condition. A model is selectable on a verified identity, its admission and a published option that supports the default; DeepSeek V4.1 Flash 1017, which advertises low/high/max, is an explicit capability mismatch with its supported list and option published and no silent substitution. MiniMax M3.1 Flash and the Claude and Codex effort lists support the default and the escalation. Stock option ids survive even without a current value, and the 3D strict loader repair is unchanged.

## [3.17.40] - 2026-10-22

- AI usage collection: stock option descriptors are preserved end to end. The source keeps a descriptor without a current value and reads the stock allowed choices from `options=[{id, label}]` as well as the simple list forms; the snapshot and the resolver keep the descriptor ids, and an alignment names the option id and a value the model actually lists, with `recommended`, `applied` and the actual current value published beside it. A model whose measured condition is not its own is selectable only with that alignment; an unknown condition with an empty alignment is no longer selectable, and an unrecognized annotation is reported as an unknown condition rather than an exact one. The AA-3D loader also enforces finite, unique, sequential ranks and an interval that contains its Elo, never raises on a non-finite rank, publishes a fixed public attribution, and forwards only the allowlisted record fields. The snapshot reconciles the offered inventory against its candidates in `coverage.ranking`, naming any excluded model. No deploy, projection or dashboard change.

## [3.17.39] - 2026-10-22

- AI usage collection: the AA-3D loader now matches the strict contract of the root-acquired evidence snapshot. It enforces the evidence schema and version, the AA-3D benchmark with a non-empty version, the canonical public source URL, `completeness.complete` with a matching record count and the entire-displayed-leaderboard scope, and the bounded 2 MiB read. It refuses the whole snapshot on a truncated board, a duplicate or missing record, a malformed or negative cost, a half or inverted interval, a malformed rank, or a future or unparseable observation time; it never drops a record or rebases a partial board. The published source and conditions are the fixed public ones, not arbitrary fields from the file. The normalization is the root's relative min-max over the complete board, published once with its bounds and fingerprint; the per-record normalized value and free-form linear transform are no longer accepted. The 22-row root snapshot is covered, together with each refusal. The stale calculation text that called a free route the lowest intelligence tier is replaced by the access-and-cost classification the owner directed.

## [3.17.38] - 2026-10-22

- AI usage collection: the release blocker in the entrypoint is fixed and covered. `ranking_samples` takes the AA feed and the AA-3D snapshot as explicit parameters, the CLI loads each cache once before the collection, and `main` passes them through `collect` to the ranking and the snapshot; there is no module global and no per-model re-read. `main.build_snapshot` accepts the free and promotional route sets the caller passes. The ranking binds each model once, with the native options the stock catalog published (including the allowed values), so a model with an explicit high effort reaches its exact High record instead of going ambiguous in the ranking and being silently unranked; the snapshot uses the same binding. A new entrypoint smoke test runs `main.collect` and `main.main` with faked sources and a real catalog, proving the AA and AA-3D feeds reach the tier membership and the written snapshot. The strict no-effort ambiguity remains, and every matched or unranked model stays visible with its reason.

## [3.17.37] - 2026-10-22

- AI usage collection: consume the root-acquired AA-3D evidence snapshot. The reader accepts the actual 22-row board shape (exact measurement name, raw Elo, 95% interval, rank and rank range, anchor flag, AA-3D cost per task, source URL, read time, attribution and benchmark version), validates every row, and refuses a malformed or negative Elo. The capability is normalized by the root's relative min-max policy over the complete board before any exclusion, with the bounds and a board fingerprint published; all-equal Elo means 1 and the cost breaks the tie, and the value is explicitly not a win probability. The cost-aware 3D value uses the AA-3D cost when present and otherwise the normal Artificial Analysis cost per task as the owner-approved proxy, published as `cost_source=artificialanalysis_intelligence` with `proxy=true`. The provider capacity is also published as metrics with its binding window; an unknown account window now suppresses a positive capacity, a spent window publishes zero, and model-scoped subordinate windows never constrain the provider's overall capacity. No HTTP client, poller, dashboard edit or deployment is added.

## [3.17.36] - 2026-10-22

- AI usage collection: the cost-aware 3D value now has the owner-approved cost fallback. The capability is the AA-3D Elo under the source's published normalization, and the efficiency is `1 / (1 + cost per task)` with the AA-3D cost when the feed publishes it. When it does not, the normal Artificial Analysis cost per task of the same model is used as an explicit proxy: `cost_source=artificialanalysis_intelligence` and `proxy=true` are published with the value, together with the statement that it is not a measured 3D cost. Missing both costs leaves the combined value unknown while the raw Elo, its interval, the source and the date stay visible. An Elo is never divided by 100 and no win probability is claimed without an AA calibration source; the normalization is the source's own transform or the value is unknown. The 3D page shows a cost graph without enumerated values, so nothing is read from it or extrapolated.

## [3.17.35] - 2026-10-22

- AI usage collection: the 3D tier ranks the measured Artificial Analysis AA-3D evaluation and nothing else. A separate bounded snapshot (`--aa-3d-cache`) carries the Elo, its confidence interval, the source, the observation date, the task count and the benchmark conditions; the reader validates every row, refuses a malformed or negative Elo, and treats a snapshot older than 30 days or without a usable row as not measured. The Elo is normalized only by the source's own published transform (min-max or linear) or an explicit normalized value; otherwise the combined 3D value is unknown while the raw Elo and interval stay visible. The 3D value is cost-aware with the published `0.80 * normalized Elo + 0.20 * 1/(1 + AA-3D cost per task)` policy and never mixes in the language benchmark's cost per task; a missing 3D cost leaves the value unknown. The tier still requires proven image input, Astra and Fable stay excluded, and no HTTP client, poller or credential is added. The language ranking is unchanged, and a model without a measured AA-3D Elo stays pending and unranked.

## [3.17.34] - 2026-10-22

- AI usage collection: the remaining guessed numbers are gone. Quality is the measured Artificial Analysis index with no prior, median fill, recency or family bonus, and the combined value is the owner's published policy `0.80 * I + 0.20 * E` with `I` the intelligence index over 100 and `E = 1 / (1 + cost per task USD)`. Both inputs are required, a missing cost leaves the value unknown while the raw index stays visible, a zero cost is a valid efficiency of one, and a negative or non-finite cost is unknown rather than free. The value policy, weights, transforms and units are published with the snapshot. The binding is exact and ordered: a version written `6.1` and `6-1` are the same version, while `gpt-1.6-sol`, `sol-6.1-gpt` and `gpt-5.4` never take another model's record, an undated id never borrows a checkpointed record in any cache order, several records of the same identity or condition are ambiguous, and only the feed's own `(Max, Default Fallback)` annotation can stand for a default condition. A native effort is read only from the model's published option descriptors; an alignment is emitted under the option id the model actually uses (effort, variant, reasoningEffort) and only with a value that option lists, and a condition word in a model name such as `Qwen3.8 Max` is not an effort. The frontier is the owner's two workhorses, GPT-6.1 Sol and Claude Opus 5.5, and only a verified admission with a proven image input admits a model to the 3D tier, which otherwise shows pending; Astra and Fable stay visible in the usage and quota readings but are never a winner or a recommendation. The provider capacity is the lowest applicable remaining share, a spent window blocks the provider, and each model publishes its own capacity and pace binding with the exact window ids when they differ. No dashboard, deployment or provider was touched, facts ingestion stays off, and no new client or poller was added.

## [3.17.33] - 2026-10-22

- AI usage collection: quality is the verified Artificial Analysis record and nothing else. The provider-model to record binding is exact on the model's own identities (id, slug, display name, documented alias) after removing routing namespaces (`nvidia/`, `@cf/google/`), promotion markers (`:free`), instruction-tuned packaging (`-it`) and a leading vendor brand, with checkpoints and release dates verified against the record (a `:1017` id binds to the 1017 record; `20250929` binds only to the matching `release_date`; a different release is refused). A reasoning variant travels with its record: a Max measurement shown for a High native setting keeps its Max label and is not selectable unless the native options can be aligned, and a model the feed has not measured is unranked, visible with its reason, and carries no quality or value number at all instead of a median-filled or prior one. The snapshot publishes a per-candidate `aa_coverage` block (state, reason, AA id/slug/name, release date, measured and native variant, match rule) and the live audit binds 172 of 245 candidates instead of 37 name matches. `beam`/`Beam 1.0 501B A23B` resolves to the AA `reflection-beam` identity and is kept out of the 3D tier by the feed's text-only evidence. The README states the metric semantics for the dashboard time picker: every series is a gauge, no series is a counter, rolling provider windows cannot be summed over a range, and the collector does not add a poller, a database or a custom time UI.

## [3.17.32] - 2026-10-21

- AI usage collection: a read-only host collector (`ghostship-ai-usage.service`, every five minutes) reads T3 Code's own provider limits and usage summary, Grok, OpenCode Go, Antigravity, OpenRouter, Ollama, the free inference pool and the public model catalog, and writes one node_exporter textfile for VictoriaMetrics. A new Grafana dashboard in the "Ghostship" folder shows the quota, usage, free model and model ranking readings, with the age of every reading, so a missing or stale source is never shown as healthy quota. The collector also writes the canonical routing snapshot at `/var/lib/ghostship-ai-usage/routing.json`, which keeps the owner's policy, the measured quota windows and the model priors apart: a missing, malformed or stale reading stays unknown, an exhausted window excludes its model, a reset in the past is not a refill, and the model that is behind the line its window draws by now is preferred, so the usage spreads across the reset limits. No provider, container or T3 Code session is started, stopped or reconfigured, and no metric, snapshot or label carries an email, an account identifier, a path or a key.

## [3.17.31] - 2026-10-21

- Document native T3 Code quota verification, the temporary sensitive environment override for OpenCode Go Console OAuth, intermittent Antigravity Gemini coverage, and the native panel's OpenRouter/Ollama limitations. Record the standalone 0.1.1 packaging and host activation requirements; the npm-based automatic updater still needs migration. T3 Code source and provider logins remain unchanged.

## [3.17.30] - 2026-10-21

- Flow collector: a released container address keeps its previous owner for 15 minutes (one collection plus margin), not 24 hours. Gluetun's short-lived benchmark containers reused bazarr's, cloudflared's and flaresolverr's old addresses, and their udp/1337 probes were recorded as new edges for those services. After the grace period an unowned address reports as `lan:<ip>`.

## [3.17.29] - 2026-10-21

- AppArmor: agent-desktop SSH shells may run the Rust coreutils multicall that `/usr/bin/timeout`, `date`, `mkdir` and similar resolve to. An agent's `timeout blender` ran in ruleless `null-*` profiles at 13:55: about 246k audit records in 10 minutes, 2 lost.

## [3.17.28] - 2026-10-21

- AppArmor: NZBGet's startup system-info probe (popen `uname -o/-r/-m` and `lscpu | grep` through `/bin/sh`) runs in its own `sysinfo` child, which may run only BusyBox sh/grep and coreutils uname, with no network or writes. It had raised `SuspiciousExecInAppDomain` after the Gluetun IP change restarted NZBGet at 17:27; investigated as legitimate (#102). Any other shell from the server still alerts.

## [3.17.27] - 2026-10-21

- Pin ghostship-agent 0.36.0: `gws`, the Google Workspace official-API CLI, is retired with its `google-workspace-cli` flake input (the lock drops it and its nixpkgs), so the managed install removes the `gws` command from T3 Code; Google work runs through the browser workflows. Also drops the ignored `shoppingConfig` argument, dead CloakBrowser Keep clients and retired Prefect/CloakBrowser notes.
- Delete the unreferenced `private-integrations/shopping-overlay.json`.

## [3.17.26] - 2026-10-21

- Pin ghostship-agent 0.35.1: `t3` `status` takes `wait_s` and answers once the task's active turn ends. `browser_op` `extract` defaults an unnamed step to `step<index>`, and with neither `js` nor `selector` returns the page's visible text.
- The host operations broker keeps `/run/ghostship-hostops` across restarts (`RuntimeDirectoryPreserve`). The MCP container bind-mounts that directory, so after each broker restart it was left holding the deleted directory, and `services_call` host operations failed as "not reachable" until the container restarted.

## [3.17.25] - 2026-10-21

- Pin ghostship-agent 0.34.1: `t3_task` `files` accepts ChatGPT conversation files, whose download URLs are on OpenAI's Azure storage accounts.

## [3.17.24] - 2026-10-21

- Pin ghostship-agent 0.34.0: `t3_task` `submit` and `send` attach files to T3 threads as native message attachments (ChatGPT conversation files through `files`, inline base64 or chunked `upload`), so a thread's agent sees images as image input and gets every other file saved on the T3 host.

## [3.17.23] - 2026-10-21

- Fix Grafana startup (#177). The vendored VictoriaLogs plugin is kept unmodified, because pruning the other platforms' backends failed its signature check. Provisioning is now real files, with dashboards inside the mounted directory; the store symlinks pointed outside the container.

## [3.17.22] - 2026-10-21

- Falco: narrow exceptions for Debian package scripts in image builds (`crun-buildah`). These are `systemd-sysusers` under dpkg reading `/etc/shadow`, and fontconfig's postinst truncating `/var/log/fontconfig.log`. Both were investigated on the scheduled agent-desktop rebuild at 13:02 (#102).

## [3.17.21] - 2026-10-21

- SIEM UI: Grafana 13.2.4 (distroless, pinned) at `grafana.ghostship.io`, behind Cloudflare Access, as the single monitoring UI (#102 decision B).
  - **Datasources:** VictoriaLogs (vendored signed plugin v0.33.1) and VictoriaMetrics, read only through a new vmauth proxy that routes only query paths.
  - **Dashboards:** host and containers, SIEM pipeline, and security events, provisioned from the repo and not editable in the UI.
  - **Disabled:** Grafana alerting, plugin installs, preinstalls, update checks and telemetry.
  - **Network:** a new internal `ghostship_siemui_net` with no egress and no host access but DNS. cloudflared joins it at a fixed address, the only one Grafana's auth proxy trusts.
  - **Container hardening:** strict flat AppArmor profiles, read-only images, no capabilities, no-new-privileges, noexec tmp, run and data.
  - **Heartbeat:** a static read-only helper serves the AppArmor heartbeat for the shell-less Grafana image.

## [3.17.20] - 2026-10-21

- Give qBittorrent 60 seconds to shut down before Podman forces termination, within systemd's existing two-minute stop limit. Ordinary restarts previously hit Podman's 10-second default and reported exit 137.

## [3.17.19] - 2026-10-21

- The Gluetun network monitor and qBittorrent's pre-start and auto-resume scripts probe the VPN namespace from the host (`nsenter -n` with host `curl` and `ip`) instead of `podman exec gluetun wget|sh -c ip`.
  - **Before:** about ten processes a minute were exec'd into the VPN container, landing in its top AppArmor profile.
  - **API key:** the Gluetun API key moves from wget's argv to a curl header file descriptor.
  - **Verified live** before merge: VPN status, public IP, forwarded port, tunnel IP and the qBittorrent API answer; requests without the key get 401.

## [3.17.18] - 2026-10-21

- Falco: narrow exception for T3 Code's in-container systemd reading `/etc/pam.d/systemd-user` when it starts the user manager. It fires on every sanctioned T3 recreate; investigated 2026-10-21 (#102).

## [3.17.17] - 2026-10-21

- `ghostship-security-check` flags any unconfined process inside a container (`apparmor.unconfined.<container>`, critical), not only a wrong PID 1 label. It walks the container's cgroup tree. A policy reload that removes a complain-mode `null-*` learning profile leaves its processes unconfined; on 2026-10-21 that left the agent desktop's PulseAudio unconfined, and the old check missed it.

## [3.17.16] - 2026-10-21

- `ghostship-apparmor-review` reads evidence from VictoriaLogs, filtered per profile on the server, instead of a day of journal JSON.
  - **Old behaviour:** the journal keeps only hours at audit flood rates, so yesterday's continuity anchor was always rotated away and every profile reported `audit-collection-failed`. The 08:30 run took 7 minutes and peaked at 9.3 GB.
  - **Live dry run:** under 2 minutes, with heartbeats found in the store for every container.
  - **Exited processes:** a process that exits between `podman top` and the label read is skipped instead of failing inspection. That caused Muximux, pyLoad, qBittorrent and RomM `inspection-failed`.
  - **Chaptarr:** its top profile is never live (PID 1 enters `server`).

## [3.17.15] - 2026-10-21

- Pin ghostship-agent 0.33.0: `browser_window` screenshots name the toolbar buttons (each pinned extension by name, then the extensions menu and the profile), so ChatGPT can use extensions without relying on tooltips.

## [3.17.14] - 2026-10-21

- Pin ghostship-agent 0.32.1: `browser_window` screenshots are never scaled (a tooltip past the window's edge had shrunk the frame, so its pixels no longer matched `ui` clicks), and `ui` accepts key names as ChatGPT writes them.

## [3.17.13] - 2026-10-21

- Pin ghostship-agent 0.32.0: `browser_window` screenshots also arrive as a text map (visible text and toolbar controls with click coordinates), so ChatGPT, which does not show tool images to its model, can use Chrome's own controls and extensions.

## [3.17.12] - 2026-10-21

- Docs: AppArmor profile-authoring pitfalls verified during the strict-profile rollout: null learning profiles, child `cx` scoping, no_new_privs, the transition table limit and stale idle tasks.

## [3.17.11] - 2026-10-21

- Fix for #167. The agent desktop's top-level `stage-control` transition went past AppArmor's per-profile limit on named transitions ("too many specified profile transitions"). The AppArmor reload failed and the kernel kept the previous agent-desktop policy. The transition is removed.

## [3.17.10] - 2026-10-21

- AppArmor learning noise, round 2, from the largest live sources:
  - Bladebro's root-owned wrapper scripts may execute. Read-only rules had sent `bladebro-env` → `bash` → `bladebro-gate` → `bladebro` into ruleless `null-*` profiles.
  - The agent desktop's top profile enters `stage-control`'s own child.
  - Sonarr and Radarr may lock `/proc/<pid>/mounts`.
  - Their ffprobe children may read zoneinfo.

## [3.17.9] - 2026-10-21

- The kernel dropped 185 audit records at 05:37 UTC (`AuditRecordsLost`). OrcaSlicer, started in an agent-desktop app session, spawned WebKitGTK helpers and `ldd` ran the loader, all without AppArmor rules. In ruleless `null-*` profiles they logged about 74k records a minute and overflowed the 8192-record backlog.
  - The agent desktop's `desktop` child now allows the two WebKit helpers and the loader; it already runs any `/usr/bin` program.
  - PulseAudio may re-execute itself.
  - The kernel audit backlog rises to 32768.

## [3.17.8] - 2026-10-21

- Falco and audit tuning for three agent-desktop image behaviours, each investigated as a legitimate workload (#102). These are narrow exceptions keyed on container name prefix, executable and exact command line; every other sudoers read or ptrace in those containers still alerts.
  - `init-selkies-config` restores `NOPASSWD` in `/etc/sudoers` at every start.
  - `selkies-proot check` runs `proot -0 /bin/true`, which ptraces its child.
  - Chrome's crashpad handler attaches to Chrome. It is also excluded from `AuditKernelChange` (`ptrace_attach`).

## [3.17.7] - 2026-10-21

- SIEM redaction covers every string field at any depth, not just the message and request path (#102 Gate 1.5). Falco command lines and output fields, audit names and future sources are included.
  - New patterns: Authorization, cookie and API-key headers; JWTs; `--password`-style arguments; MySQL/MariaDB `-p<password>` (romm-db's poststart passed one); private-key blocks.
  - Detection text such as `find -perm` is kept.
  - Two new Vector tests cover this.

## [3.17.6] - 2026-10-21

- Agent desktop: whole Chrome windows. `stage-control` (replacing `stage-input`) gives every Chrome window in a browser stage a headless output of its own, so the viewer shows the whole window (tab strip, address bar, toolbar, extension buttons, menus and popups) and a person's taps, keys and text reach Chrome's own controls. Agents get the same through `browser_window` `screenshot`/`ui` (ghostship-agent 0.31.0).
- Browser controls take a focus lease on one window: focus moves only between that window and an empty `idle` workspace, new windows map on a hidden workspace and never take focus, and other windows are never activated or deactivated. Measured: 4,000 concurrent agent input operations (8 agents) with zero cross-talk, and 4,000 more while a lease loop opened Chrome's menu and typed in another window throughout, as on the previous stage.
- Stage windows now tile at the same fixed 1600x900 (workspace gaps) on outputs side by side in the lowest free slot, like a person's monitors; Chrome sees one screen per open window, and every window gets frames (overlapping outputs would starve all but one). The fingerprint matches the baseline except the window-frame inset (`outerMinusInner`, now that of a tiled window). The update service's fingerprint baseline is re-recorded on the next run.
- Sway windows are paired with Chrome window ids (home-tab title, unique tab titles, elimination; sticky; ambiguous windows stay unpaired), so a run only ever shows its own windows. The viewer's new sessions wait for that pairing before opening their working tab, so two runs on the same site are told apart.

## [3.17.5] - 2026-10-21

- The SIEM watchdog reads the oldest journal entry with `journalctl -n +1`. Its unit has no shell on PATH, so the `sh -c ... | head -1` pipeline from #161 failed and `siem-pipeline.prom` was never written.

## [3.17.4] - 2026-10-21

- SIEM loss visibility (#102 Gate 1.4).
  - The watchdog publishes kernel audit lost and backlog, journal retention and VictoriaLogs ingestion lag (`siem-pipeline.prom`).
  - New rules: `AuditRecordsLost`, `JournalRetentionShort` (< 6 h), `LogIngestionLag` (> 10 min), `VectorBufferFilling` (> 1 GiB) and `PipelineMetricsStale`.
- The journal cap rises from 1 GiB to 4 GiB. It is the buffer upstream of Vector, and during the 2026-10-21 AppArmor flood it held only about 3 hours, so a longer collector or store outage would have lost events.

## [3.17.3] - 2026-10-21

- SIEM pipeline liveness (#102 Gate 1.2).
  - `ghostship-siem-alerts` now publishes `siem-bridge.prom`: last poll, per-source last success, per-channel last delivery and failure counts, retry queue, T3 pending and dead letters. Firing alerts undelivered for 24 h become dead letters, listed by `--list` and never dropped.
  - A new independent root timer, `ghostship-siem-watchdog` (every 2 minutes), alerts on any of these:
    - a stalled bridge;
    - an unreadable vmalert source;
    - repeated delivery failures;
    - dead letters;
    - a vmalert or store API that stops answering;
    - a stale container snapshot.
  - Each watchdog problem opens one episode: ntfy `security` at priority 5 plus a single T3 incident through `ghostship-notify --incident`, which still reaches T3 when ntfy is down. The publish retries until ntfy accepts, and one resolution follows.

## [3.17.2] - 2026-10-21

- SIEM: no long-lived collector holds the rootful Podman API.
  - `ghostship-siem-alerts` and `ghostship-container-metrics` read `/run/podman/podman.sock` directly. Root needs no capability to use that socket, which can create and exec containers.
  - A short-lived root job, `ghostship-podman-snapshot` (every 30 s), now writes a metadata-only snapshot and the container counters, replacing the container-metrics daemon.
  - The bridge resolves ntfy and T3 from that snapshot, refuses one older than 5 minutes, and runs with `/run/podman` inaccessible.
  - `ContainerSnapshotStale` alerts if the job stops.
- Container network bytes are counted once per network namespace. qBittorrent, which shares Gluetun's namespace, was double-counted. Members now get `ghostship_container_netns_shared`.

## [3.17.1] - 2026-10-21

- SIEM alerts reach ntfy. `ghostship-notify` found ntfy by running `podman inspect`, which fails in the bridge's capability-free sandbox. Since #156 every ntfy publish from the bridge failed; T3 delivery was unaffected. The bridge now resolves ntfy through the Podman API socket and passes `GHOSTSHIP_NOTIFY_URL`.
- A failed ntfy publish is retried on the next poll. Previously it was recorded as sent and stayed quiet for the 6-hour renotify window.

## [3.17.0] - 2026-10-21

- SIEM part 2: detections and alerting (docs/siem.md).
  - Two vmalert v1.154.1 containers evaluate `siem/rules/logs.yml` (LogsQL) and `siem/rules/metrics.yml` (MetricsQL), with no notifier of their own. They share one strict complain-mode AppArmor profile; the registry gains a `source` option for shared profile files.
  - Log detections:
    - AppArmor denials in Plex's enforced domains;
    - shells, downloaders and interpreters executed by app server domains;
    - Falco critical and warning alerts;
    - Plex2Shell-surface requests from the WAN, and Plex preference writes;
    - exploit patterns against Muximux;
    - SSH authentication-failure bursts and firewall refusal bursts;
    - sensitive file changes outside NixOS activation;
    - kernel module loads, kexec and ptrace attaches;
    - silent journal or Plex ingestion.
  - Metric detections: sustained container CPU (miners), container egress spikes (proxies, exfiltration), SIEM components down, stale host or container metrics, Vector errors, low disk.
  - `ghostship-siem-alerts` polls vmalert on loopback. It publishes new and resolved alerts to ntfy `security`, and batches high and critical alerts into one message to the security campaign thread: at most one every 10 minutes and 12 a day, with a stable command id. Labels are sanitized, and the message frames alert text as untrusted data. `--list` shows current alerts. Its own T3 session token is issued daily.
  - NixOS activation's store Perl reading `/etc/shadow` and rewriting `/etc` is excluded, narrowly, from the Falco and audit detections. It was seen on every deployment today.
  - `scripts/check` validates both rule files with `vmalert -dryRun` and runs the bridge's tests (sanitizing, dedupe, resolution, rate limits, suppression expiry).
  - Falco, Vector, node_exporter and the SIEM network units now report failures through `ghostship-failure@`.

## [3.16.2] - 2026-10-21

- SIEM container metrics move to `/var/lib/ghostship-container-metrics`. node_exporter could not traverse the root-only `/var/lib/ghostship-siem` (`node_textfile_scrape_error 1`), so the counters written there never reached VictoriaMetrics.

## [3.16.1] - 2026-10-21

- SIEM container metrics read the Podman REST API over its socket. `podman ps` failed under the collector's read-only sandbox (it takes lock files), so no per-container counters reached VictoriaMetrics after #153.
- Falco alerts carry the container plugin's fields (container id, name, image) again (`append_output`); the minimal configuration had dropped them.

## [3.16.0] - 2026-10-21

- Security monitoring (SIEM), part 1: collection and storage (docs/siem.md).
  - VictoriaLogs v1.53.0 and VictoriaMetrics v1.154.1 run in Podman, pinned by digest, on their own network (`ghostship_siem_net`). Every connection they open is dropped except DNS, and their ports are published on 127.0.0.1 only. Each has a strict complain-mode AppArmor profile, a read-only image, no capabilities and noexec storage. nixpkgs' VictoriaLogs 1.52.0 can panic or drop logs, so it is not used.
  - Vector (native, no root) ships the whole journal, Plex's log and Muximux's nginx logs. It parses AppArmor and audit fields, Falco alerts and Plex and nginx requests, and redacts tokens, keys, passwords and URL credentials before storage. `tests/siem-vector.toml` runs in `scripts/check` and fails if redaction or parsing regresses.
  - node_exporter and a per-container counter service (CPU, memory, processes, network bytes) feed VictoriaMetrics, so a cryptominer or proxy shows up in the numbers.
  - Falco 0.45.1 runs natively on the modern eBPF probe, with the container plugin, packaged from the upstream release with pinned hashes. A trial on the host flagged a planted `/etc/shadow` read in a container.
- New intrusion-relevant log sources:
  - Audit rules watch identity files, sudoers, SSH configuration and keys, runtime systemd units, the system profile, kernel module loads, kexec and ptrace attaches.
  - The firewall logs refused connections.
  - Plex logs every request with the client and its network class (`logDebug`; Plex strips tokens).
  - The audit backlog rises from 1024 to 8192, matching auditd.

## [3.15.175] - 2026-10-21

- Plex2Shell (CVE-2026-96652/4/5/6, exploited since 2026-10-17): Plex already ran 1.43.5.11029, past the 1.43.3.10861 fix, with no indicators of compromise. Its Internet-facing AppArmor domains (server, interpreter, ldconfig) now **enforce**; startup and the healthcheck keep learning.
  - The interpreter rules were pinned to the 1.43.4 `Plug-ins-e5521bd8c` directory and would have blocked every metadata agent on 1.43.5. The build hash is now a glob, and the shipped agents' code and per-identifier state are allowed.
  - The server may not write or link into the allowlisted codec sets, the step Plex2Shell used to load its payload.
  - Observed benign server reads are allowed: DMI board names, `/proc/*/cmdline`, interface and route tables, CPU frequency limits, the bundled library directory and `/dev/shm` links.
  - The AppArmor collector checks each label's own mode (`apparmorProcessModes`), so a domain loaded in the wrong mode is reported.
- eMudhra intermediate key compromise: the host distrusts emSign ECC Root CA - G3 and Comodo AAA Services root (`security.pki.caCertificateBlacklist`). Every third-party container gets the host bundle and blanked copies of both roots, `SSL_CERT_FILE` and `REQUESTS_CA_BUNDLE`; the Node images use OpenSSL's store, and Plex's bundled `cacert.pem` is replaced. Throwaway copies of the Plex, Sonarr, Bazarr and Uptime Kuma images rejected the compromised test chains with these mounts and still reached plex.tv. Host services in the private integrations use the host bundle.

## [3.15.174] - 2026-10-21

- The read-only images without s6 also get a noexec `/run`: Chaptarr, cloudflared, the Grimmory database, Homepage, ntfy, Plex Auto Languages, Recyclarr, Seerr and Uptime Kuma. Throwaway copies of each image started cleanly with it. Their whole filesystem now has no writable, executable path.
- Plex Auto Languages' image-declared `/logs` anonymous volume is replaced by a noexec host directory.

## [3.15.173] - 2026-10-21

- AppArmor learning noise, from the largest live complain-mode sources: Sway's keymap reads of `xkeyboard-config-2` (about 9k a minute), RomM Valkey reading its own `/proc/<pid>/stat`, FlareSolverr's healthcheck curl starting from the top profile, and Gluetun's healthcheck loading the system CA roots. Each rule is limited to the observed path.

## [3.15.172] - 2026-10-21

- AppArmor: the agent desktop's top profile may run `s6-envuidgid`. Every s6 service that drops to `abc` runs `s6-setuidgid`, which calls `s6-envuidgid`. Without the rule, the LXQt desktop, D-Bus, PulseAudio, Selkies, Pelorus and the Chrome idle reaper all ran in ruleless `null-*` learning profiles. That logged about 175k audit records a minute, rotated auditd's logs in minutes and crowded the rest of the journal out. The same rule is added to the other LinuxServer profiles that allow `s6-applyuidgid`.

## [3.15.171] - 2026-10-20

- Agent viewer: one launcher. **Apps** has a tile for Chrome · Personal, Chrome · Agent, OrcaSlicer and Blender (from `apps.json`), and **Open** lists everything running. The mode switch reads **Apps | Desktop**.
- **×** closes at once without a confirmation: the tab disappears immediately, and an app is asked to quit every 2 s (so a dialog on top cannot hold it open) and stopped after 10 s. Agents' `close` still never discards unsaved work without `--force`.
- Blender 5.0 is installed and launches in its own app session.

## [3.15.170] - 2026-10-20

- Agent desktop: desktop app sessions. OrcaSlicer (and later other catalog apps, `apps.json`) runs on its own headless Sway screen with its own pointer and keyboard, opened from the viewer's new **Apps** launcher or by agents through `ghostship-gui app` (ghostship-agent 0.30.0). Each session is a viewer tab with a live view; touch pauses agent input, and closing never discards unsaved work without force. A 10,000+-keystroke concurrency gate across two sessions had zero cross-talk. Orca works again: the image now has WebKitGTK 4.1, and GTK image loading no longer aborts in the container (bwrap stand-in).
- Pin ghostship-agent 0.30.0: `ghostship-gui app` drives app sessions.
- `desktop.ghostship.io` serves the viewer at the root (no redirect); Selkies moved to `/desktop/` and the old `/agents/` address redirects to `/`. The main page groups **Apps** and **Browser sessions**; the health check and the update service's viewer gate follow the new paths.

## [3.15.169] - 2026-10-20

- Gluetun keeps a writable image filesystem. It creates its user in `/etc/passwd` at every start, so with `--read-only` (#145) it failed with "read-only file system", and qBittorrent, which shares its network, went down with it.

## [3.15.168] - 2026-10-20

- 17 containers run with a read-only image filesystem (`--read-only`), so a compromise cannot replace image binaries or plant code in the image: Bazarr, Chaptarr, cloudflared, Gluetun, the Grimmory database, Homepage, ntfy, NZBGet, Plex Auto Languages, Prowlarr, Radarr, Recyclarr, the RomM database, Seerr, Sonarr, Tautulli and Uptime Kuma.
  - **Selection:** each container's overlay upper layer showed it writes only Podman's passwd/group entries and its mount points.
  - **Testing:** throwaway read-only copies of eight images started cleanly.
  - **Still writable, with the reason** (recorded in `container-hardening.nix`):
    - FlareSolverr patches `/app/chromedriver`.
    - Muximux, pyLoad and qBittorrent run root init.
    - Tdarr writes `/app` assets.
    - Grimmory's root entrypoint rewrites `/etc/passwd`.
    - RomM templates `/etc/nginx/conf.d`.

## [3.15.167] - 2026-10-20

- Fixed the outage from #143. LinuxServer images started as the app user (Sonarr, Radarr, Prowlarr, Bazarr, NZBGet, Tautulli and the RomM database) run s6 preinit through the setuid-root `s6-overlay-suexec`. With every capability dropped it failed with "unable to setgid to root", and those containers (and RomM, which depends on its database) crash-looped. They now keep the LinuxServer startup set: chown, dac_override, fowner, kill, setgid, setuid.

## [3.15.166] - 2026-10-20

- Kernel-enforced execution limits for containers (`container-hardening.nix`), so a compromised app can't run code it writes. AppArmor is still learning in complain mode and blocks nothing.
  - **Data volumes:** every writable data volume is mounted `noexec,nosuid,nodev`. That covers configs, media, downloads, databases and state for all containers except Plex, the agent desktop and T3.
  - **Temporary storage:** `/tmp` and `/var/tmp` are size-capped `noexec,nosuid,nodev` tmpfs. RomM gets a disk-backed noexec `/tmp` for multi-GB uploads. Grimmory keeps an executable `/tmp` because pdfium4j maps `libpdfium.so` from there.
  - **Capabilities:** every container drops ALL and adds back only what its strict profile lists. Most get none; root-started LinuxServer images keep chown, dac_override, fowner, kill, setgid and setuid; Gluetun keeps net_admin and net_bind_service. So a setuid binary in an image can't regain capabilities.
  - **Why the exceptions:** a live scan found code executing from writable paths only in Plex's downloaded codecs, Grimmory's `/tmp` pdfium and the agent desktop's OrcaSlicer. Plex and the agent desktop follow separately.
  - **Impact:** NZBGet's `/scripts` is now noexec. No extension is configured; enabling one later needs an explicit exception.

## [3.15.165] - 2026-10-20

- Agent desktop AppArmor: the Chrome launchers may execute `with-contenv`, `s6-envuidgid`, `s6-applyuidgid`, and the root-owned `run-chrome`, `chrome-close` and `ghostship-chrome-instance` scripts. Before, these were read-only, so agent Chrome and its subtree ran in ruleless `null-*` learning profiles (about 100k events a minute).

## [3.15.164] - 2026-10-20

- AppArmor fixes from the first deploy of the strict profiles (#140). In complain mode an exec with no matching rule enters an empty `null-<path>` learning profile, and its whole subtree then runs ruleless.
  - Inside a child profile, `cx -> name` names a child of that child, not a sibling. So FlareSolverr's and Tdarr's sibling transitions now use `px -> ghostship-<container>//<name>`.
  - Tdarr's startup gets `s6-envuidgid`.
  - Grimmory's JVM may re-exec `java`.

## [3.15.163] - 2026-10-20

- Every container except T3 now has its own strict AppArmor profile in complain mode (user direction: no broad policy).
  - Covered: the arrs, downloaders, Gluetun, cloudflared, the web apps, the databases, Tdarr, FlareSolverr, the internal services and the agent desktop.
  - Each profile lists exact executables, libraries, data paths, network families and capabilities, with child profiles for daemons, interpreters, helpers and healthchecks. Policies live in `modules/self-hosted/apparmor/<container>.profile`.
  - The agent desktop is split into per-process children (Chrome per identity, Sway, sshd, Selkies, Pelorus, API, agent shells). The viewer profile is unchanged.
- `ghostship-container-default` now grants nothing and logs everything. Only ad-hoc job containers use it. An assertion requires every declared container except T3 to have its own profile.
- `ghostship-apparmor-review` tracks every container. Each app declares the labels it expects (`apparmorProcessProfiles`, `apparmorRequiredProcessProfiles`). Images without `cat` give the audit heartbeat their own reader (`apparmorHeartbeat`).
- `ghostship-apparmor-review` reads the journal once per collection, not once per container, with a 10-minute bound.
- The kernel audit backlog is raised to 8192 records (`ghostship-audit-backlog`), so complain-mode bursts at container start aren't dropped. Dropped records would reset every learning window.
- Containers running with no_new_privs (GitHub coordinator, private integrations) get flat profiles. Under no_new_privs AppArmor never enters child profiles; complain mode logs "no new privs", and enforce mode would refuse the exec.
- Documented that a reloaded policy reaches an idle task only at its next mediated call. This is why Plex's `ptrace readby` events continue until Plex restarts.

## [3.15.162] - 2026-10-20

- Agent viewer: closing a session also closes tabs and popups the agent opened while the close waited for its in-flight call, and a manual scroll of the session strip no longer snaps back on each refresh (Codex review of #138).

## [3.15.161] - 2026-10-20

- Agent viewer: every open session is a tab along the top (identity dot, label, × to close) instead of ‹ › stepping, and **+** opens a Personal or Agent window from there. Closing pauses the session, waits for an in-flight agent call, then closes its tabs (home last) and removes its registry entry; closing an agent's session asks first. Cards in the grid have a Close button too.

## [3.15.160] - 2026-10-20

- Agent viewer: the address bar accepts a bare host such as `amazon.com` (it was a `type=url` field, so the browser demanded a scheme before the viewer could add `https://`).

## [3.15.159] - 2026-10-20

- Agent desktop: one web UI. `desktop.ghostship.io` opens the viewer with a **Browsers | Desktop** switch; Desktop mode embeds Selkies, which nginx still serves at `/` to frames and health checks, and leaving it ends the stream. nginx redirects are now relative: `/agents` no longer redirects to `http://desktop.ghostship.io:3000/agents/`.

## [3.15.158] - 2026-10-20

- Every AppArmor profile now runs in complain (learning) mode: `ghostship-container-default` (the 25 containers without their own profile), `ghostship-agent-desktop` and `ghostship-desktop-viewer` move from enforce. Explicit `deny` rules still apply in complain mode, so Podman's baseline denials (mount, `/proc` and `/sys` writes, kernel security files) and the viewer's denials of Chrome profiles, SSH keys and container secrets stay in force. Per-service strict profiles replace the shared default next (#102).

## [3.15.157] - 2026-10-20

- Agent viewer: **+ Personal** / **+ Agent** start an idle-stopped Chrome (through `chrome-ensure`) instead of failing with "browser stopped". The viewer's AppArmor profile may run only `chrome-ensure`, under the container profile with a scrubbed environment.

## [3.15.156] - 2026-10-20

- `ghostship-apparmor-review` identifies a policy by its own file's content hash, not by its path in the combined `apparmor.d` tree. Adding the agent-desktop profile (#130) renamed that tree, so every other profile reported `configuration-mismatch`, and the next collection would have reset their learning windows despite byte-identical policies. Includes are embedded by content-addressed store path, so real include changes still count. Plex's process labels now allow `ghostship-plex//healthcheck`, so a scan that coincides with a healthcheck no longer fails `process-profile-mismatch`.

## [3.15.155] - 2026-10-20

- Agent desktop: BladeBro 4.2.2 -> 4.6.4 (canary-tested by ghostship-agent-desktop-update).

## [3.15.154] - 2026-10-20

- Fixed `ghostship-agent-desktop-update` canaries: the update service now uses the host's configured podman. The plain package refused the canary's AppArmor profile ("AppArmor is not enabled"), so every candidate failed before testing.

## [3.15.153] - 2026-10-20

- Pin ghostship-agent 0.29.0: browser agents drive their own windows in the browser stages without the desktop input lock or tab activation, publish run records (label, harness, model, T3 thread) for the agent viewer, and stop on `paused` when a person takes over a window.

## [3.15.152] - 2026-10-20

- Concurrent agents on one signed-in Chrome. Each identity's Chrome now runs in its own browser stage: a Sway compositor with a virtual 1920x1080 output, virtual mouse and keyboard, and no automatic focus changes. Agents drive their own windows with target-scoped input, never stealing focus from each other or from a person on the desktop. Measured: 30,000+ barrier-synchronised ops at 8 and 16 agents, and a 2 h soak, with zero cross-talk. Browser fingerprint, CDP detection and bot-check results match the previous desktop. Logins stay in one authoritative profile per identity, with no replication.
- Agent viewer at `https://desktop.ghostship.io/agents/`: mobile-first cards per agent window (label, identity, harness/model, T3 thread, current action, live preview). Tapping a card opens that agent's live view; any touch pauses only that agent (`bladebro-gate` refuses its page-changing calls) until Resume. It verifies the Cloudflare Access token on every request and runs under a new enforce-mode AppArmor profile (`ghostship-desktop-viewer`). The desktop now resizes to the client's screen.
- Browser sessions survive restarts: Chrome is closed through DevTools before the container stops (it previously lost cookies written in its last ~30 s).
- Automatic desktop updates: `ghostship-agent-desktop-update` gates signed Chrome stable, checksummed Bladebro and the webtop digest in lab canaries (concurrency, CDP detection, bot checks, fingerprint parity, profile compatibility on network-less snapshot copies). It then commits `containers/agent-desktop/versions.json`, drains, snapshots, deploys and verifies, rolling back with profile restore on failure, and reports to NTFY. Retailer sites are never part of automated tests.

## [3.15.153] - 2026-10-20

- Stop the inference scheduler by signalling its container process and waiting for the scheduler and its Podman attachment to exit. Orderly configuration switches no longer kill the attachment and report a false service failure; genuine nonzero scheduler exits still fail. Shutdown uses pinned process identities and leaves unrelated container processes alone.

## [3.15.152] - 2026-10-20

- Allow the private integrations container 110 seconds to stop, covering its supervisor's 100-second worker drain and descendant reaping. Allow systemd 130 seconds for the stop and cleanup. Podman's default 10-second timeout could kill the supervisor during a deployment and report exit 137.

## [3.15.151] - 2026-10-20

- Pin ghostship-agent 0.28.0 at `ea17d445` (MCP connector review). `t3_task` op `submit` now accepts the model options that `t3` op `capabilities` lists, for example `{"effort": "high"}`, plus a `runtime_mode`. It checks both against the live catalog and reports the selection it used and the thread `url`, falling back to a deep link if the link lookup fails. Capabilities lists options compactly and can be filtered by `instance_id`. Errors for invalid arguments now name the argument and the limit it broke. Filesystem denials list the allowed roots and the container paths that map into them. `browser_op` `extract` accepts a `selector` and fails when given neither `js` nor `selector`, instead of returning null. Only the `ghostship-private-integrations` MCP runtime changes behavior.

## [3.15.150] - 2026-10-20

- `ghostship-apparmor-review` can review the learning ledger by group. `--summary` lists unreviewed events grouped by their kept fields, with digits normalized and hex `comm` decoded. `--container NAME --match FIELD=GLOB` classifies every matching event in one locked write; profile and operation matches are required. The new `resolved-by-policy` classification, whose note must cite a PR, clears legitimate events a deployed policy now covers. Before this, only `expected-denial` cleared an event, so fixed events blocked enforcement forever, and reviewing 126k Plex events one ID at a time rewrote a 48 MB ledger on every call. Events now keep the AppArmor `peer`, so ptrace and signal records are distinguishable.

## [3.15.149] - 2026-10-20

- Failed services start T3 repairs. `ghostship-failure@` alerts now also go into a root-owned incident spool. The GitHub coordinator (ghostship-agent 0.28.0) turns each one into a T3 thread that diagnoses the failure on the host, fixes the cause through a PR and deploys it, and leaves `t3code` alone. A repeat failure messages the same thread, and at most 3 incident threads start per day; past that, the alert goes to a human on `operations`. Incident details never reach GitHub.
- Update notices: a nightly `nixos-upgrade` that changes the running system posts the new release to `informational`. Container auto-updates post the list of updated containers there too, and the run fails, raising an incident, when a container update fails or rolls back. The maintenance lock is now taken inside the update runner.
- Removed the Uptime Kuma HTTP monitor for the webhook receiver. Kuma can't reach the receiver's internal network, so the monitor failed every minute. The receiver's container heartbeat still covers it.
- Fixed `ghostship-desktop-bridge.timer` and `agent-desktop-mcp.timer`. Their `OnUnitActiveSec=daily` was invalid and ignored by systemd, so they now use `1d`.

## [3.15.148] - 2026-10-20

- Enable source-preserving EPUB imports through Ghostship's filesystem service: allow the existing Books library root and check Grimmory access with its configured application uid/gid. Pin the agent release with bounded EPUB inspection, collision-safe copy and the Grimmory scan/read-back workflow.
- Run the unprivileged Books EPUB converter every five minutes, with network isolation and memory/CPU limits. It retains originals and publishes validated EPUBs beside stable imported files; MCP can queue the same fixed job and inspect its report. Chaptarr's completed-download path does not implement its conversion toggle.
- The pinned MCP also discovers active T3 threads and live model/harness availability, accepts canonical thread IDs, and sends updates to existing running threads.

## [3.15.147] - 2026-10-20

- Pin ghostship-agent 0.27.2 (`de0f9588`): the GitHub coordinator routes a base-branch CI failure to the T3 thread whose merged pull request produced the failing commit (the regression issue is filed owned by that thread and the thread is messaged) instead of launching a new thread; unowned failures launch as before. Only `ghostship-github-coordinator` changes behavior.

## [3.15.146] - 2026-10-20

- `ghostship-apparmor-review` reads only AppArmor audit records (type 1400 and 1501–1507), kernel messages and journald rate-limit notices. Its daily read had covered every audit record, 1.28M lines (1.5 GB) taking 39s, past a 20s timeout. That marked every profile `audit-collection-failed` and reset each learning window daily. The read now takes about 10s, with a 120s limit, and the unit gets 15 minutes. Audit loss now matches only `audit`/`apparmor` rate-limit lines, not unrelated kernel ones such as NFS `rpc_check_timeout: N callbacks suppressed`.
- Plex profile (complain): Podman's `curl` healthcheck gets a `healthcheck` child profile with its exact libraries, resolver/TLS files and TCP. Under enforcement it would otherwise be denied, and `--health-on-failure=kill` would kill Plex. Before this, each run logged about 100 records under a null profile, about 12k an hour. The `PMS GTP` thread may `ptrace` read its own `//server` peer, to read its processes' /proc entries (no tracing).

## [3.15.145] - 2026-10-20

- Pin ghostship-agent 0.27.1 (`e0213afd`): fixes the `printing-press.sh` quoting regression from 0.27.0 that left `ghostship-inference-scheduler` crash-looping after 3.15.144.

## [3.15.144] - 2026-10-20

- Pin ghostship-agent 0.27.0 (`2b64a6d8`): skill families collapse into routers with linked guides, so 44 installed skills become 12 and the ChatGPT GhostShip Skills plugin goes from 26 skills to 5. `ghostship-skills-reconcile` installs the T3 set (pruning the retired links) and republishes the plugin. The MCP instructions now point shopping at the `shopping` skill, so the ChatGPT connector is refreshed after the switch.

## [3.15.143] - 2026-10-20

- `ghostship-cloudflare-sync` retries Cloudflare reads twice (after 5s and 20s) on HTTP 429, 5xx and network errors. A single HTTP 504 at 04:25 UTC failed the sync during the nightly `nixos-upgrade` activation, which marked the whole upgrade failed (status 4) and sent a failure notification. Writes and other client errors still fail immediately, so a write is never sent twice.

## [3.15.142] - 2026-10-20

- The host firewall accepts DNS from the internal `ghostship_github_net` (10.89.9.0/24) to its own aardvark-dns at 10.89.9.1, and nothing else. Netavark adds no DNS input rule for internal networks, so `ghostship-hooks` had no working resolver and cloudflared's second nameserver timed out on about a fifth of its queries; the flow observer recorded these as dropped. Aardvark never forwards an internal network's queries upstream, so the network still has no egress.

## [3.15.141] - 2026-10-19

- Pin ghostship-agent 0.26.0 (cba1ad46): the GitHub coordinator publishes T3 progress to `informational` (thread launched, PR opened and merged, issue closed) and base-branch regression issues to `operations` at priority 4, each once, without holding GitHub routing on an ntfy outage.

## [3.15.140] - 2026-10-19

- Notification coverage is declared once in `notify-coverage.nix`: every `ghostship-*` and `podman-*` service and a named list of other custom units report failures to `operations` through `ghostship-failure@`, which now names the unit's description, result and exit status. Previously 17 units had a failure path; the containers, brokers, bridges, network setup units and download helpers failed silently. Exemptions carry a reason, and evaluation fails when a covered unit loses its path or the module names a missing unit.
- Backup jobs post their restic summary lines silently to `informational` through the new `ghostship-success@`.
- New daily `ghostship-storage-check` alerts `operations` when the root filesystem is read-only or a Btrfs device error counter is nonzero.

## [3.15.139] - 2026-10-19

- `ghostship-synology-health` polls the Synology NAS every 10 minutes over SNMPv3 authPriv (SHA, AES) and publishes to the operations topic: system status, power and fan failures, system and disk temperature, disk status and health, degraded or crashed RAID, and `/volume*` usage at 85% and 95%. Each finding fires once, repeats daily while it persists and resolves when it clears; a failed poll raises its own alert and keeps the earlier ones active instead of resolving them. The SNMP user is the new `synology-snmp` secret unit (Bitwarden `chill-penguin/synology`); its passphrases reach net-snmp through a private `snmp.conf`, never the command line. The unit alerts through `ghostship-failure@`. Until SNMPv3 is enabled on DSM with those credentials, the poll alert fires daily.

## [3.15.138] - 2026-10-19

- Recorded the user's decision that Plex's router forward is manual, with UPnP and NAT-PMP declined. The public-service policy notes that Plex stays on manual port mapping, and that its NAT-PMP requests to the bridge gateway stay dropped. Verified: the host firewall already drops UDP 5351 from the container bridge, and SSDP does not leave the bridge.

## [3.15.137] - 2026-10-19

- Flow verdicts compare accepted connections against a new per-edge `checked` count: the connections collected while the accepted sets were loaded. Comparing against the full `connections` history left every edge recorded before 3.15.136 stuck at `partial` or `unknown`. Existing edges restart their verdict counts once; a collection missing the accepted sets does not add to `checked`.

## [3.15.136] - 2026-10-19

- The flow observer records verdicts. Accepted-connection sets at priority +20 on the inet forward/input and bridge forward hooks sit after every host filter, so each edge now carries an `accepted` count beside `connections`. `ghostship-flow-report` labels edges `accepted`, `dropped`, `partial`, or `unknown` for edges recorded before this change. Unsolicited WAN probes and blocked attempts can now be told apart from real paths when the allow graph is derived.

## [3.15.135] - 2026-10-19

- `ghostship-security-check` keeps the addresses of host SSH clients (T3, the tunnel connector) allowed for a day after they change. Logins read from the journal can predate T3's recreation, and checking them only against its new addresses produced a critical alert after each idle redeploy.

## [3.15.134] - 2026-10-19

- The GitHub coordinator joins its own `ghostship-github` group as well as the spool group, so it can read its T3 session token. Without it, issue launches retried with "t3 executable not found".

## [3.15.133] - 2026-10-19

- Keep the webhook spool and coordinator state under `/var/lib/ghostship-github`. systemd-tmpfiles refused to create root-owned directories under the `apps`-owned `/srv/apps`, so the receiver and coordinator could not start on 3.15.132.

## [3.15.132] - 2026-10-19

- Add `hooks.ghostship.io`, the webhook receiver for GitHub-driven T3 engineering and Cloudflare alerts (ghostship-agent 0.25.0, pinned at `d61a5415`):
  - Cloudflare Access bypasses exactly `POST /github` and `POST /cloudflare` (the owner 2026-10-19, recorded as `cloudflareBypassApproval`); every other path still requires Google identity. The receiver verifies GitHub's HMAC signature or the Cloudflare webhook secret itself, runs AppArmor-confined in complain mode, and shares an internal network only with cloudflared. It has no egress.
  - The registry gains `cloudflareBypassPaths`, which requires an approval and an AppArmor profile. `ghostship-cloudflare-sync` accepts a path-scoped Access app only when every domain is an approved exact path and the app's only policy is bypass-everyone.
  - The coordinator re-reads each GitHub event from GitHub and routes your issues, comments, reviews and PRs to one T3 thread per issue. It files regression issues for failing base-branch CI and publishes Cloudflare alerts to ntfy.
  - New encrypted unit `hooks` (`GITHUB_WEBHOOK_SECRET`, `CLOUDFLARE_WEBHOOK_SECRET`; copy in Bitwarden `hooks.ghostship.io`).

## [3.15.131] - 2026-10-19

- The flow collector remembers each container's addresses for a day, so connections recorded before Podman recreated a container (and gave it a new address) keep the container's name instead of `lan:<address>`. A reused address always belongs to its current owner.
- `ghostship-flow-report` accepts report options without the `report` subcommand, e.g. `ghostship-flow-report --json --since-hours 6`.

## [3.15.130] - 2026-10-19

- `ghostship-security-check` resolves the containers allowed to log in to host SSH (`host_ssh_clients`: T3 and the tunnel connector) to their current addresses on every run. Podman gave T3 new addresses when it was recreated, and the fixed list made every T3 login a critical alert. Repeated logins from one unexpected source collapse into one finding with a count.

## [3.15.129] - 2026-10-19

- Keep Podman containers confined across AppArmor reloads. Podman loads its own `containers-default-<version>` profile at runtime, and the `aa-remove-unknown` step of every NixOS AppArmor reload unloaded it, so each nightly switch left every container without its own profile unconfined. The same default rules are now declared as `ghostship-container-default` (enforce) and set as Podman's default profile, so reloads replace it instead. Container units without their own profile now also start after `apparmor.service`.
- `ghostship-security-check` compares every running container's live AppArmor label with its configured profile or the one Podman recorded, and flags containers created without a profile unless they are allowlisted privileged containers.
- Security alerts publish only through `ghostship-notify` from `config.ghostship.notify.package`; the `ghostship-alert` fallback is gone.

## [3.15.128] - 2026-10-19

- ntfy carries exactly three topics, `security`, `operations` and `informational`; `publisher` writes and `android` reads all three, and the host operations broker may publish to each.
- `ghostship-notify` replaces `ghostship-alert` as the host publisher: `--topic`, `--priority` (5 act now, 4 actionable, 3 today, 2 informational, 1 digest), `--source` and `--state` as the first two tags, optional `--dedupe` (one publish per key and state per hour, recorded only after a successful publish) and `--click`. Failed-unit notifications use it on `operations` at priority 4.

## [3.15.127] - 2026-10-19

- Add observe-only connection inventory for chill-penguin (issue #102). nftables flow sets on the inet forward/input and bridge forward hooks record each new connection's source, destination, protocol and port without returning verdicts, including attempts later dropped by the FlareSolverr egress rules. `ghostship-flow-collect` resolves addresses to container names every five minutes into a root-only edge map; `ghostship-flow-report` prints it. The map is the evidence base for the declarative allow graph.
- Add `ghostship-security-check`, run every 15 minutes:
  - Invariants alert immediately: AppArmor enabled, declared profiles loaded and attached to their containers, audit enabled with no lost events, expected firewall tables present. Also unexpected privileged containers, added capabilities, host sockets, host namespaces or undeclared containers.
  - Root SSH logins from unexpected sources and SSH failure bursts alert as one-off events.
  - Drift checks baseline first, then report new listeners, SSH key or sshd config changes, non-store unit or cron files, and new SUID/SGID files (scanned daily); `--accept` re-baselines after review.
  - Containers opening host SSH or another app's database are flagged from the flow map.
  - Alerts go to the `security` NTFY topic through `ghostship-notify` with dedupe keys and resolved notices, falling back to the existing operations alert until the NTFY topic rollout lands.

## [3.15.126] - 2026-10-19

- Start T3 Code tool maintenance within ten minutes of a new Codex, Claude, OpenCode or Grok release, using the npm registry check that drives T3's provider update notice. The existing idle and OpenCode process guards still apply.

## [3.15.125] - 2026-10-19

- Trim T3 Code's OpenCode model list: `t3code-opencode-model-catalog` rebuilds a models.dev catalog from OpenCode's cache at server start and every tool auto-update, keeping Ollama Cloud, OpenCode Go and OpenRouter models released in the last 183 days that support tool calls (OpenRouter free models only) plus the configured default and small models; other providers pass through. T3 Code's OpenCode reads it through `OPENCODE_MODELS_PATH`, because OpenCode 2 ignores provider whitelists. Today this lists 57 models instead of 446, so `orchestrator_capabilities` shrinks by about 120 KB. The free-inference pool's isolated OpenCode keeps the full catalog.
- Pin ghostship-agent f3f73aba (0.24.2): Ghostship MCP results for coding agents are bounded at 32 KB; ChatGPT keeps 96 KB.
- Stop registering direct `bladebro`/`bladebro-personal` MCP servers in every coding agent and remove the existing entries; their host-side wrapper paths never resolved inside the container, so every session failed to spawn them. Agents use Bladebro through the Ghostship browser tools; the SSH wrappers and pinned host key remain.

## [3.15.124] - 2026-10-19

- Add a Plex AppArmor profile in complain mode, separating startup utilities from the server domain and pinning executable/library paths to the inspected container.
- Include the AppArmor parser in Podman's wrapper so profile attachment works after the first AppArmor boot.
- Expose AppArmor tunables at their standard path so Podman's default profile compiles for other containers during a full system activation.
- Drain AppArmor learning events with auditd and bounded root-only log rotation, avoiding kernel printk suppression during startup bursts.
- Require declared Internet-facing apps to carry enabled AppArmor policies and recorded explicit approval for access outside Cloudflare Access. Attach profiles through Podman and fail startup when a profile is unavailable; isolate dynamic interpreters with minimal resource permissions.
- Revoke ntfy's native-auth Cloudflare Access bypass, require identity protection for explicit tunnel routes, reject unauthenticated preflight and unscoped service-token admission in both tunnel provisioners, and retain an additional ntfy AppArmor profile behind Access.
- Collect private daily audit evidence with confinement checks, an audit heartbeat, journal continuity checks, and a seven-day observation window that resets on policy/image/boot changes or telemetry gaps. Document daily review and the transition to enforcement.
## [3.15.123] - 2026-10-19

- Pin Ghostship Agent at `68d0549a` to expose NAS filesystem inspection and no-overwrite moves.
- Limit the broker to Downloads, TV and Movies on the NFS-mounted NAS; derive Sonarr, Radarr and Plex access-check identities from their container users.

## [3.15.122] - 2026-10-18

- Pin GhostShip Agent main at `81fb9234` (free inference 0.24.0, PR #28, and 0.24.1, PR #29: OpenRouter pin drift pause, probes prefer strict routes).
  - Gate request rewriting fixes Upstage and Cloudflare.
  - New free providers: Upstage, Inception, Poolside, OVH, plus Mistral on its Free plan. OrcaRouter is enabled.
  - Routing ignores where a model was developed and fails closed on unknown aggregator hosting. OpenRouter gets a hosting allowlist pin.
  - A new `light` workload admits weaker models.
- Pool accounts:
  - Add Upstage, Inception, Poolside, OVH (anonymous) and Z.ai; enable OrcaRouter; open Mistral to all workloads.
  - Billing attestations for Upstage, Mistral and Inception.
  - `china_hosting_workloads: ["research"]` on the aggregator and research accounts (the owner 2026-10-18: free research may include China providers; Singapore is fine).
- Project Z.ai's key (`ZHIPU_API_KEY`) from a new encrypted provider unit.

## [3.15.121] - 2026-10-18

- Free inference pool reads its credentials from a copy in the T3 container's tmpfs `/run` (`GHOSTSHIP_FREE_INFERENCE_PROJECTION`), refreshed by the bridge prepare step and a path unit whenever `/run/ghostship-secrets/t3code.env` changes. The container's single-file bind mount keeps the old inode after the projector's rename, so new provider keys stayed invisible without a T3 restart.

## [3.15.120] - 2026-10-18

- Pin Ghostship Agent main at `e714db00` to activate the lean engineering workflow, writing standard, manual pattern review and repository cleanup skills, with verified behavioral evaluation fixtures.

## [3.15.119] - 2026-10-18

- Pin GhostShip Agent main at `5c176689` (free inference pool as the first-class worker framework, PR #26): registry as data with live probes, bounded OpenCode agent jobs (request budgets, allowlisted fetch, confined sandbox), adaptive concurrency and client shares, admission benches, no China-hosted routes by default.
- Project the free-provider keys Kilo, Requesty, OrcaRouter, Inception, Mistral, Upstage and Poolside into `t3code.env` from new encrypted provider units.
- Pool: 8 workers (goship-research 0.7 / default 0.3), scheduled probes and admissions; un-suspend NVIDIA (research allowed) and Cloudflare Workers AI; Vercel free-only without `beam-free`; enable keyed Kilo and Requesty, and Mistral for evaluation.

## [3.15.118] - 2026-10-18

- Start the free inference bridge only after the T3 container's `t3code-container-setup` finishes: its boot-time `chown -R t3code:t3code ~/.local` reset the bridge socket and token to group `t3code` after the bridge set group 62020, so every MCP `inference_*` call returned "unavailable" after the 2026-10-17 container replacement.

## [3.15.117] - 2026-10-17

- Preserve existing research launchers on OpenCode 2 and provide an OpenCode-only activation command without restarting T3.
- Stage OpenCode 2 from its separate stable package in verified immutable releases, preserving the old executable on failure and requiring an explicit first database migration.
- Never trust the stale V1 database once T3 has migrated to V2; missing databases also block host deployment. V2 activity uses the `v2-sqlite` probe from 3.15.114.
- Add disposable-container release and database-migration smoke checks and a maintenance-only safety guard that preserves the active runtime.
- Stop projecting `OPENCODE_API_KEY`: OpenCode retired API keys, and the expired key shadowed OAuth logins and made Zen reject even free models.

## [3.15.116] - 2026-10-17

- Pin GhostShip Agent `main` at 0.22.1 (free inference pool and relay health
  merged; content identical to the previously deployed branch pin).

## [3.15.115] - 2026-10-17

- Fully retire CloakBrowser: quarantine `/srv/apps/cloakbrowser` profiles and
  extensions into `/srv/retired-apps` and remove the runtime masks that
  outlived its units.

## [3.15.114] - 2026-10-17

- Clear runtime drop-ins and shadowed runtime unit links of declared units on
  every full switch; a leftover targeted-activation drop-in kept rendering the
  ChatGPT relay with a removed MCP runtime path. Runtime masks stay.
- Detect T3 Code 2 activity from `statev2.sqlite` in the idle-deploy probe
  (open runs, subagents and launches, recent user messages and turn items), so
  queued T3 updates no longer need a disabling override or session guard.
- Pin GhostShip Agent 0.22.1: a crash-looping relay now marks the MCP
  container unhealthy and `integration_status` reports the relay state.

## [3.15.113] - 2026-10-16

- Keep scheduled T3 source sync on the host-projected managed installer so an
  older running image cannot reinstall an obsolete CLI or shared instructions.
- Share the existing guarded repository sync between future images and the
  session-safe service override; retain timer behavior and provider settings.

## [3.15.112] - 2026-10-16

- Allow selected private-file inference reviews in the approved Ghostship
  checkout and derive broker repository roots from the shared pool policy.
- Retain the public fixture and its repository-specific trusted test command.
- Keep Cohere request ceilings unchanged while allowing a documented internal
  500k-token daily ceiling and bounded 4096-token review output.
- Refresh the pinned managed CLI during inference activation while preserving
  provider configuration and global Git settings.

## [3.15.111] - 2026-10-16

- Pin the inference MCP response contract fix so live status, cancellation, and
  paged result responses reach clients after the durable broker operation.

## [3.15.110] - 2026-10-16

- Pin Ghostship Agent 0.22.0 and run separate supervised inference broker and
  scheduler processes in T3, with a dedicated encrypted token and a local Unix
  socket for the MCP.
- Persist the worker pool's provider policy and public synthetic fixture
  separately from the main OpenCode configuration.

## [3.15.109] - 2026-10-16

- Add encrypted inference provider bundles for Groq, Google AI Studio, NVIDIA,
  Hugging Face, Vercel AI Gateway, Cloudflare Workers AI, and Cohere, projecting
  their credentials into the T3 Code runtime environment.
- Keep the dedicated Workers AI token and account separate from Cloudflare's
  management credential bundle.

## [3.15.108] - 2026-10-16

- Pin GhostShip Agent 0.21.0: retailer skills and generic browser shopping, with Costco local warehouse inventory retained through the generic service executor.
- Retire the unused shopping overlay argument and preserve the active T3 session during activation.

## [3.15.107] - 2026-10-13

- Pin GhostShip Agent 0.20.1 for bounded shopping output, literal model matching, selected spool/variant evidence, Best Buy destination verification and read-only quantity promotion quotes.
- Preserve the active T3 session while activating the updated shopping runtime.

## [3.15.106] - 2026-10-13

- Pin GhostShip Agent 0.20.0 for exact-ASIN verification, bounded deep search, sampled price history, silent baselines and retailer cart contracts with explicit coverage gaps.
- Preserve active T3 sessions while activating the updated GhostShip runtime.

## [3.15.105] - 2026-10-13

- Keep T3 temporary checkouts on disk instead of Podman's systemd tmpfs, with a writable sticky directory and evaluated mount regression checks.
- Raise the shared memory reclaim threshold to 36 GiB, retaining the 40 GiB hard ceiling, to recover the existing RAM-backed temporary workload without restarting active sessions.

## [3.15.104] - 2026-10-13

- Contain combined T3 tool memory when anonymous allocations cause cgroup reclaim stalls, even when each tool is below 12 GiB. Protect the native T3 server behind its Node launcher and timestamp containment actions.
- Never restart T3 for memory pressure, including pressure-induced web timeouts. Memory measurements veto web recovery immediately, reset its failure streak, and are rechecked before recovery.
- Protect T3's launcher and native server from kernel OOM selection, keep tools eligible, and increase the shared reclaim/hard limits to 32/40 GiB on Chill Penguin's 64 GiB host.

## [3.15.103] - 2026-10-13

- Pin ghostship-agent 0.19.0: browser window leases lapse after 10 idle minutes and 2 hours in total, close when a coding-agent session ends, hold at most 6 tabs, sweep the popups their pages opened, and publish their expiry in the window's home tab.
- Agent Desktop: Chrome starts with no window (`--no-startup-window`), and the
  idle watcher runs `chrome-lease-reaper`, which closes windows whose
  `about:blank#ghostship-window-<token>.<expires>` lease expired more than
  `CHROME_LEASE_SLACK_SECONDS` (120) ago, with their popups.

## [3.15.102] - 2026-10-13

- Pin ghostship-agent 0.18.2: Wyze weigh-ins from the Wyze API (every weigh-in, true time zones, kg).
- New agenix unit `wyze` (`EMAIL`, `PASSWORD`, `KEY_ID`, `API_KEY`) projected to the MCP container as the `wyze` service credential.

## [3.15.101] - 2026-10-12

- Pin ghostship-agent 0.18.1: `health` op `types` and `query` over every Health Connect type, Ultrahuman lab biomarkers, full sleep and metrics, Wyze weigh-ins, and health documents with their text (OCR for scans).
- The MCP container reads health documents only from the owner's own Drive folders and the shared "HealthConnect" folder (`GHOSTSHIP_HEALTH_DOCUMENT_FOLDERS`).

## [3.15.100] - 2026-10-12

- Pin ghostship-agent 0.16.3 (AlohaQ skill removed).

## [3.15.99] - 2026-10-12

- Pin ghostship-agent 0.16.2: the ChatGPT skills plugin carries all 26 ChatGPT-capable skills.

## [3.15.98] - 2026-10-12

- Pin ghostship-agent 0.16.1 (cover display guidance).

## [3.15.97] - 2026-10-12

- Pin ghostship-agent 0.16.0: the listed tool surface is compressed to about 27 KB.

## [3.15.96] - 2026-10-12

- Pin ghostship-agent 0.15.1 (facade op descriptions).

## [3.15.95] - 2026-10-12

- Pin ghostship-agent 0.15.0:
  - results are trimmed and paginated instead of dropped;
  - services take sort/limit;
  - media records carry public cover URLs;
  - ChatGPT output alignment.

## [3.15.94] - 2026-10-12

- Pin ghostship-agent 0.14.1: `health` op `sources` passes the result contract.

## [3.15.93] - 2026-10-12

- Pin ghostship-agent 0.14.0 (`main` 25cab8c6): the `health` tool (Health Connect export, Ultrahuman, Wyze scale history) and the Ultrahuman and Wyze services.
- New agenix unit `ultrahuman` (`API_TOKEN`) projected to the MCP container as the `ultrahuman` service credential.

## [3.15.92] - 2026-10-12

- Pin ghostship-agent `main` acf76bd8. The unified platform line, with every release through 0.13.1, is merged into `main`.

## [3.15.91] - 2026-10-12

- Pin ghostship-agent 0.13.1:
  - pages settle adaptively after navigation;
  - the desktop lock is held only across a batch's native-input steps.

## [3.15.90] - 2026-10-12

- Pin ghostship-agent 0.13.0:
  - the MCP server lists 15 op-dispatch tools instead of 40;
  - the ChatGPT skills bundle adds `ghostship-services` and `ghostship-browser`.

## [3.15.89] - 2026-10-12

- Pin ghostship-agent 0.12.0, which adds read and write support for every service.
- The host operations broker allowlists the config files of Homepage, Muximux, Plex Auto Languages and Recyclarr for read and replace.
- Restic restores go to `/var/lib/ghostship-backup/restore`.

## [3.15.88] - 2026-10-12

- Pin ghostship-agent 0.11.0 (regenerated service clients, confirm gates, chill-penguin host service, ntfy message polling). The host operations broker reports disk usage for `/`, `/srv`, `/nix` and the NAS share.

## [3.15.87] - 2026-10-12

- Make the rendered Seerr executor credential group-readable (0440) so the MCP container can read it.

## [3.15.86] - 2026-10-12

- Pin ghostship-agent 0.10.0 (every service executable through `services_*`).
- Add `ghostship-hostops-broker`: the agent's allowlisted host operations broker, run as root and reachable only by the MCP container user over `/run/ghostship-hostops/ops.sock`, which is mounted read-only into the container. It drives:
  - container status, logs and restart for every OCI container, except restarting `t3code` and the MCP container;
  - MariaDB reads;
  - restic status, snapshots and runs;
  - Recyclarr sync;
  - Uptime Kuma;
  - read-only Cloudflare;
  - ntfy publishing.

  Restic, Cloudflare management, Kuma and ntfy credentials stay on the host.
- Project Gluetun and Tdarr executor credentials (Tdarr: base URL only). Render Seerr's self-generated API key from its settings into its projection.

## [3.15.85] - 2026-10-12

- Pin ghostship-agent 0.9.1 (Plex, Tautulli and Grimmory service backends) and
  project their executor credentials into the private integrations container:
  the Plex token as `PLEX_USER_TOKEN`, the Tautulli API key, and the Grimmory
  application login (not its database credentials), each with the internal
  base URL.

## [3.15.84] - 2026-10-11

- Pin ghostship-agent 0.9.0 (generic service executor, explicit browser
  leases, bounded-wait jobs, skills distribution) and enable
  `skillsReconcile` on chill-penguin.

## [3.15.83] - 2026-10-11

- Project least-privilege credentials for the ghostship-agent generic service
  executor into the private integrations container (read-only at
  `/run/ghostship-secrets/<service>.env`): Sonarr, Radarr, Prowlarr, Bazarr,
  Chaptarr, pyLoad and RomM secrets plus internal base URLs for those and
  qBittorrent, NZBGet and ntfy. Projections now accept non-secret literal
  fields and unquoted (`raw`) output.
- Add `ghostship.privateIntegrations.skillsReconcile.enable` (off): a
  post-deploy oneshot that packages, publishes and verifies the ChatGPT
  skills plugin once the MCP container is healthy.

## [3.15.82] - 2026-10-11

- Raise the private integrations container memory limit from 1 GiB to 4 GiB.

## [3.15.81] - 2026-10-11

- Stop idle deploys from interrupting T3 Code work: the activity probe now treats
  unsettled Claude background tasks and any thread activity in the last 10
  minutes as active, and the deployer never restarts a unit that is mid-start.

## [3.15.80] - 2026-10-11

- Pin ghostship-agent 0.8.27 (AliExpress checkout quotes, Best Buy filament weights).

## [3.15.79] - 2026-10-11

- Pin ghostship-agent 0.8.26 (named tabs, category routing, AliExpress shipping minimums).

## [3.15.78] - 2026-10-11

- Raise the private integrations container to 512 pids and 1 GiB: parallel
  agent windows drive up to 8 Bladebro workers per identity, and the old
  64-pid cap failed worker starts with EAGAIN.
- Pin ghostship-agent 0.8.25 (one window per agent, per-retailer tabs).

## [3.15.77] - 2026-10-11

- Start Agent Desktop Chrome on demand: the agent and personal s6 services no
  longer start at boot; `chrome-ensure <identity>` starts one and waits for
  DevTools, and `svc-agent-desktop-chrome-idle` stops an identity after 10
  minutes on plain `about:blank` only. The `abc` group controls both services
  through `s6-svperms`, so crash restart stays and an idle stop stays down.
- Keep background and occluded Chrome tabs rendering and running timers.
- Accept bursts of concurrent Agent Desktop SSH handshakes (`MaxStartups
  200:30:400`), since parallel agents issue many short browser-control commands.

## [3.15.76] - 2026-10-11

- Tag and build the Agent Desktop image from its own content-addressed
  `containers/agent-desktop` context, so unrelated nixos-config commits no
  longer change `podman-agent-desktop.service` or restart the desktop.

## [3.15.75] - 2026-10-10

- Pin ghostship-agent 0.8.24: the Ghostship MCP adds the read-only `orca_profiles`
  tool for Orca Cloud profiles on the Assistant identity.

## [3.15.74] - 2026-10-10

- Prepare offline Boomer security fixes: run setup and controller state as kiosk,
  confine privileged LED writes, protect Bluetooth logs/locks, and bound event work.
- Copy homebrew assets without following symlinks, keep Wi-Fi passwords off argv,
  replace unsafe secret fallbacks, and bound performance-log classification.
- Repair PICO-8 aliases, retired Tools links, console TUI output, controller policy
  metadata, and exact Star mapping tests; retain owner-accepted emulation risks.

## [3.15.73] - 2026-10-10

- Remove the active private relay identifier from public integration documentation.

## [3.15.72] - 2026-10-10

- Read existing Kuma notification types from their serialized configuration,
  preserving the notification ID while updating the ntfy URL and credential.

## [3.15.71] - 2026-10-10

- Replace Homepage's host Podman socket with a restricted read-only Unix
  broker; deny container inspection, logs, archives, execution, and control.
- Restrict FlareSolverr to public-site egress while retaining internal API
  access and Podman DNS. Cover both bridge peers and routed traffic.
- Require protected approval for private-source CI and migrate RomM's existing
  root accounts to an encrypted password, including authenticated backups.
- Remove host-root file mutations from desktop MCP provisioning,
  qBittorrent configuration, and Tdarr node configuration. Keep
  auto-resume state outside the container's writable tree.
- Harden XML parsing, require critical secrets before config writes, accept
  interspersed config CLI options, and protect NZBGet/Docker Hub credentials.
- Keep VPN credentials out of curl arguments, preserve fallback ordering,
  reconcile existing ntfy alerts, refresh T3 bridge tokens, and keep GC from
  starting a stopped T3 container. Hold the upgrade maintenance lock throughout
  the build and switch.
- Scope iframe-audit Access headers to trusted HTTPS origins and recheck each
  redirect; remove inline-token deployment guidance. Prune OpenCode events
  under SQLite's write lock without replacing live clients' database inode.
- Preserve independent ACP request IDs and handle missing retailer page titles
  and command failures. Preserve dynamic RomM WebSocket paths and queries.
  Add hourly recovery after RomM exhausts its bounded restart window.
  Record retained trust choices and defer emulation work.

## 3.15.70

- Integrate shared MCP/browser/GUI activation with main’s T3 activity-probe and retention fixes, preserving active-session restart protections.

## 3.15.69

- Pin the desktop locking correction: outer MCP batches and nested workers acquire both profile locks in the same order.

## 3.15.68

- Pin the retired-browser platform and managed Bladebro/GUI wrappers to the shared MCP source and package.
- Normalize Pelorus control responses so successful backend input returns a valid REST result; preserve errors and reject unknown responses.

## 3.15.67

- Retire CloakBrowser completely: remove its service, extension timer, dashboard route, installers, and T3 environment/wiring. Cleanup removes retired execution artifacts and images while preserving saved profile data.

## 3.15.66

- Install coding-agent commands from the same pinned Ghostship package as the shared MCP. Boot and periodic source sync no longer rebuild an older main checkout over the tested connector.

## 3.15.65

- Pin Ghostship MCP 0.8.20: verified checkbox activation and worker transport recovery. Live ChatGPT tool validation remains skipped as requested.

## 3.15.64

- Clear only Chrome tab/session restoration files before managed launch so an unclean exit also starts fresh. Preserve cookies, credentials, history, and site storage.

## 3.15.63

- Start Agent Desktop Chrome with a fresh tab after relaunch while preserving profiles and sign-ins. Disable background mode, Memory Saver discarding, and background tab freezing for predictable browser workers.

## 3.15.62

- Pin Ghostship MCP 0.8.19: bounded worker RPC framing, guarded SSH startup, and private loopback OAuth callbacks. ChatGPT authentication remains deferred.
- Set the Agent Desktop task bound to 4,096 under its existing 16 GiB memory bound after parallel browser workloads reached the default 2,048-task limit. Apply the task bound without restarting T3 or the desktop container.

## 3.15.61

- Pin Ghostship MCP 0.8.17: resilient coding connections without tool replay, exact owned-tab lifecycle, and collector context support. ChatGPT authentication remains deferred.

## 3.15.60

- Pin Ghostship MCP 0.8.15: native-input workflow transactions, Drive row selection, and observed item identity/fee evidence. ChatGPT authentication remains deferred.

## 3.15.59

- Pin MCP 0.8.14 accessible role actions and foreground native-input isolation; DOM reads remain parallel. Full retailer/Google/consumer acceptance remains pending.

## 3.15.58

- Pin MCP 0.8.13 Target native title/identity extraction and unknown variant price ranges. Full retailer/Google/consumer acceptance remains pending.

## 3.15.57

- Pin MCP 0.8.12 fresh offer evidence, bounded parallel verification and compact job history. Full retailer/Google/consumer acceptance remains pending.

## 3.15.56

- Pin MCP 0.8.11 typed retailer failure outcomes with conservative interrupted-mutation uncertainty and no replay. Retailer and cached client acceptance remain incomplete.

## 3.15.55

- Pin MCP 0.8.10 fresh-price/condition/eligibility evidence and concurrent job-store initialization fixes. Full retailer and cached client acceptance remain pending.

## 3.15.54

- Pin MCP 0.8.9 product matching, rejecting conflicting selected variants and incomplete verified identity evidence before ranking offers. Full retailer and client acceptance remain pending.

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [3.15.53] - 2026-10-09

- Pin shared MCP 0.8.8 with durable tab/job ownership across PID namespaces,
  interrupted-write reconciliation without replay and explicit diagnostic limits.
- Restore the previous session when managed desktop Chrome restarts. Renderer
  hang root cause and unattended recovery remain pending acceptance.

## [3.15.52] - 2026-10-09

- Pin shared MCP 0.8.7: coding agents and the OpenAI relay use one persistent
  canonical backend with independent sessions and reusable identity-bound workers.
  Connector refresh and broader shopping acceptance remain pending.

## [3.15.51] - 2026-10-09

- Pin shared MCP 0.8.6 with Standard search budgets, canonical product matching,
  destination/offer safeguards and bounded per-worker diagnostics. Retailer
  workflow and price benchmark acceptance remains pending.

## [3.15.50] - 2026-10-09

- Align the shared MCP and coding-agent package at 0.8.5, including the
  verified installed eBay client module path. MCP schemas remain unchanged.

## [3.15.49] - 2026-10-09

- Pin shared MCP 0.8.4: browser-only eBay active/sold/completed evidence,
  explicit sign-in outcomes and retired legacy/API clients. Unknown mandatory
  fees require checkout evidence; listing location no longer implies zero fees.

## [3.15.48] - 2026-10-09

- Update the shared Ghostship MCP to 0.8.3: exact-tab ownership checks,
  interrupted-worker cleanup, independent primary/detail pages, concurrent
  registry reconciliation and accurate mutation idempotence annotations.
  Worker fixtures passed 100 rounds at 1/2/4/8 workers in both identities.

## [3.15.47] - 2026-10-09

- Pin the shared Ghostship MCP to the tested 0.8.2 catalog and browser runtime.
  Coding agents and the private ChatGPT relay use the same server. Integration
  diagnostics expose the pinned source revision, image tag, catalog hash, and
  backend connectivity for deployment and connector discovery checks.

## [3.15.48] - 2026-10-10

- **Fix the T3 Code retention OpenCode prune**: the retention wrapper ran
  `packages/t3code/retention.py` as a lone store file, so its
  `load_opencode_prune()` sibling lookup resolved to
  `/nix/store/opencode-db-prune.py` and failed on every run. OpenCode's
  unbounded event log was never rebuilt, which is why `opencode.db` reached
  10 GiB. Bundle both modules in one store directory so the sibling import
  works, and assert the bundled invocation in `tests/test_t3code_retention.py`.

## [3.15.47] - 2026-10-10

- **Stop mid-turn T3 Code restarts**: the shared activity probe that gates
  tool maintenance, memory recovery, and host deployments only counted a turn
  as running while its `completed_at` was null. T3 Code stamps `completed_at`
  on a running turn when a mid-turn checkpoint diff completes, so a long Codex
  or Claude turn stopped counting as active once its pending request and user
  message windows lapsed. The server monitor then restarted
  `t3code-server.service` for sustained memory pressure and interrupted the
  work that was still running (observed on 2026-10-10 at 06:28 and 08:20 UTC).
  The probe now also treats a provider session that is starting or running as
  active work, the same authoritative signal T3 Code uses to keep a turn
  unsettled. Regression tests cover a checkpointed running turn and sessions
  without a turn row.
- **Keep the retention timer alive across store GC**: `t3code-retention` was
  missing from the container image contents, so the daily isolated-store GC
  deleted its binary and the enabled `t3code-retention.timer` failed to exec
  with no log line. OpenCode's unbounded event log then grew to 10 GiB
  (`event` table alone 8.5 GiB), server traces exceeded the retained count, and
  the container previously hit ENOSPC on 2026-09-30, breaking tool updates and
  agent installs. Add the retention package to the seeded and rooted image
  contents, and assert in `checks.nix` that `podman-t3code` seeds it.

## [3.15.46] - 2026-10-09

- **Garbage-collect the T3 Code container's isolated Nix store**: the container
  keeps its own persistent store at `/srv/apps/t3code/nix-root/nix`. Every image
  deployment `nix copy`s a fresh closure into it and agent sessions build into
  it, but nothing ever collected it, so dead paths accumulated without bound.
  A daily `t3code-nix-store-gc` timer now runs `nix store gc` inside the running
  container under the shared maintenance lock. GC removes only paths unreachable
  from GC roots, so live profiles, active sessions, and in-flight builds are
  preserved, and it never restarts the container. It skips when the container is
  not running.

## [3.15.45] - 2026-10-08

- Validate the Bladebro driver across Home Depot, Lowe's, Amazon, Walmart
  and Target: all five load with distinct products and prices and no
  challenge markers.
- Record the concurrency results (three parallel agents with separate tabs,
  independent Agent/Personal profiles, client kills leaving Chrome and tabs
  intact, authentication surviving a Chrome restart).
- Document the driver policy (Bladebro default, Playwright optional, Pelorus
  for native and CDP-incompatible sites) and the upgrade/rollback runbook
  for the pinned Chrome and Bladebro versions.

## [3.15.44] - 2026-10-08

- Add the CDP detection test tooling (dependency-free client, local detector
  page, variant matrix, retailer journey runner) and document the isolation
  result: `Runtime.enable` is the only operation deviceandbrowserinfo's
  detector observes, while attachment, Page/Network/DOM/Accessibility/Input
  and one-shot evaluation stay clean.
- Validate Home Depot end to end with Bladebro real-lane attach and the raw
  minimal CDP client; Playwright and Runtime-enabling clients remain blocked.
- Evaluate the Chrome extension transport: branded Chrome 155 ignores
  `--load-extension`, so non-CDP alternatives need enterprise policy or
  native desktop control.
- Harden the CDP regression runner to fail on missing results, zero page
  samples, Chrome startup failures and unsuccessful commands, and load the
  desktop session environment so timers or `podman exec` can run the tools.
- Strengthen the retailer runner: live product links only, distinct product
  counts, page-completeness markers, explicit 403/challenge detection, and
  a reload step; the no-CDP control stays screenshot-only.

## [3.15.43] - 2026-10-08

- Restore PulseAudio and add Noto Color Emoji so the desktop browser exposes
  real audio devices and emoji fonts instead of container-only stubs.
- Ship the CloakBrowser detection/fingerprint bookmark set as managed Chrome
  bookmarks on both profiles.
- Record that Akamai/PerimeterX detect active CDP clients: Home Depot works
  without CDP (manual Selkies or Pelorus input) and returns 403 to
  Bladebro/Playwright sessions.

## [3.15.42] - 2026-10-08

- Run Google Chrome as a native Wayland client so Selkies touch gestures
  and Pelorus scroll injection reach the browser; XWayland Chrome ignored
  compositor wheel events, which broke touch scrolling and manual scroll.

## [3.15.41] - 2026-10-08

- Replace Camoufox in the agent desktop with Google Chrome stable, pinned by
  version and SHA-256, as the default LXQt/XDG browser; retire the Camoufox
  runtime, browser cache and Playwright WebSocket forwarding.
- Run persistent Agent and Personal Chrome instances under independent s6
  services with fixed loopback DevTools ports and profile directories that
  preserve authentication across restarts and image updates.
- Integrate Bladebro, pinned by version and SHA-256, in real-browser attach
  mode and provision its MCP servers automatically for t3code over SSH with a
  pinned desktop host key.
- Keep the browser environment coherent for mainstream sites: match the
  container timezone to the egress location, pass through `/dev/dri` so
  Chrome reports the real GPU instead of disabled WebGL, and re-enable
  Chrome's sandbox. Lowe's search and product pages now load with
  structured extraction.
- Launch Chrome with a deliberately minimal command line (custom profile,
  loopback DevTools port, first-run/crash UX suppression, locale and window
  size only) and add `ghostship-chrome-instance` for on-demand instances.
- Keep Pelorus native GUI control and the authenticated desktop proxy with a
  reduced Pelorus-only surface.

## [3.15.40] - 2026-10-08

- Add the Ghostship agent desktop: a persistent LXQt + labwc Selkies
  workstation on `chill-penguin` built from the LinuxServer `ubuntu-lxqt`
  image with pinned Camoufox/Playwright, Pelorus AT-SPI desktop control, key
  based SSH and supervised browser owners.
- Expose a token authenticated automation proxy on a private
  `agent_desktop_net` shared with t3code, and route `desktop.ghostship.io`
  through the existing Cloudflare tunnel and Access policy.
- Document the endpoints, profiles, GUI automation, updates and recovery in
  `docs/agent-desktop.md`.

## [3.15.39] - 2026-10-06

- Provide `git` to the `ghostship-config-tests` derivation; the t3code retention
  test invokes `git worktree` and failed in the sandbox without it.

## [3.15.38] - 2026-10-06

- Build the private MCP sidecar from the extracted `ghostship-tools` platform
  (`ghostship-private-tools`) instead of `ghostship-agent`.
- Update the CI private-source importer to recognize the renamed input and
  preserve its `dir = "ghostship-tools"` subdirectory.

## [3.15.37] - 2026-10-05

- Add a daily `t3code-retention` service that rotates oversized operational logs,
  prunes OpenCode's unbounded SQLite event log, archives settled threads after
  7 days, deletes threads idle for 180 days through the orchestration API, and
  removes archive-only worktrees under `~/.t3/worktrees` when no active thread
  still shares the path.
- Point the OpenCode launcher at a home-backed `TMPDIR` and clear the
  `NO_COLOR`/`FORCE_COLOR` conflict that polluted every OpenCode stderr line.

## [3.15.36] - 2026-10-03

- Pin the verified merged Ghostship Agent revision for private Keep and Amazon deployment.
- Record native host verification and next-boot generation 238 while preserving the active T3 session.

## [3.15.35] - 2026-10-03

- Deploy Keep create/update with separate titles, checkbox row patches, labels, image attachments and label/tag searches; preserve the active T3 session.

## [3.15.34] - 2026-10-03

- Deploy the Amazon multiword-query schema fix for the connected ChatGPT host.

## [3.15.33] - 2026-10-03

- Refresh pinned integration sources after reconciling current shopping and host changes.

## [3.15.32] - 2026-10-03

- Fix Keep session recovery by preserving Google session authentication timestamps;
  verify all eight personal Keep tools and four Amazon reads against the live host.

## [3.15.31] - 2026-10-03

- Pin the Keep navigation fix and its required public browser-client identifier;
  include the registered Assistant ChatGPT metadata workflow, delete-to-trash
  support and private cached authentication. CloakBrowser is used for auth only.

## [3.15.30] - 2026-10-03

- Route Keep accounts to Assistant/Default profiles and execute operations
  directly, retaining revision checks and durable interruption recovery.

## [3.15.29] - 2026-10-03

- Authenticate CI public host-key metadata requests with the scoped Actions token
  to avoid shared-runner anonymous API limits; record live relay evidence.

## [3.15.28] - 2026-10-03

- Pin the private integration image's shell dependency required by real Podman
  health probes, after verifying authenticated OpenAI tunnel polling.

## [3.15.27] - 2026-10-03

- Provision the encrypted Ghostship relay bundle for the owner-created tunnel,
  retaining disabled personal Keep access pending independent review.

## [3.15.26] - 2026-10-03

- Consolidate private Keep and Amazon into one Ghostship connection, official
  relay and scoped credential bundle, retaining separate service authorization.

## [3.15.25] - 2026-10-03

- Package private Ghostship Keep and Amazon MCP profiles in one immutable ARM64
  OCI image, with separate scoped official OpenAI relays and a host-only Keep
  approval broker. Personal activation remains disabled and relay provisioning
  remains owner-controlled; no inbound MCP port or T3 Code restart is required.

- **Fix pyLoad iframe blacking out on Queue or Packages**: pyLoad renders its
  Queue, Packages, Files, Logs, and Settings links plus theme assets as
  root-absolute paths (`href="/queue"`, `href="/web/..."`). Inside Muximux's
  `/pyload/` same-origin proxy those references escaped the prefix and landed on
  Muximux's own `404` page, which is the black screen users saw after clicking
  through the embedded UI. Rework the `/pyload/` and `/web/` nginx locations to
  rewrite root-absolute `href`/`url()` references back under `/pyload/`, so
  in-iframe navigation stays inside pyLoad.

## [3.15.24] - 2026-10-01

- **Restore Antigravity session startup**: T3 0.0.44 resolves `node` from
  `PATH` and refuses a runtime whose resolved path or inode matches
  `process.execPath`. The `t3-runtime-preload.cjs` shim overrode
  `process.execPath` with the pinned Node, so T3 mistook the container's Node
  for its own executable and failed every Antigravity session with
  `NodeRuntimeUnavailableError` ("Antigravity sign-in requires Node.js"). Drop
  the obsolete override; the packaged T3 now finds Node on `PATH` directly.

## [3.15.23] - 2026-10-01

- **Keep the Tdarr encoder from stalling behind policy refusals**: Tdarr stops
  handing out work once `stagedFileLimit` items sit in the review queue, and a
  full queue silently idles every worker. Every deterministic policy refusal
  (unknown original language, above 1080p, HDR, interlaced, missing audio
  language tags, commentary tracks, no original audio, foreign titles without
  English subtitles) now ends at a local `plexSkip` node that leaves the file
  untouched and records the item as done. The old flow parked those files at
  `Require Review`, which is what wedged the encoder twice. `plexSkip`
  deliberately does not use `removeFromTdarr`: deleting the record while the
  file stays on disk makes the next scan re-queue it forever.
- **Detect a full staging queue**: a 15-minute `tdarr-staged-guard` timer fails
  loudly when staging reaches 90% of its limit and reports the review count, so
  a future queue buildup is visible instead of silently idling transcodes.

## [3.15.22] - 2026-10-01

- Move RomM and Grimmory into the Muximux dropdown, add an optional Muximux
  `label` so the Homepage tile renders icon-only, and set that label empty.

## [3.15.21] - 2026-09-30

- Reclaim Btrfs metadata on a schedule and bound the churn that exhausts it.
  Add a weekly metadata balance, a weekly unused image prune, a one GiB
  journald cap, and a bounded systemd-boot entry count so the root filesystem
  can no longer fill its metadata and latch read-only while `df` shows space.

## [3.15.20] - 2026-09-30

- Project the OpenCode Go `GO_API_KEY` into the T3 Code container as
  `OPENCODE_API_KEY` so OpenCode can use the `opencode-go` provider.

## [3.15.19] - 2026-09-27

- Remove the orphaned OpenChamber and Synara HTTP monitors for retired apps.

## [3.15.18] - 2026-09-27

- Remove the unused NZBGet Gluetun namespace proxy, prune its Homepage card,
  and remove the orphaned ChatGPT card after its container retirement.
- Provision Uptime Kuma push monitors for every declared container and report
  missing, stopped, or unhealthy containers from the host timer.
- Enforce Kuma's disabled-login setting through its settings API, leaving
  Cloudflare Access as the public authentication layer.

## [3.15.17] - 2026-09-27

- Ensure Homepage's house icon widget is added when the existing widgets file
  has no logo entry, and add the XPlus4 shortcut to Muximux.

## [3.15.16] - 2026-09-27

- Allow Uptime Kuma to render inside the protected Muximux dashboard and remove
  the non-UI FlareSolverr shortcut.
- Add Homepage status entries for every container, enforce complete registry
  coverage, and show Homepage's house mark without the title text.

## Unreleased

## [3.15.15] - 2026-09-27

- **Route foreign titles without English subtitles to review**: Detect missing
  English subtitles in the source before changing streams or starting an
  encode, avoiding predictable post-encode validation failures.

## [3.15.14] - 2026-09-27

- **CloakBrowser fonts and quiet permissions**: Mount a persistent directory for
  licensed Windows fonts and refresh Fontconfig before launch; browser profile
  defaults now suppress permission prompts and crash restore bubbles.

## [3.15.13] - 2026-09-27

- **Automatic chill-penguin upgrades**: Enable nightly `system.autoUpgrade` on
  `chill-penguin` with `--impure` so Asahi firmware stays enabled, fetch the
  public repository over HTTPS, catch up missed runs after boot, wait for a
  running backup, and alert on failure.
- **Keep active T3 Code sessions running**: The server monitor no longer
  force-restarts active work for memory pressure or a missing provider; only a
  stopped server or an unresponsive web UI can interrupt active turns.
- **Resume interrupted T3 Code deploys**: Stamp containers with their deployment
  ID and record an already-running image as applied instead of restarting it
  again. Share the tool-maintenance lock with the host deployer through the home
  bind mount and hold it across the container restart. A host switch no longer
  restarts an in-flight deploy.
- **Skip needless T3 Code restarts**: Ghostship tool package changes no longer
  queue a server restart.
- **Bounded recovery from a broken T3 Code image**: Adopt a running new image
  only once healthy, wait out its start period, retry an unhealthy one at most
  three idle-gated times, alert on each failed start, then stop until a new
  image arrives.
- **Sync shared source checkouts**: Fast-forward `/workspace/ghostship-agent`
  and `/workspace/nixos-config` from `origin/main` before each tooling install
  and every 30 minutes, skipping checkouts with local work.
- **Skip redundant Cursor downloads**: Only run the Cursor installer when its
  pinned release is not already active.

## [3.15.12] - 2026-09-26

- **Idle-aware T3 Code deployment**: Queue container image updates and restarts
  behind sustained idle, and apply them with `t3code-deploy-when-idle` only
  after active turns and pending tasks clear, so updates no longer interrupt
  running agent work.
- **Fix idle gate on deploy retry**: Re-check activity on every restart attempt,
  including the retry after a deployment that failed health verification, so a
  leftover `applying` marker cannot bypass the idle gate while tasks are active.

## [3.15.11] - 2026-09-23

- Include the T3 child-memory guard launcher in the inner image store so its
  systemd timer can execute after deployment.

## [3.15.10] - 2026-09-23

- Add a 5-second T3 child-process memory guard. It terminates an oversized
  provider/tool process before it can exhaust the shared service cgroup, while
  leaving the server process and other work running; the existing server
  health recovery remains the fallback.

## [3.15.9] - 2026-09-23

- Run the WSL WinCLI install before Codex Desktop migration can end Home
  Manager activation early while the desktop app is open.

## [3.15.8] - 2026-09-23

- Install the sbroenne WinCLI for both WSL hosts, available to Codex from WSL
  and Windows desktop sessions without an always-running service.

## [3.15.7] - 2026-09-23

- Keep the existing D-Bus implementation on WSL hosts so live NixOS switches
  are not blocked by the D-Bus switch inhibitor.

## [3.15.6] - 2026-09-23

- Repair Claude Code's recursive npm launcher by installing the matching
  platform executable directly and verifying it before use. Replace CLI
  shims atomically so existing links are not overwritten, and bound version
  probes so a broken launcher cannot stall automatic updates.

## [3.15.5] - 2026-09-23

- Ignore completed turns and old pending-start rows when deciding whether
  T3 maintenance can proceed. After five consecutive unhealthy checks, the
  server monitor performs one recovery even when activity state is stale or
  unknown, with a cooldown before another attempt. Measure memory even when
  the web interface is already unavailable.

## [3.15.4] - 2026-09-22

- Keep T3 release validation variables local so promotion cannot retarget the
  active release to a temporary staging directory. Migrate an existing staged
  installation to a verified versioned release during maintenance.

## [3.15.3] - 2026-09-22

- Restore the T3 Code web interface after npm replaced the package files used
  by a running server. Stage future T3 releases in versioned directories,
  install the native package explicitly, validate the browser bundle, and
  switch only new launches. Use the image's Python for native npm builds.
- Retry deferred tool updates as soon as T3 becomes idle, while preserving the
  active session and its queued restart. Check both the web page and the API
  environment endpoint; report degraded container health without killing
  active work.
- Remove the unused `t3code-pair` helper from the image and persistent home.
- Prefer image tools over stale user shims in T3 services and maintenance.

## [3.15.2] - 2026-09-21

- Connect the armored-armadillo WSL worker to the main T3 web client through a
  dedicated, Access-protected Cloudflare tunnel instead of T3 Connect. Add
  guarded two-minute self-healing for the worker and connector; both start with
  the NixOS WSL system and require no Windows scheduled task.
- Add an idempotent Cloudflare tunnel provisioner that reconciles the named
  tunnel, exact DNS record, loopback ingress, Access coverage, and private
  connector token without placing credentials in the Nix store.

## [3.15.1] - 2026-09-21

- Include GNU Make in the managed agent-CLI maintenance runtime so T3's
  Linux platform package can build its `node-pty` fallback when npm has no
  prebuilt binary for the current Node.js ABI.

## [3.15.0] - 2026-09-21

- Add a reusable `ghostship.host.roles.t3worker` role and `modules/agent-worker`
  platform so a Windows/WSL2 desktop joins the T3 web interface as its own
  environment. Each worker runs a persistent `t3 serve` system service, reaches
  the fleet through T3 Connect, and keeps independent projects, threads,
  providers, files, and execution.
- Install T3 and every supported provider CLI (Codex, OpenCode, Claude, Cursor,
  Gemini, Grok, and optional Antigravity ACP) through the existing agent
  maintenance service, and restart the worker only when an installed version
  changes. Provider instances are seeded only when the worker has no settings.
- Keep workers standalone: they receive only this repository's small skill set
  under `home/config/skills/` and the repo-local `home/config/AGENTS.md` with
  WSL2-specific guidance. The `ghostship-agent` catalog is not installed,
  cloned, or executed on worker hosts.
- Retire OpenChamber, the Synara T3 Code container, and the ChatGPT/Codex
  workstation: remove their modules, packages, workflow, tests, and docs, and
  quarantine their `/srv/apps` state, containers, images, units, and dashboard
  entries through `modules/self-hosted/cleanup.nix`. Keep the T3 Code Codex
  provider.
- Fix `checks.nix` referencing the already-removed `podman-synara` unit, which
  had broken host evaluation and CI.
- Clean retired agent artifacts from WSL2 user homes, including Paseo, Agent
  Deck, the WSL OpenCode desktop server, old OpenChamber user units, and
  `.openchamber` state.

## [3.14.6] - 2026-09-21

- Restore the managed Ollama Cloud and OpenRouter API keys to the T3 Code
  container environment so OpenCode's environment-backed provider
  configuration authenticates after container replacement or restart.

## [3.14.5] - 2026-09-21

- Run T3's Antigravity browser-suppression preflight with the pinned Node
  runtime instead of re-invoking the packaged T3 executable with unsupported
  Node flags.

## [3.14.4] - 2026-09-21

- Complete the Antigravity ACP compatibility bridge by returning the pinned
  1.1.1 initialization descriptor immediately and suppressing the agent's
  delayed duplicate response. This breaks the T3/agent initialization
  deadlock while leaving all authenticated session traffic on the real agent.

## [3.14.3] - 2026-09-21

- Bridge Google Antigravity's ACP initialization ordering so T3 Code can
  complete its local health check and start sessions after a server restart.
  The bridge injects the required `initialized` notification, then suppresses
  the duplicate notification from the client.

## [3.14.2] - 2026-09-21

- Make the Antigravity ACP launcher select the native ARM64 harness itself.
  T3 Code sanitizes provider child environments, so relying on a caller-supplied
  `ANTIGRAVITY_HARNESS_PATH` could relaunch the staged x86_64 helper under QEMU
  and fail session startup with a generic ACP transport error.

## [3.14.1] - 2026-09-21

- Make T3 Code's agent maintenance resolve current npm releases online and
  verify the installed manifests, so a cached or otherwise stale T3, Codex, or
  Claude CLI is a visible maintenance failure rather than a false success.
- Include the OpenSSL certificate directory required by Cursor's Node runtime.

## [3.14.0] - 2026-09-20

- Run Tdarr automatically on chill-penguin with one CPU transcode worker, folder watch, scan on start, and atomic replacement after validation.
- Publish Tdarr on Homepage and Muximux at `tdarr.ghostship.io` with Cloudflare Access protection.
- Reconcile original-language metadata from Radarr and Sonarr so unrelated dubs can be removed without guessing from filenames or stream order.

## [3.13.2] - 2026-09-20

- Wrap the current native T3 CLI with its image-provided GCC runtime library
  path. T3 0.0.42 on ARM64 requires `libatomic.so.1`; keep that path scoped to
  T3 so project-pinned Nix commands still run with clean loader settings.

## [3.13.1] - 2026-09-20

- Snapshot Chill Penguin's dedicated `/srv` Btrfs subvolume when seeding
  Synara. Snapshotting the parent root omitted nested subvolume contents and
  prevented the initial migration from finding the T3 Code state.

## [3.13.0] - 2026-09-20

- Add the independent Synara T3 Code container at `synara.ghostship.io`, with
  separate home, workspace, nested Docker, Nix store, health supervision,
  dashboard registration, Cloudflare routing, and backup coverage.
- Seed Synara once from a crash-consistent Btrfs snapshot of T3 Code's live
  home, workspace, and nested Docker state. The reflink migration preserves
  transferable provider logins, configuration, conversations, worktrees, and
  project files without stopping or restarting T3 Code.

## [3.12.3] - 2026-09-18

- Run the Antigravity `localharness_external` helper natively on ARM64 instead
  of under QEMU. Emulation corrupted its Go runtime and aborted long turns with
  "Harness process exited unexpectedly (WS close code 1006)". The x86_64 ACP
  server stays emulated because Google's binary aborts on 16 KiB pages.
- Stage the matching native harness from the official registry in the automatic
  updater, and fail the offline probe when a runtime harness is not native.

## [3.12.2] - 2026-09-17

- Define the `nobody`/`nogroup` account in the T3 container image so Google's
  Antigravity ACP harness can drop privileges for sandboxed tool work instead
  of aborting the turn.
- Fail the offline Antigravity ACP probe closed when that sandbox account is
  absent.

## [3.12.1] - 2026-09-17

- Include the agy updater integrity tests in automatic unittest discovery.

## [3.12.0] - 2026-09-17

- Detect sustained T3 process memory growth or memory pressure and restart only when idle, with a 30-minute cooldown and diagnostic samples. Ignore deleted threads and superseded pending requests in maintenance idle checks.

## [3.11.1] - 2026-09-17

- Raise the T3 service memory budget to 24 GiB soft / 32 GiB hard for the server and its child agents, preventing repeated provider and Git timeouts from cgroup memory throttling.

## [3.11.0] - 2026-09-15

- Add persistent Grok Build CLI installation and update hooks for the T3 container, with device authentication and T3 provider setup instructions.

## [3.10.2] - 2026-09-15

- Install and automatically update the official `agy` terminal CLI in the T3 container, with checksum verification and persistent storage.

## [3.10.1] - 2026-09-14

- Disable OpenChamber and its deployment timer on chill-penguin while retaining
  its declaration and persistent data for later restoration; pause its uptime
  monitor and retain monitoring history.
- Restore Homepage, Plex, NZBGet, qBittorrent, Sonarr, Radarr, and Prowlarr
  as top-level Muximux desktop tabs after the registry migration misplaced them.

## [3.10.0] - 2026-09-08

- Make T3 Code installable in Android Chrome with a named standalone manifest,
  Android launcher icons, and credentialed manifest fetching behind Cloudflare.
- Preserve installation support across T3 updates and show a reconnect screen
  offline without caching private workspace data or old application bundles.

## [3.9.1] - 2026-09-15

- Delegate shared agent instruction generation and installation to
  `ghostship-agent`, which owns the `.agents` guidance and delivery defaults.

## [3.9.0] - 2026-09-08

- Reapply T3's shared Ghostship agent tooling and native browser
  through persistent bootstrap, server-start, doctor, and post-update hooks.
- Automatically update Antigravity from the official ACP registry, preserving
  the Asahi-compatible runtime and activating only after an offline ACP check.
- Attempt each T3/provider update independently and queue idle restarts after
  partial updates or Ghostship package changes.
- Use Cloudflare sign-in for T3 browser access without a second pairing prompt,
  with an internal gateway and a loopback-only T3 backend.

## [3.8.3] - 2026-09-08

- Share installed Ghostship skills and tools across T3 Code providers, preserve
  provider plugins, and add repeatable container setup and CI validation.
- Reduce agent instructions to short workflow rules and task-specific references;
  install and apply Matt Pocock's `writing-for-agents` skill.


## [3.8.2] - 2026-09-08

- Space ordinary container restart attempts by 30 seconds so brief boot-time
  DNS failures do not exhaust systemd's rapid-start limit.
- Document persistent T3 Code deployment so reboot keeps the deployed service.

## [3.8.1] - 2026-09-08

- Run Antigravity's official x86 ACP agent through container-local QEMU on
  ARM64, avoiding Google's 4 KB allocator assertion on Asahi's 16 KB pages.
- Add an offline ACP handshake probe that exercises initialization without
  requiring a Google login or sending a model request.

## [3.8.0] - 2026-09-08

- Restore T3 Code alongside OpenChamber with independent project copies,
  persistent systemd user services, nested Docker, and an isolated Nix store.
- Enable native Codex/OpenAI, OpenCode, and Google's official Antigravity ACP
  agent; keep initial provider sign-in separate from container health.
- Register T3 Code for dashboards, Cloudflare ingress, monitoring, and backups.

## [3.7.5] - 2026-09-08

- Publish Muximux settings atomically with their PHP access guard, preventing
  concurrent reads from observing its legacy partial header rewrite.
- Use its static favicon for health checks so routine probes do not trigger
  GitHub branch refreshes or configuration writes.
- Remove the retired Paseo dashboard alias and correct Chaptarr ingress docs.

## [3.7.4] - 2026-09-08

- Allow Kuma's populated monitor/stat login burst within a bounded Engine.IO
  polling limit so provisioning remains repeatable after initial setup.
- Monitor pyLoad's direct public robots endpoint instead of its favicon
  redirect, avoiding false alarms while retaining strict HTTP status checks.

## [3.7.3] - 2026-09-08

- Supply Kuma's required empty monitor conditions for HTTP, TCP, and heartbeat
  provisioning instead of sending an implicit null value.
- Monitor the primary OpenChamber HTTP endpoint through the service registry.
- Omit Seerr's legacy enable query parameter only for an empty selection,
  satisfying its validator while preserving existing enabled libraries.

## [3.7.2] - 2026-09-08

- Keep the shared Podman network setup active after success so simultaneous
  container starts do not repeatedly run it and hit systemd's start limit.
- Keep both agent containers outside shared hard startup dependencies so a
  network-setup unit update cannot stop active OpenChamber work.
- Run ntfy on unprivileged internal port 8080 and synchronize its tunnel,
  dashboard, health check, publisher, and monitoring references.
- Use Plex's installed curl client for readiness checks instead of absent wget,
  avoiding false health failures and unnecessary container restarts.
- Support the released Seerr library-setup API as well as its newer API,
  preserving selected libraries when retrying incomplete provisioning.

## [3.7.1] - 2026-09-08

- Preserve chill-penguin's running D-Bus implementation across the nixpkgs
  refresh so fleet activation does not require rebooting the active agents.

## [3.7.0] - 2026-09-08

- Declare service hostnames, origins, and dashboard metadata with each container;
  automatically reconcile Cloudflare routes/DNS and both dashboards while
  preserving unrelated entries and Google Access policies.

- Add Uptime Kuma, authenticated Android ntfy notifications, and Seerr with
  approval-required requests using existing Plex/Sonarr/Radarr settings.
- Add encrypted Restic backups, isolated restore checks, retention, stale-job
  alerts, and a recent-backup gate for automatic container updates. Pin the
  current MariaDB image digests for reviewed engine migrations.
- Refresh coordinated Nix inputs; adapt Home Manager SSH option names without
  changing policy, and use the compatible nixpkgs ragenix CLI.
- Retain the compatible Apple Silicon input until vendor firmware is rebuilt
  from macOS; the newer input requires a firmware archive this host lacks.
- Render application configuration at service startup, preserve native secret
  values in Podman env files, require critical secrets, and write configs atomically.
- Add readiness notifications, network/NAS/database ordering, and non-destructive
  retirement quarantine while preserving the active agent environment.
- Stabilize OpenChamber with isolated immutable tool generations, activity-aware
  promotion, candidate validation, and recoverable image deployments. Count
  pending goal audits as active work, preserve quiet detached terminals, and
  observe provider retries without aborts. Retain image dependencies for rollback
  and recover staging permissions after interrupted validation.
- Raise the configurable goal continuation cap to 1,000 while retaining token
  budgets and explicit goal termination controls; include the configured limit
  in generation identity so changed limits take effect.
- Preserve the live Codex workstation and reconcile its service registry.
- Add fleet CI and weekly validated input-update PRs; system upgrades consume
  the committed lock file. Correct stale inventory docs and document recovery.

## [3.6.1] - 2026-09-07

- **Notification targets**: Capture task routes across the upstream RPC read
  loop and coalesce repeated completion alerts by upstream notification ID.
- **Phone rotation**: Keep the mobile drawer and visual-viewport sizing on touch
  phones in landscape so browser chrome and the keyboard cannot clip controls.

## [3.6.0] - 2026-09-07

- **Background notifications**: Persist per-device Web Push subscriptions and
  VAPID keys, encrypt completion alerts, wake the service worker for closed-tab
  delivery, and open the app from notification clicks. Report registration
  failures with a retry action.
- **Idle upgrades**: Check the signed ChatGPT Linux repository every 15 minutes
  and allow activation after 15 minutes without browser input, while protecting
  active tasks, recordings, open terminals and dialogs.
- **Project selection**: Disable folder selection during navigation so a quick
  click cannot select the previous directory. Document the OpenChamber project,
  Git authentication and Nix profile migration.
- **Mobile project screen**: Fit the inner zoomed frame to the visible viewport
  and remove the desktop suggestion overlap so project headings and composer
  controls stay separate below Android browser chrome.
- **Browser verification**: Exercise encrypted push payloads, stopped-worker
  notifications, multi-device focus and update deferral, plus the folder-loading
  race. Include a local speech fixture tool for microphone acceptance.

## [3.5.0] - 2026-09-07

- **ChatGPT Linux workstation**: Restore the web-native desktop renderer using
  the official ARM64 Linux application and its native runtime in the existing
  Nix/systemd OCI workstation, with persistent Nix, Docker, home and workspace.
- **Application updates**: Authenticate OpenAI's signed package index, build and
  smoke-test isolated candidates, queue idle activation and restore the previous
  generation after failed startup. Refresh browser assets on transport changes.
- **Browser compatibility**: Support sandboxed Linux preloads, preserve binary
  IPC payloads and initialize the upstream renderer's application version.
- **Web controls**: Use upstream web menus, keep project actions visible, refresh
  chunked state updates and reconnect without replaying an application backlog.
- **Embedded browser**: Resize pages to their panel, preserve keyboard modifiers,
  and keep typing focused through cursor overlays and application shortcuts
  without announcing navigation on each keystroke.
- **Bundled plugins**: Make runtime copies writable so Linux plugin variants can
  be materialized from sealed Nix resources.
- **Restart reliability**: Keep the updater alive through its own restart and
  health checks, and defer automatic activation while browser tabs are connected.
- **Chat startup**: Forward desktop tool-server configuration to each persistent
  app-server thread and provide the Linux sandbox helper.
- **Folder picking**: Keep file dialogs above clipped project modals while
  preserving the parent dialog during selection.
- **Recovery checks**: Require renderer heartbeats and roll back failed service
  starts as well as failed health checks.
- **Mobile layout**: Keep navigation in a drawer and size the app to the visible
  viewport so the composer stays reachable with browser chrome and keyboards.
- **Session synchronization**: Refresh project state in place across browsers,
  preserving the current conversation and unsent draft during project changes,
  and isolate transport channels between tabs sharing browser storage. Preserve
  Electron window identity so native state broadcasts include the app window.
- **Browser startup**: Compress large HTTP and WebSocket payloads, route request
  replies to their originating tab, and avoid resending the full startup
  snapshot for project updates. Relay complete native chunked messages and
  acknowledge them independently of the hidden renderer to keep state updates flowing.
- **Authenticated app installation**: Include access cookies when Chrome fetches
  the web app manifest behind Cloudflare Access.

## [3.4.6] - 2026-08-12

- **OpenChamber deployment policy**: Let operator-approved host deployments
  apply changed OpenChamber images without waiting for session idle, while
  preserving idle gates for automated tool updates and health recovery.

## [3.4.5] - 2026-08-12

- **Gluetun benchmark reliability**: Use Gluetun's DNS server for candidate
  containers, benchmark against Hetzner's bounded download endpoint, and
  invalidate cached winner speeds when the benchmark source changes.
- **RomM migration recovery**: Allow binary-logged MariaDB migrations to manage
  functions and triggers, wait for database readiness, disable Gunicorn's
  unwritable control socket, and rate-limit failed RomM starts across a full
  day so a migration error cannot cause a rapid restart storm.
- **Recyclarr update recovery**: Follow the supported Recyclarr 8 major image
  tag after upstream removed `latest`, restoring Podman registry auto-update
  checks and moving daily synchronization off the stale 8.3.2 release.

## [3.4.4] - 2026-08-07

- **Codex live acceptance reliability**: Keep repeated readiness checks on the
  existing browser session so they do not discard Chrome's one-shot install
  event, and test the terminal without requiring pre-existing task history.

## [3.4.3] - 2026-08-07

- **Codex Android install recovery**: Restore the browser-owned install offer
  when a shared native-renderer refresh replaces its DOM node.

## [3.4.2] - 2026-08-07

- **Codex auxiliary-window recovery**: Make opaque bridged desktop windows
  accessible dialogs and let Escape close them so a stale About or New Window
  surface cannot permanently intercept browser input.
- **Codex multi-device menu isolation**: Keep the keyboard-shortcuts modal on
  the browser device that requested it instead of opening or replaying it on
  every connected device.
- **Codex UI surface coverage**: Add a real-Chrome desktop and Android sweep for
  application menus, native windows, project dialogs, primary screens, every
  settings screen, and safe dropdown controls.

## [3.4.1] - 2026-07-27

- **Codex Android prompt layout**: Stack the Chrome install offer beneath the
  notification permission offer so both remain readable and clear of the
  native Codex pet on small screens.

## [3.4.0] - 2026-07-27

- **Codex Android install offer**: Match OpenChamber by capturing Chrome's
  `beforeinstallprompt` event and presenting a persistent native-styled Install
  or Dismiss offer. Serve the manifest with its standard media type and verify
  the real Chrome event in the live acceptance suite.

## [3.3.13] - 2026-07-26

- **Codex full-screen fallback**: Keep browser-local full-screen state
  deterministic when Chrome declines the native Fullscreen API, and cover both
  entering and leaving full screen in real-browser tests.

## [3.3.12] - 2026-07-26

- **Codex per-device full screen**: Handle the native full-screen menu action
  in the invoking browser so a closed or second device cannot leave Electron's
  global window state out of sync with tab-local browser full screen.
- **Codex acceptance cleanup**: Use physical project-action clicks and exact
  scheduled-task controls, and tolerate an already-visible persistent pet.

## [3.3.11] - 2026-07-26

- **Codex pet overlay usability**: Make the transparent native pet surface
  click-through in browsers so it remains visible without blocking composer or
  model-picker controls.
- **Codex repeatable browser tests**: Verify that a persistent pet remains
  visible without obstructing later controls across repeated fresh-profile
  acceptance runs.

## [3.3.10] - 2026-07-26

- **Codex auxiliary window lifecycle**: Give opaque browser-bridged desktop
  windows an accessible close control so About does not remain above and block
  the native app after it is opened.
- **Codex live browser coverage**: Exercise the deployed app from fresh
  Android and desktop Chrome profiles, including installability, notifications,
  menus, projects, shared state, Ollama models, terminal, About, pet, and full
  screen.

## [3.3.9] - 2026-07-26

- **Codex project picker browser fix**: Mount the bridged folder picker inside
  the upstream project modal so capture-phase outside-click handling cannot
  dismiss project creation.
- **Codex installable app parity**: Match OpenChamber's install metadata with
  separate standard and maskable Android icons, an Apple touch icon, mobile app
  metadata, language, and related-app policy.
- **Codex browser acceptance tests**: Add real-Chrome regression coverage for
  project picker containment and live full-function/PWA acceptance.

## [3.3.8] - 2026-07-26

- **Codex project removal propagation**: Recognize the native local-project
  fetch response as an authoritative sidebar-state change so removals refresh
  the shared bootstrap and every connected browser.

## [3.3.7] - 2026-07-26

- **Codex multi-device project state**: Detect project-list changes once in the
  shared gateway and send the same delayed refresh signal to every connected
  browser, including passive devices after project removal.

## [3.3.6] - 2026-07-26

- **Codex project synchronization**: Refresh every connected browser after the
  shared project list changes while preserving the completion delay that keeps
  create and remove transactions intact.
- **Codex dropdown controls**: Treat all nested trigger content as part of its
  parent button so icon-based menus remain reliable on touch and in browsers.

## [3.3.5] - 2026-07-26

- **Codex notification prompt**: Keep the browser notification permission
  prompt clear of the composer controls so model and tool dropdowns remain
  usable before the prompt is answered.

## [3.3.4] - 2026-07-26

- **Codex project creation**: Let native project creation finish before
  refreshing connected browser project state instead of interrupting it with an
  immediate reload.
- **Codex dropdown controls**: Make menu-trigger buttons own their complete
  pointer target and refresh the PWA asset cache for existing installations.

## [3.3.3] - 2026-07-26

- **Codex project picker events**: Isolate browser picker pointer events from
  the native app modal so selecting a folder cannot trigger its outside-click
  dismissal.
- **Codex project synchronization**: Reload connected browser renderers when
  the native project sidebar bootstrap changes so created and removed projects
  appear immediately on every device.

## [3.3.2] - 2026-07-26

- **Codex project folder picker**: Keep the native Create Project modal mounted
  while the browser folder picker is open so selecting a source folder returns
  to the project form instead of dismissing it.

## [3.3.1] - 2026-07-26

- **Codex project synchronization**: Keep the project bootstrap current across
  devices and expose the add-project action on touch-only browsers.
- **Codex full-screen menu**: Let the upstream menu command own the browser
  full-screen transition so one tap cannot immediately toggle it back off.

## [3.3.0] - 2026-07-26

- **Codex browser desktop contracts**: Make project folder selection tappable
  inside native modals, preserve the upstream application menu, relay native
  About and pet windows to every browser, and bridge full-screen state.
- **Codex web notifications and schedules**: Request browser notification
  permission explicitly and route desktop notifications through the PWA
  service worker so task and scheduled-run completion works on Android.

## [3.2.1] - 2026-07-26

- **Codex Browser release packaging**: Copy and validate the Browser surface
  bridge explicitly when preparing the Nix ASAR so live containers cannot
  start with Browser chrome but no page surface.

## [3.2.0] - 2026-07-26

- **Codex built-in browser**: Host Codex's expected native renderer origin,
  relay persistent browser surfaces and input through the unchanged desktop
  Browser panel, and share each tab across connected devices.
- **Codex Android app installation**: Keep the official responsive renderer
  behind a root-scoped service worker and standalone manifest, with fresh
  Chrome installability coverage for the container image.

## [3.1.4] - 2026-07-26

- **OpenChamber deployment retry safety**: Latch failed image deployments,
  preserve the idle gate across interrupted attempts, and prevent a failed
  deployment from repeatedly restarting the container.
- **OpenChamber bootstrap reconciliation safety**: Gate orphan reconciliation
  on the root-visible web service state and add unprivileged runtime checks so
  a manual bootstrap cannot rewrite active tool records.

## [3.1.3] - 2026-07-26

- **Codex native startup dependencies**: Start the user D-Bus daemon with its
  real session configuration and expose the C++ and graphics runtime libraries
  needed by the official desktop native modules on ARM.

## [3.1.2] - 2026-07-26

- **Codex ARM runtime stability**: Give the persisted XDG configuration tree
  back to the Codex user during container setup so Electron can initialize its
  crash database instead of repeatedly terminating on `chill-penguin`.

## [3.1.1] - 2026-07-26

- **Codex package evaluation**: Permit the versioned official desktop package
  as the Codex container's sole unfree dependency.

## [3.1.0] - 2026-07-26

- **Official Codex desktop web port**: Replace `0xcaff/codex-web` with a
  versioned bridge around the signed official Codex desktop renderer, preload,
  main process, Linux Electron runtime, terminal, and persistent app server.
- **Shared browser and mobile runtime**: Fan one native app host out to
  multiple browser devices, add confined server-side file dialogs and uploads,
  and ship a Chrome-installable Android PWA.
- **Durable compatibility and operations**: Verify upstream signatures and IPC
  contracts, preserve idle-gated updates and rollback, supervise Electron and
  Xvfb cleanly, and keep only tool-capable Ollama.com models in the picker.

## [3.0.6] - 2026-07-26

- **T3 server browser inheritance**: Attach the CloakBrowser route to the T3
  server unit that spawns provider sessions.

## [3.0.5] - 2026-07-26

- **T3 provider browser environment**: Propagate the internal CloakBrowser URL
  into the T3 server process so Codex and OpenCode sessions inherit it.

## [3.0.4] - 2026-07-26

- **T3 Code CloakBrowser routing**: Configure T3-launched agents to use the
  internal CloakBrowser service so the installed browser tools work without
  per-session setup.

## [3.0.3] - 2026-07-26

- **T3 Code CloakBrowser tools**: Put the preserved Ghostship `agent` and
  `ghostship-cloakbrowser` launchers on the container user's PATH so T3-launched
  Codex and OpenCode sessions can manage CloakBrowser without `agent-browser`.

## [3.0.2] - 2026-07-26

- **OpenChamber interruption prevention**: Decouple container deployments from
  unrelated repository revisions, apply changed images only after sustained
  OpenChamber-reported idle, and run bootstrap hooks before the single web
  service start.
- **OpenChamber session resilience**: Bound provider retries and timeouts,
  enable tool-output pruning during compaction, reconcile orphaned tool calls,
  require consecutive monitor failures, and add restart-source auditing.

## [3.0.1] - 2026-07-26

- **T3 Code migration cleanup**: Remove the retired Paseo npm package during
  every container setup, including when all replacement tools are already
  current and package maintenance is skipped.

## [3.0.0] - 2026-07-26

- **T3 Code replacement**: Replace the Paseo daemon and web UI with upstream
  T3 Code at `t3code.ghostship.io` on its native port `3773`, while preserving
  the existing workspace, credentials, nested Docker, Nix, user services,
  Codex, OpenCode, Antigravity, and Ollama Cloud integration.
- **T3 Code operations**: Add project registration, one-time remote pairing,
  provider-aware health checks, idle-gated updates, and last-good settings
  recovery for the new server.

## [2.6.2] - 2026-07-26

- **Paseo Codex ripgrep compatibility**: Replace Codex's bundled glibc-path
  `rg` with the Nix-packaged ripgrep after container setup and every Codex
  update so agent shell commands do not fail on the minimal image.

## [2.6.1] - 2026-07-26

- **Paseo Ollama provider routing**: Route derived Ollama Codex threads through
  the authenticated loopback endpoint instead of allowing Paseo's Codex adapter
  to reset them to the default OpenAI API.

## [2.6.0] - 2026-07-26

- **Paseo Ollama Codex provider**: Add a distinct `Codex (Ollama Cloud)`
  provider that uses the supported `ollama launch codex` flow through an
  authenticated loopback proxy, with a refreshed catalog of tool-capable
  ollama.com models.

## [2.5.0] - 2026-07-26

- **Paseo agent tooling**: Enable Paseo's MCP server, agent tool injection, and
  browser-tool broker while preserving the rest of the persisted daemon config.
- **Paseo Ollama access**: Install the Ollama CLI and project the existing
  ollama.com API key into the container as `OLLAMA_API_KEY`.
- **Paseo hostname**: Give the container the stable
  `paseo.ghostship.io` hostname instead of a generated container ID.

## [2.4.9] - 2026-07-26

- **Retired skill lock cleanup**: Remove retired skills from the XDG-state
  global skill lock used by agent maintenance, preventing `brainstorming` from
  being reinstalled after cleanup.

## [2.4.8] - 2026-07-22

- **Paseo web UI patch quoting**: Use a single-line JavaScript replacement and
  repair the malformed escaped-newline form left by version 2.4.7 before the
  daemon starts.

## [2.4.7] - 2026-07-22

- **Paseo persisted bootstrap fix**: Apply the web UI connection-hint
  compatibility patch on every daemon start, including when the persisted agent
  tools are already current and cold bootstrap skips package maintenance.

## [2.4.6] - 2026-07-22

- **Paseo web UI bootstrap**: Patch Paseo's same-origin connection hint to
  include the default HTTP or HTTPS edge port, preventing the bundled client
  from rejecting a portless hostname and falling back to `localhost:6767`.

## [2.4.5] - 2026-07-22

- **Paseo reverse proxy connection**: Trust the loopback and Ghostship Podman
  proxy networks so the bundled HTTPS web UI derives a secure `wss://`
  connection from Cloudflare's forwarded protocol.

## [2.4.4] - 2026-07-22

- **Paseo user services**: Start the persistent user D-Bus from its packaged
  session configuration so user units and Secret Service remain reachable.

## [2.4.3] - 2026-07-22

- **Paseo maintenance safety**: Defer package mutation while Paseo reports
  active or unknown work, and add `ps` for managed-provider process
  reconciliation plus bzip2 support for bundled speech model extraction.

## [2.4.2] - 2026-07-22

- **Paseo Antigravity migration**: Treat a persisted `agy` binary as installed
  only when it can execute, so upgrades automatically replace the unusable raw
  aarch64 binary from the initial deployment with the managed glibc wrapper.

## [2.4.1] - 2026-07-22

- **Paseo cold bootstrap**: Assign first-created npm and XDG directories to the
  unprivileged Paseo user before tool installation, and launch the official
  dynamically linked aarch64 Antigravity binary through Nix's glibc loader.

## [2.4.0] - 2026-07-22

- **Self-hosted Paseo**: Add a repo-built systemd Podman image with Paseo,
  Codex, OpenCode, and Antigravity, persistent user services, Docker and Nix
  state, activity-gated four-hour updates and recovery, Quick Tunnels, config
  validation with rollback, clean shutdown, and Homepage/Muximux entries.
- **Paseo exposure contract**: Listen on the internal network at port 6767
  without an application password, leaving the external route and mandatory
  authentication boundary to Cloudflare Access.

## [2.3.0] - 2026-07-22

- **Codex Android installation**: Patch every pinned or automatically updated
  Codex Web generation at runtime with a complete standalone manifest, 192px
  and 512px maskable icons, mobile web-app metadata, and a root-scoped service
  worker so Chrome on Android offers the same install flow as OpenChamber.

## [2.2.1] - 2026-07-22

- **Codex Ollama credential handling**: Keep the Ollama.com authorization
  header out of catalog-refresh process arguments, and let app-server protocol
  helpers discover the managed Unix socket without caller-provided environment.

## [2.2.0] - 2026-07-22

- **Self-hosted Codex Web**: Add a systemd-based Codex container with a
  persistent app server, disposable `codex-web` bridge, persistent user
  services, Docker and Nix state, activity-gated four-hour updates, guarded
  recovery, clean shutdown, Quick Tunnels, and config validation with rollback.
- **Ollama.com models**: Project `OLLAMA_API_KEY` through the secret catalog,
  proxy cloud inference over loopback, and add only models advertising tool
  capability to the Codex Web picker.

## [2.1.128] - 2026-07-22

- **Autoreview skill retirement**: Remove the repo-managed `autoreview` skill
  and its Codex configuration, and clean stale installations from develop
  hosts.

## [2.1.127] - 2026-07-14

- **OpenChamber systemd shutdown targets**: Install systemd's upstream halt,
  shutdown, final, unmount, and halt-service unit chain in the minimal image's
  active unit search path so Podman's `SIGRTMIN+3` stop signal can shut down
  instead of waiting for the outer timeout and forcing a container-wide
  SIGKILL.

## [2.1.126] - 2026-07-14

- **OpenChamber bounded shutdown**: Cap the web and user manager at 10 seconds
  and the Docker and Nix daemons at 30 seconds while preserving systemd's
  longer stop allowance for package updates and bootstrap hooks that mutate
  persistent state. Nix shutdown now includes connection and build workers.
  Podman's 180-second aggregate stop window leaves enough headroom for either
  path, the host unit allows 210 seconds, and explicit `shutdown.target`
  ordering ensures the container services receive their stop jobs without a
  container-wide SIGKILL.

## [2.1.125] - 2026-07-14

- **OpenChamber initial health probe**: Treat the brief interval before the
  container system manager accepts unit queries as startup rather than a
  failed health check, avoiding false failed transient health units during
  deployment.

## [2.1.124] - 2026-07-14

- **OpenChamber persistent store seeding**: Trust paths copied directly from
  the host's local Nix store when incrementally seeding the isolated container
  store, including locally built image closures that have no binary-cache
  signature.

## [2.1.123] - 2026-07-14

- **OpenChamber startup health gate**: Treat activating container setup,
  bootstrap, and web startup as healthy for up to 20 minutes of container
  system-manager uptime so long first-start tooling builds cannot exhaust the
  Podman health start period and enter a container kill/restart loop. Root
  health probes now use absolute Nix-store tool paths. Normal
  restarts now skip tool maintenance when the persisted OpenChamber and
  OpenCode binaries already exist, start the web service before project hooks,
  run bootstrap and before-web hooks in the background, and queue one
  idle-gated maintenance restart after those hooks finish. The container now
  uses an isolated persistent Nix store seeded incrementally from the image
  closure and served through a root-owned internal `nix-daemon`, so
  container-built agent packages survive image replacement without exposing
  the host's primary store to container writes.

## [2.1.122] - 2026-07-14

- **OpenChamber idle-gated tool updates**: Queue OpenChamber and OpenCode tool
  restarts only after an installed version changes, and apply them through a
  separate timer only when OpenChamber's aggregate session activity reports
  that all work is idle. The web monitor now applies the same gate before
  restarting an active but unhealthy runtime, and the outer container health
  policy observes the same gate before killing the container. The web service
  now throttles above 32 GiB and caps its workload at 40 GiB with a
  continue-on-OOM policy, preventing a runaway child process from escalating
  into a host-wide OOM and full OpenChamber restart.
## [2.1.121] - 2026-07-08

- **OpenChamber apply command fix**: Preserve root setuid ownership on the
  container-local `sudo` binary so `openchamber-apply-config` can restart
  `openchamber-web.service` through its narrow sudoers rule as the
  unprivileged `openchamber` user.

## [2.1.120] - 2026-07-08

- **OpenChamber Ghostship agent compatibility**: Seed `/home/openchamber/tools`
  from `/workspace/ghostship-agent/tools` when present so installed
  `ghostship-agent` command wrappers keep resolving their repo-local support
  scripts after container rebuilds.

## [2.1.119] - 2026-07-08

- **OpenChamber project runtime support**: Run startup project hooks as the
  `openchamber` user, add `openchamber-user-units` for persisted user
  systemd services and timers, and document the supported hook, config apply,
  recurring job, and tool auto-update contracts.

## [2.1.118] - 2026-07-08

- **OpenChamber Quick Tunnels**: Replace the in-container Caddy wildcard app
  proxy with Cloudflared Quick Tunnel support and an `openchamber-tunnel`
  helper for exposing OpenChamber-launched loopback web apps through ephemeral
  `trycloudflare.com` URLs.

## [2.1.117] - 2026-07-08

- **OpenChamber sudoers image build**: Remove packaged sudo defaults before
  writing the container-local sudoers and PAM files used by
  `openchamber-apply-config`.

## [2.1.116] - 2026-07-08

- **OpenChamber config apply command**: Add `openchamber-apply-config` for
  non-root OpenChamber JSON validation, native OpenCode config validation,
  controlled web-service restart, health verification, and rollback to the
  last-good runtime config snapshot refreshed by successful
  `openchamber-web.service` starts.

## [2.1.115] - 2026-07-08

- **OpenChamber wildcard app proxy**: Add an in-container Caddy proxy and
  `openchamber-proxy` helper so OpenChamber-launched local web servers can be
  routed under `*.test.openchamber.ghostship.io` through the Cloudflare tunnel.

## [2.1.114] - 2026-07-01

- **OpenChamber Bitwarden projection**: Include Bitwarden client and password
  fields in the OpenChamber runtime secret projection.

## [2.1.113] - 2026-07-01

- **OpenChamber env projection**: Project OpenCode, OpenRouter, and GitHub
  secrets into OpenChamber and source them inside the container runtime.

## [2.1.112] - 2026-06-27

- **Gluetun endpoint fallback**: Rotate through cached PIA WireGuard fallback
  endpoints during bootstrap and let the selector run without depending on a
  healthy Gluetun container so dead VPN endpoints can self-repair.

## [2.1.111] - 2026-06-23

- **OpenChamber hook isolation**: Log failing lifecycle hooks and continue
  startup so persisted user automations cannot prevent OpenChamber from
  starting after image recreation.

## [2.1.110] - 2026-06-23

- **Codex container retirement**: Remove the self-hosted Codex Podman service,
  dashboard entries, secret projection, hosted tooling bootstrap, and
  `codex-web` flake input, and add its live container, unit, image, and
  `/srv/apps/codex` state to retired artifact cleanup.

## [2.1.109] - 2026-06-23

- **OpenChamber automation environment**: Export
  `OPENCODE_AUTOMATION_DIR=/home/openchamber/.automation` from the container
  runtime and keep the persisted automation directory created for the
  `openchamber` user.

## [2.1.108] - 2026-06-23

- **OpenChamber user systemd runtime**: Start `user@3000.service` in the
  container image, provide the minimal user systemd targets and D-Bus user bus,
  and order OpenChamber bootstrap after the user manager is available.

## [2.1.107] - 2026-06-22

- **OpenChamber lifecycle hooks**: Add generic container bootstrap, pre-web,
  and doctor hook directories that run before OpenChamber starts, leave
  repo-installed automation units intact in the persisted home, and allow
  hook-owned system timers to run as `openchamber`.

## [2.1.106] - 2026-06-21

- **OpenChamber web monitor**: Add a container systemd monitor service and
  timer that restarts the OpenChamber web service when the UI is up but the
  managed OpenCode process is missing, and make the system service PATH stable
  for npm-installed launchers.

## [2.1.105] - 2026-06-21

- **OpenChamber tool auto-updates**: Add a container systemd timer that keeps
  OpenChamber and OpenCode installed at their latest npm versions and restarts
  the system web service only when a tool version changes.

## [2.1.104] - 2026-06-21

- **OpenChamber graceful stops**: Increase the Podman stop timeout for the
  systemd-based OpenChamber container so deployment restarts have time to shut
  down cleanly instead of falling back to SIGKILL.

## [2.1.103] - 2026-06-20

- **OpenChamber user unit cleanup**: Remove stale repo-seeded
  `ghostship-*` user systemd units from the persisted OpenChamber home so the
  repo no longer leaves installed services in the OpenChamber user manager.

## [2.1.102] - 2026-06-20

- **OpenChamber system web service**: Run the OpenChamber web process as a
  container systemd service, stop enabling the old user-level
  `openchamber.service`, stop seeding repo-managed user systemd targets, and
  clean up stale repo-managed user unit links.

## [2.1.101] - 2026-06-20

- **OpenChamber user task limit repair**: Rewrite existing persisted
  `openchamber.service` user units when they are missing the unlimited
  `TasksMax` setting.

## [2.1.100] - 2026-06-20

- **OpenChamber process limits**: Remove the Podman PID cap and set the
  generated OpenChamber system and user services to unlimited systemd tasks.

## [2.1.99] - 2026-06-20

- **OpenChamber user systemd runtime**: Run the user manager as the
  `openchamber` user with delegated cgroup control, seed a minimal user
  `default.target`, and make the OpenChamber web shim independent of service
  `PATH`.

## [2.1.98] - 2026-06-20

- **OpenChamber user manager launch**: Start the persistent `openchamber` user
  systemd manager through systemd's actual daemon path so the user service
  manager comes up inside the container image.

## [2.1.97] - 2026-06-20

- **OpenChamber systemd dependency repair**: Disable default systemd
  dependencies on the minimal container units and remove packaged Docker units
  from the boot target so OpenChamber services can start without a full NixOS
  target tree.

## [2.1.96] - 2026-06-20

- **OpenChamber user service repair**: Run the seeded OpenChamber user service
  through a stable `/home/openchamber/.local/bin/openchamber-web-run` shim,
  repair old generated units that point at stale image store paths, and extend
  the first-start health window for systemd-managed startup.

## [2.1.95] - 2026-06-20

- **OpenChamber systemd boot target**: Add explicit `default.target` and
  `multi-user.target` units to the OpenChamber image so systemd can boot the
  generated container services as PID 1.

## [2.1.94] - 2026-06-20

- **OpenChamber systemd supervision**: Replace the container's s6,
  Supercronic, webhook, and Taskfile automation stack with systemd as PID 1,
  keep `dockerd` as a root system unit, and seed OpenChamber as a user-level
  systemd service so the `openchamber` user can manage its own services and
  timers.

## [2.1.93] - 2026-06-19

- **OpenChamber agent ownership**: Stop deleting or rewriting persisted
  Ghostship agent files, Nix state, cron entries, skills links, and OpenCode
  `AGENTS.md`; only seed OpenChamber defaults when missing.

## [2.1.92] - 2026-06-19

- **OpenChamber agent state**: Stop deleting persisted `.agent-browser` and
  `.agents` state during container startup so agent tooling can be managed
  entirely from inside the container.

## [2.1.91] - 2026-06-19

- **OpenChamber persisted tools**: Stop managing `/home/openchamber/.nix-profile`
  from the image startup path and preserve persisted `.local/bin` agent links
  for tooling managed inside the container.

## [2.1.90] - 2026-06-19

- **OpenChamber PATH cleanup**: Put `/home/openchamber/.nix-profile/bin` in
  the managed runtime PATH even without Home Manager session vars, and rewrite
  migrated cron comments that still referenced the Codex container.

## [2.1.89] - 2026-06-19

- **OpenChamber profile package**: Install the seeded OpenChamber Nix profile
  as one curated `buildEnv` package to avoid package-file collisions.

## [2.1.88] - 2026-06-19

- **OpenChamber Nix profile**: Seed `/home/openchamber/.nix-profile` from the
  OpenChamber image package set instead of the Codex Home Manager activation,
  and prune the migrated `ghostship-agent-bootstrap` cron entry.

## [2.1.87] - 2026-06-19

- **OpenChamber bootstrap resilience**: Regenerate the fallback agent bootstrap
  Taskfile at startup, skip Home Manager activation when the existing profile
  already has `agent`, and keep OpenChamber running if bootstrap activation is
  incompatible with the `openchamber` user.

## [2.1.86] - 2026-06-19

- **OpenChamber bootstrap repair**: Replace a stale
  `.automation/ghostship-agent-bootstrap.Taskfile.yml` symlink with a regular
  persisted Taskfile before running the startup bootstrap.

## [2.1.85] - 2026-06-19

- **OpenChamber profile activation**: Stop creating a fake `.nix-profile`
  directory and run the persisted agent bootstrap before s6 starts so
  Home Manager recreates `.nix-profile` as the real profile link.

## [2.1.84] - 2026-06-19

- **OpenChamber session profile**: Seed a minimal
  `/home/openchamber/.nix-profile/etc/profile.d/hm-session-vars.sh` before s6
  starts OpenChamber so the web process inherits the expected Home Manager path.

## [2.1.83] - 2026-06-19

- **OpenChamber runner PATH**: Source Home Manager session variables after the
  container tool path is assembled so `/home/openchamber/.nix-profile/bin`
  remains visible to OpenChamber runners.

## [2.1.82] - 2026-06-19

- **OpenChamber runner environment**: Source Home Manager session variables
  before OpenChamber services start and pass the inherited environment through
  `su-exec` to OpenChamber, supercronic, and webhook.

## [2.1.81] - 2026-06-19

- **OpenChamber startup cleanup**: Prune migrated agent artifacts from the
  OpenChamber home and clear stale OpenChamber port run files before starting
  the supervised web service.

## [2.1.80] - 2026-06-19

- **OpenChamber OpenCode environment**: Make generated OpenCode wrappers source
  `/home/openchamber/.nix-profile/etc/profile.d/hm-session-vars.sh` when it
  exists, without requiring a Home Manager profile.

## [2.1.79] - 2026-06-19

- **Homepage service grouping cleanup**: Prune stale Codex entries from
  Homepage's Management group now that Codex belongs under Services.

## [2.1.78] - 2026-06-19

- **Agent dashboard placement**: Move OpenChamber and Codex into Homepage's
  Services group and order OpenChamber after Grimmory in Muximux.

## [2.1.77] - 2026-06-19

- **RSS Bridge retirement**: Remove RSS Bridge from the active self-hosted
  stack, Homepage, and Muximux, and add cleanup for its Podman unit, container,
  image, and `/srv/apps/rss-bridge` config.

## [2.1.76] - 2026-06-19

- **OpenChamber self-hosted service**: Add a repo-built OpenChamber image for
  `chill-penguin` with s6-managed Docker-in-Docker, OpenChamber, Supercronic,
  and webhook services, persistent `/home/openchamber` state under
  `/srv/apps/openchamber`, OpenCode installed for OpenChamber to start, no UI
  password configuration, and Muximux updated to make OpenChamber the primary
  agent link while moving Codex into the dropdown.

## [2.1.75] - 2026-06-15

- **Codex user tool path**: Expose mutable Codex-user tooling only through
  `/home/codex/.local/bin`, keep npm-backed agent installs under internal
  `ghostship-agent-tools` state, and initialize the standard XDG user
  directories in the hosted Codex image.

## [2.1.74] - 2026-06-08

- **Codex container Nix logs**: Make `/nix/var/log/nix` writable by the
  `codex` user in the Codex image so rootless Nix can create derivation build
  logs while building Home Manager activations.

## [2.1.73] - 2026-06-08

- **Codex container Nix store**: Build the Codex image with a populated Nix
  database and make the image-owned `/nix/store` plus `/nix/var/nix` writable
  by the `codex` user so rootless Nix and Home Manager activations produce
  system-visible `/nix/store` paths instead of falling back to a per-user
  chroot store.

## [2.1.72] - 2026-06-08

- **Codex startup directory**: Start the Codex web service from `/home/codex`
  and set the container working directory to the persisted Codex home.

## [2.1.71] - 2026-06-08

- **Codex automation ownership**: Stop seeding the
  `ghostship-agent-bootstrap` Taskfile and cron entry from the NixOS container
  config. `nixos-config` now only provides the base image, `agent-browser`, and
  persistent Supercronic/Taskfile framework; `/workspace/ghostship-agent` owns
  its repo-specific persistent bootstrap through Home Manager activation.

## [2.1.70] - 2026-06-08

- **Codex automation agent repo bootstrap**: Seed the existing Codex
  Supercronic and Taskfile automation with a managed
  `ghostship-agent-bootstrap` task that builds and activates
  `/workspace/ghostship-agent#homeConfigurations.codex.activationPackage` for
  the `codex` user. This keeps mutable shared agent tooling and skills outside
  the image while avoiding changes to the Codex container entrypoint/setup
  path; `agent-browser` remains in the base image.

## [2.1.69] - 2026-06-08

- **OpenCode agent tooling fallback**: Teach Codex agent maintenance to fall
  back to OpenCode's architecture-specific npm package when `opencode-ai`
  selects an incompatible platform package, and make the flake-installed
  `opencode` wrapper tolerate that fallback binary layout in Nix images that
  do not expose the glibc loader at the fallback binary's FHS path.

## [2.1.68] - 2026-06-08

- **Codex agent tooling flake installer**: Add
  `.#install-codex-agent-tooling`, a repo-local flake app/package that installs
  shared AGENTS files, repo-managed skills, agent CLI wrappers, and
  `ghostship-agent-maintenance` into a user home so a fresh Codex image can be
  rehydrated without rebuilding the image.

## [2.1.67] - 2026-06-08

- **Codex external agent tooling bootstrap**: Keep `agent-browser` in the Codex
  container image, but move mutable agent CLI and skill maintenance outside the
  image. Host startup now copies the maintenance script, shared AGENTS files,
  and repo-managed skills into persisted `/home/codex`; container setup runs
  that external script so Codex, Gemini, OpenCode, skills, and browser runtime
  updates do not require rebuilding the image.

## [2.1.66] - 2026-06-08

- **Codex agent tooling bootstrap**: Include shared agent maintenance tooling in
  the Codex container image, target it at `/home/codex`, and run it during
  container setup so rebuilt images refresh Codex, Gemini, OpenCode, skills,
  and `agent-browser` tooling inside the hosted Codex environment. Container
  setup also relinks the repo-managed shared AGENTS file and skills into
  `/home/codex` so persisted homes cannot keep stale skill symlinks from older
  images.

## [2.1.65] - 2026-06-08

- **Codex web refresh**: Update the Codex container to the latest
  `0xcaff/codex-web` flake input.

## [2.1.64] - 2026-06-07

- **Codex container Git LFS**: Add `git-lfs` to the Codex container image so
  hosted Codex sessions can fetch and work with LFS-backed repositories.

## [2.1.63] - 2026-06-07

- **Codex image-owned Nix store**: Stop bind-mounting and reseeding `/nix` for
  the Codex container. The image now owns `/nix`, and startup clears the Codex
  user's mutable Nix DB/profile/cache state when the image generation changes
  so user metadata cannot point at paths from the previous image.

## [2.1.62] - 2026-06-06

- **Muximux Grimmory bundle rewrite**: Rewrite Grimmory's current
  `text/javascript` bundles and runtime base-url API calls through the
  `/grimmory/` proxy so the UI calls the proxied API path.

## [2.1.61] - 2026-06-05

- **Codex Nix seed validation**: Reseed the persisted Codex container `/nix`
  tree when required wrapper or Node runtime paths are missing, even if the
  image marker already matches.

## [2.1.60] - 2026-06-05

- **Codex Nix store seeding**: Replace the persisted Codex container `/nix`
  tree when the image changes so new image store paths and symlink targets are
  not lost during deployment.

## [2.1.59] - 2026-06-05

- **Codex share mount**: Make `podman-codex` wait for the host
  `/mnt/share` NFS mount before starting so the container's `/mnt/share`
  bind mount sees the live library share.
- **WSL share mount path**: Move develop-host Synology NFS automounts from
  `/mnt/z` to `/mnt/share`, while clearing stale `/mnt/z` mount state during
  activation.

## [2.1.58] - 2026-06-04

- **Codex s6 service packaging**: Package Codex s6 service run scripts as
  image-compatible binaries so the container image builds cleanly.

## [2.1.57] - 2026-06-04

- **Codex container supervision**: Run the Codex container under s6, add
  `supercronic`, `webhook`, and `task`, and persist cron, webhook, and Taskfile
  automation under `/home/codex/.automation`.

## [2.1.56] - 2026-06-04

- **Prefect retirement**: Remove the Prefect workflow stack, its PostgreSQL and
  Redis support containers, and its Homepage and Muximux dashboard entries from
  `chill-penguin`.

## [2.1.55] - 2026-06-04

- **Developer SSH public key**: Manage `id_ed25519_dev.pub` through the
  develop-host Home Manager profile alongside the encrypted private key.

## [2.1.54] - 2026-06-04

- **Autoreview skill**: Vendor OpenClaw's MIT-licensed `autoreview` skill,
  tailor its instructions for Codex-only review closeout, and link it into
  develop-host shared skills.

## [2.1.53] - 2026-06-04

- **Developer SSH key secret**: Encrypt `id_ed25519_dev` as a develop-host
  home secret and keep Git plus `chill-penguin` SSH using that key.

## [2.1.52] - 2026-06-04

- **Chill Penguin SSH profile**: Replace the stale root-only host alias with
  the active `chill-penguin` SSH profile.

## [2.1.51] - 2026-06-04

- **Muximux Grimmory loading**: Route Grimmory through a same-origin
  `/grimmory/` Muximux proxy, align its health check with the documented
  `/api/v1/healthcheck` endpoint, and mount library/bookdrop paths at the
  container paths expected by current Grimmory images.

## [2.1.50] - 2026-06-04

- **NZBGet container startup**: Keep NZBGet behind Gluetun, seed the
  LinuxServer container auth env to match Homepage, and pin `ScriptDir` to the
  mounted scripts directory so newer NZBGet releases do not look under the app
  install path.
- **Homepage Prefect icon**: Replace the invalid selfh.st Prefect icon
  reference with the Simple Icons Prefect glyph.

## [2.1.47] - 2026-06-02

- **Muximux pyLoad API polling**: Proxy pyLoad's root `/json/` polling
  endpoints through Muximux so the same-origin dashboard can refresh status and
  queue data instead of logging 404s.

## [2.1.46] - 2026-06-02

- **Muximux proxy asset paths**: Proxy pyLoad's root `/web/` assets through
  Muximux, keep pyLoad's session cookie available to those asset requests, and
  fix RomM's root `/assets/` and `/api/` proxy paths so dynamically referenced
  assets do not fall back to Muximux.

## [2.1.45] - 2026-06-02

- **Muximux pyLoad redirects**: Force same-origin pyLoad proxy redirects to
  stay on HTTPS so Cloudflare-served Muximux iframes do not hit mixed-content
  redirects after pyLoad autologin.

## [2.1.44] - 2026-06-02

- **Muximux iframe fixes**: Route pyLoad through a same-origin `/pyload/`
  Muximux proxy with redirect and cookie-path rewrites, fix RomM's `/romm/`
  proxy prefix stripping so asset requests return JavaScript/CSS instead of the
  Muximux app shell, and remove the non-web SSH Access endpoint from Muximux.

## [2.1.43] - 2026-06-02

- **Muximux iframe audit tooling**: Add a repeatable `agent-browser` based
  audit script and documentation for testing Muximux entries through the real
  Cloudflare Access path before making iframe fixes.

## [2.1.42] - 2026-06-01

- **Prefect startup ordering**: Use unique generated env temp files and make
  Prefect services wait for Redis so concurrent service starts do not race.

## [2.1.41] - 2026-06-01

- **Prefect support image pulls**: Reuse cached PostgreSQL and Redis images on
  service restarts while keeping Podman registry auto-update labels, preventing
  Docker Hub rate limits from blocking Prefect support services.

## [2.1.40] - 2026-06-01

- **Prefect Redis cache**: Run Prefect Redis without snapshot persistence so
  background services keep accepting writes even when RDB saves would fail.

## [2.1.39] - 2026-06-01

- **Prefect image pulls**: Reuse cached Prefect images on service restarts
  while keeping Podman registry auto-update labels, avoiding Docker Hub rate
  limits during rebuilds.

## [2.1.38] - 2026-06-01

- **Prefect database bootstrap**: Ensure the Prefect PostgreSQL database exists
  before starting the server so reused state directories can migrate cleanly.

## [2.1.37] - 2026-06-01

- **Prefect workflow stack**: Replace Windmill with Prefect as the final
  workflow orchestrator design, restore the Prefect Podman stack, wire
  dashboards to `prefect.ghostship.io`, and retire Windmill artifacts.

## [2.1.36] - 2026-06-01

- **Muximux qBittorrent icon**: Use a distinct magnet icon for qBittorrent
  instead of sharing NZBGet's download icon.

## [2.1.35] - 2026-06-01

- **Muximux qBittorrent order**: Keep qBittorrent in the same Muximux position
  previously occupied by VueTorrent, directly after NZBGet.

## [2.1.34] - 2026-06-01

- **qBittorrent runtime identity**: Rename the managed torrent container,
  systemd units, dashboard entries, and Gluetun restart wiring from
  `vuetorrent` to `qbittorrent` while keeping the VueTorrent alternate WebUI
  installed as the qBittorrent UI.

## [2.1.33] - 2026-06-01

- **Windmill official-base image**: Restore Windmill and build the
  `JEMALLOC_SYS_WITH_LG_PAGE=14` binary as an overlay on top of the official
  Windmill image instead of using a fully custom Nix root filesystem.

## [2.1.32] - 2026-06-01

- **Hatchet workflow stack**: Replace the short-lived Prefect stack with a
  Hatchet control plane using PostgreSQL-backed messaging, wire Homepage and
  Muximux to `hatchet.ghostship.io`, and retire Prefect runtime artifacts.

## [2.1.31] - 2026-06-01

- **Prefect workflow stack**: Replace the Windmill stack with a Prefect 3
  Podman deployment backed by PostgreSQL and Redis, wire Homepage and Muximux
  to `prefect.ghostship.io`, and retire Windmill runtime artifacts.

## [2.1.30] - 2026-06-01

- **Windmill worker isolation**: Override the worker unshare flags to avoid
  Podman's denied `--mount-proc` path while keeping PID unshare enabled.

## [2.1.29] - 2026-06-01

- **Windmill worker startup**: Include `unshare` in the repo-built Windmill
  Podman image so the worker can satisfy `ENABLE_UNSHARE_PID` and stay running
  on `chill-penguin`.

## [2.1.28] - 2026-06-01

- **Windmill workflow stack**: Replace n8n with a repo-managed Windmill
  server, worker, and PostgreSQL Podman stack; rebuild the Windmill container
  with `JEMALLOC_SYS_WITH_LG_PAGE=14` for Apple Silicon page-size
  compatibility; wire dashboard entries to `windmill.ghostship.io`; and retire
  the now-unused SearXNG search/cache containers, secrets, dashboards, and
  runtime artifacts.

## [2.1.27] - 2026-06-01

- **Self-hosted service retirement**: Retire Changedetection and PriceBuddy
  now that n8n replaces the change-monitoring workflow and PriceBuddy appears
  abandoned. Remove their local image contexts, secret wiring, refresh timers,
  dashboard entries, containers, and stale runtime artifacts.

## [2.1.26] - 2026-06-01

- **Self-hosted service retirement**: Retire BentoPDF, ConvertX, IT Tools,
  MeTube, and OmniTools from the `chill-penguin` stack, add cleanup for their
  stale containers/images/dashboard entries, redistribute Homepage utilities,
  and replace the broken Codex Homepage icon.

## [2.1.25] - 2026-06-01

- **CloakBrowser extension refresh**: Keep the last known-good unpacked
  extension when an upstream extension download temporarily fails, while still
  failing if no usable installed copy exists.

## [2.1.24] - 2026-06-01

- **Container auto-update auth**: Extend the shared Podman registry auth file
  to cover `docker.n8n.io` as well as Docker Hub so n8n auto-update checks do
  not fall back to anonymous pulls and fail on registry rate limits.

## [2.1.23] - 2026-05-31

- **Local image refresh**: Add daily forced rebuild timers for the local
  Changedetection and PriceBuddy scraper CloakBrowser images so their `latest`
  base images update automatically before the running services restart. The
  refresh services also prune stale hash-tagged local image leftovers after the
  restarted service adopts the current tag, and automatic NixOS upgrades no
  longer try to commit lock-file changes from remote flake checkouts.

## [2.1.22] - 2026-05-31

- **Develop and secret cleanup**: Remove duplicate Home Manager OpenCode
  wrapper wiring, drop the unused CIFS package from develop hosts, and retire
  unused n8n, Electron Hub, Google AI Studio, NVIDIA Build, SMB, and Zenmux
  secret catalog entries.

## [2.1.21] - 2026-05-31

- **Retired image cleanup**: Add leftover upstream Agent Zero and local Honcho
  image repositories to the `chill-penguin` retired artifact cleanup inventory.

## [2.1.20] - 2026-05-31

- **Develop module cleanup**: Remove the unused `modules/develop/core.nix`
  duplicate now that develop hosts import `modules/develop/default.nix`.

## [2.1.19] - 2026-05-31

- **Codex mobile patch cleanup**: Remove temporary manifest, service worker,
  debug overlay, and route fallback changes while keeping the mobile viewport
  clamp that fixes Android thread input clipping.

## [2.1.18] - 2026-05-31

- **Codex mobile shell height**: Clamp the hydrated Codex app shell and main
  content viewport to the measured mobile visual viewport so first-load thread
  pages do not extend under Android Chrome controls.

## [2.1.17] - 2026-05-30

- **Codex hydration diagnostics**: Keep the mobile debug overlay refreshing
  after React root mutations so thread screenshots capture hydrated app state
  instead of only the startup loader.

## [2.1.16] - 2026-05-30

- **Codex deep-link diagnostics**: Keep mobile helper assets root-relative on
  thread routes, avoid serving the SPA shell for asset-like 404s, and report
  client runtime errors in the mobile debug overlay.

## [2.1.15] - 2026-05-30

- **Codex mobile diagnostics**: Add a temporary `?ghostship-debug=1` overlay
  that reports Android viewport, composer positioning, service worker, and
  install-prompt state from the device.

## [2.1.14] - 2026-05-30

- **Codex Android clearance**: Give the mobile floating composer a fixed
  Android navigation clearance fallback and keep the manifest link unversioned
  while no-store headers handle freshness.

## [2.1.13] - 2026-05-30

- **Codex mobile viewport owner**: Apply the mobile bottom inset to Codex's
  main content viewport, use the small viewport height on touch devices for
  first paint, and serve the PWA manifest with the manifest media type.

## [2.1.12] - 2026-05-30

- **Codex mobile first-load inset**: Re-run the visual viewport sizing after
  DOM readiness, page load, animation frames, and short Android browser-chrome
  settle delays so the follow-up composer clears mobile controls before focus.

## [2.1.11] - 2026-05-30

- **Codex mobile installability**: Add a real service worker, 192px PWA icon,
  and body-level mobile bottom inset so Chrome can install the app and the
  portal-mounted follow-up composer clears mobile browser controls.

## [2.1.10] - 2026-05-30

- **Codex patched launcher**: Repoint the copied `codex-web` launcher at the
  patched package output so the live server uses the mobile and manifest fixes.

## [2.1.9] - 2026-05-30

- **Codex static cache disable**: Disable Fastify Static's default cache
  header on the Codex webview root and apply no-store headers there directly.

## [2.1.8] - 2026-05-30

- **Codex static shell headers**: Set no-store headers from Fastify Static's
  file header hook so the app shell and manifest are not overwritten by static
  defaults.

## [2.1.7] - 2026-05-30

- **Codex shell cache enforcement**: Disable Fastify's default static cache
  header for the Codex webview root so the app-shell no-store hook is not
  overwritten.

## [2.1.6] - 2026-05-30

- **Codex shell cache control**: Mark Codex HTML, manifest, mobile viewport
  script, and SPA fallback responses as non-cacheable so authenticated browser
  paths stop reusing stale app-shell metadata.

## [2.1.5] - 2026-05-30

- **Codex mobile inset priority**: Mark the mobile composer bottom inset
  override important so later upstream bundle CSS cannot reset it.

## [2.1.4] - 2026-05-30

- **Codex mobile cache bust**: Inline the mobile viewport override into the
  Codex web HTML and version the manifest link so mobile browsers do not keep
  stale hashed assets or manifest metadata.

## [2.1.3] - 2026-05-30

- **Codex installable web app**: Add standalone PWA manifest metadata and iOS
  standalone web-app tags to the patched Codex web bundle.

## [2.1.2] - 2026-05-30

- **Codex mobile viewport**: Patch the Codex web bundle in the container image
  to use the mobile visual viewport and safe bottom inset so the floating
  composer is not clipped behind mobile browser chrome.
- **Codex Ollama proxy fix**: Strip the UI-only `ollama/` model prefix from
  Ollama-compatible JSON request bodies before forwarding them to ollama.com.

## [2.1.0] - 2026-05-30

- **Codex Ollama picker**: Add Ollama to the Codex web container, run Codex web
  and an authenticated ollama.com API proxy as the persistent `codex` user,
  project the Ollama API key into the container, and route the live
  ollama.com model list filtered to `tools`, `thinking`, and `cloud` models
  through Codex CLI's native Ollama provider while keeping GPT models in the
  same picker.
- **Codex Bitwarden CLI**: Add Bitwarden CLI to the Codex web container and
  project `BW_CLIENTID`, `BW_CLIENTSECRET`, and `BW_PASSWORD` into the Codex
  runtime environment.
- **Muximux clipboard permission**: Allow clipboard read/write in service
  iframes so Codex copy actions work when opened through `apps.ghostship.io`.

## [2.0.24] - 2026-05-30

- **Codex Nix seed tracking**: Track the built Codex image store path when
  seeding the persistent `/nix` mount so package changes reseed runtime store
  artifacts even when the upstream image tag is unchanged.

## [2.0.23] - 2026-05-30

- **Codex container GitHub CLI**: Add GitHub CLI to the Codex web container
  alongside Git so hosted Codex sessions can run `gh` workflows.

## [2.0.22] - 2026-05-30

- **BookStack removal**: Remove BookStack and its MariaDB sidecar from the
  `chill-penguin` self-hosted stack, including secret projections, dashboard
  entries, modules, and retired live container/config artifacts.

## [2.0.21] - 2026-05-30

- **Codex web service**: Restore Codex as a repo-built Podman OCI service for
  `codex.ghostship.io` using `0xcaff/codex-web`, the Codex CLI, Nix, Git, SSH,
  Docker-in-Docker, Python, Node.js, `uv`, `direnv`, search tools, and basic
  build tools, with persistent `/nix`, `/workspace`, `/home/codex`, Docker
  state seeded from the built image's Nix store, and `/mnt/share` mounted into
  the container.

## [2.0.20] - 2026-05-30

- **JDownloader2 removal**: Remove the headless JDownloader2 service, secret
  projection, dashboard entries, and retired live container/config/image
  artifacts from the `chill-penguin` self-hosted stack.

## [2.0.19] - 2026-05-29

- **JDownloader2 self-hosted service**: Add a headless
  `jlesage/jdownloader-2:latest` container on `chill-penguin` with
  MyJDownloader credentials projected from the new `jdownloader` secret,
  downloads rooted at `/mnt/share/Downloads/JDownloader2`, and
  Homepage/Muximux links to `https://my.jdownloader.org/`.

## [2.0.18] - 2026-05-28

- **Self-hosted agent containers**: Retire the Codex and Agent Zero
  `chill-penguin` containers, dashboard entries, secrets projections, and
  persistent Podman artifacts.
- **CloakBrowser extension defaults**: Make uBlock Origin Lite default to
  complete filtering instead of optimal, and make Bypass Paywalls Clean enable
  all regular default sites when extension storage is empty.
- **CloakBrowser reset**: Remove the CloakBrowser profile-default patching path
  so the manager UI and API keep upstream profile defaults while retaining the
  extension launch fix.
- **CloakBrowser extension defaults**: Persist requested uBlock Origin Lite and
  Bypass Paywalls Clean first-run defaults in the managed extension refresh,
  including complete uBOL filtering, selected rulesets, BPC custom sites, update
  checks, set-cookie opt-in, and suppressed update option pages.
- **CloakBrowser extension launch fix**: Allow Playwright-managed
  CloakBrowser profiles to load unpacked extensions by ignoring the default
  `--disable-extensions` Chromium flag, and disable auto-launch in the
  recommended profile payload.
- **CloakBrowser extensions**: Add a daily extension refresh service that
  unpacks and configures uBlock Origin Lite, I still don't care about cookies,
  and Bypass Paywalls Clean under CloakBrowser data, remove startup creation of
  a managed default profile, and document the recommended API profile payload.

## [2.0.10] - 2026-05-28

- **CloakBrowser manager restore**: Reintroduce the standalone
  `cloakhq/cloakbrowser-manager` service on `chill-penguin` with internal
  `ghostship_net` networking only, restore Homepage and Muximux entries, and
  stop retired-artifact cleanup from deleting its state.

## [2.0.9] - 2026-05-27

- **Shared skill curation**: Vendor Matt Pocock's MIT-licensed `grill-me`
  skill into the repo-managed shared skill set, remove the managed global
  `brainstorming` install, and clean stale `brainstorming` skill state during
  develop-host activation.

## [2.0.8] - 2026-05-26

- **Codex provider wiring**: Remove the standalone `/workspace` mount so Codex
  uses its persisted home as the working area, and seed a managed local provider
  mux for Ollama Cloud and OpenCode Go credentials.

## [2.0.7] - 2026-05-26

- **Codex web service**: Add a Nix-based `codex` Podman service for
  `codex.ghostship.io` with Docker-in-Docker support, persistent Codex home,
  workspace, nested Docker state, and `/nix` storage, plus a dedicated refresh
  timer and Homepage/Muximux entries.

## [2.0.6] - 2026-05-25

- **Agent Zero DinD contract**: Run the Agent Zero container privileged so the
  latest image can start its nested Docker daemon and manage bridge networking.

## [2.0.5] - 2026-05-23

- **Agent Zero Muximux icon**: Switch the Agent Zero Muximux tile to the
  triangular `muximux-archlinux` glyph so it visually tracks the Homepage
  Agent Zero A mark more closely.

## [2.0.4] - 2026-05-22

- **Agent Zero Muximux icon**: Replace the Homepage-style home glyph with the
  Muximux-native `muximux-brand-dot-ai` icon for a closer AI/A-style mark.

## [2.0.3] - 2026-05-22

- **Agent Zero Muximux icon**: Switch the Agent Zero Muximux tile to the
  existing Homepage-style `muximux-home2` icon.

## [2.0.2] - 2026-05-22

- **Agent Zero dashboards**: Add Agent Zero to Homepage's Management group
  directly after Muximux and to Muximux directly after Grimmory, using the
  public `https://agent-zero.ghostship.io` route.
- **Retired image cleanup**: Expand `chill-penguin` retired artifact cleanup
  to prune remaining Hermes and Firecrawl image repositories, and add the
  Homepage NZBGet widget auth fields while keeping the internal URL on
  `http://gluetun:5001`.
- **Develop login shell**: Set develop-role users to `fish` directly.
- **Codex Desktop WSL shell handling**: Keep the NixOS user shell on fish while
  letting Codex Desktop use the standard WSL shell path without the temporary
  fish-wrapper compatibility override.

## [2.0.1] - 2026-05-21

- **Ghostship audit worktree skill**: Rename
  `ghostship-review-worktree` to `ghostship-audit-worktree` across the
  repo-managed skill tree and develop-host skill link.
- **Ghostship audit worktree scope**: Refocus
  `ghostship-review-worktree` on current Codex session changes instead of
  pre-merge comparison against `main`, and remove changelog/version review
  duties from that skill.

## [2.0.0] - 2026-05-21

- **Hermes and Firecrawl retirement**: Remove the deprecated Hermes
  `ghostship-hermes` service and the full Firecrawl stack from
  `chill-penguin`, including their self-hosted modules, Firecrawl image build
  contexts, Firecrawl secret source, Hermes runtime projections, dashboard
  entries, and active README guidance.
- **chill-penguin retired artifact cleanup**: Add an allowlist-only self-hosted
  cleanup module for retired `chill-penguin` services. Activation now stops and
  removes known retired Hermes, Firecrawl, Honcho, LiteLLM, and standalone
  CloakBrowser manager units/containers, deletes their `/srv/apps` state, prunes
  retired project images, and removes stale Homepage/Muximux rows.
- **Retired agent tool cleanup**: Remove managed Paseo, Agent Deck, and the
  WSL OpenCode server service while keeping the OpenCode CLI, add exact cleanup
  for their retired user config/state paths plus browser-use and Caveman skill
  artifacts, and switch managed global skill refreshes to the installed
  `skills` CLI with `brainstorming` verified under shared `.agents`.

## [1.0.3] - 2026-05-21

- **NZBGet Gluetun routing**: Move NZBGet back into Gluetun's VPN namespace and
  update internal Homepage and Hermes URLs to `http://gluetun:5001`.

## [1.0.2] - 2026-05-21

- **VS Code WSL launcher fix**: Resolve the generated `/usr/bin/sh` wrapper
  path before locating its paired `shell`, so FHS shims that symlink to the
  wrapper still launch the real shell correctly.

## [1.0.1] - 2026-05-21

- **Shared PR workflow skill pruning**: Remove the repo-managed
  `github-pr-workflow` skill from develop host links, Codex skill config, and
  stale artifact cleanup.

## [1.0.0] - 2026-05-21

- **Shared skill pruning**: Remove deprecated repo-managed `codex-queue`,
  `nix`, `python`, `skill-creator`, `ssh`, and `wsl2` skills from develop host
  links, Codex skill config, and stale artifact cleanup.
- **Ghostship worktree review skill**: Add `ghostship-review-worktree` as the
  local worktree pre-merge review workflow for concrete issue finding and fix
  planning before merge, while keeping `ghostship-merge-worktree` as the local
  merge workflow used after approval.
- **Ghostship pull worktree skill**: Add `ghostship-pull-worktree` for the
  draft PR path from a worktree, including Codex review, CI follow-up, and
  ready-for-merge gating.
- **Ghostship merge worktree skill**: Replace the bundled merge helper tooling
  with an instruction-only direct merge workflow that updates `main`, handles
  drift and conflicts, verifies `main`, and pushes without using the PR path.
- **Ghostship review worktree checks**: Extend `ghostship-review-worktree` to
  review documentation, changelog, and semantic versioning consistency before
  merge.
- **Develop artifact cleanup inventory**: Add a single Home Manager cleanup
  module for retired develop-user artifacts, moving old Superpowers, managed
  Caveman, and Workmux cleanup into one maintained activation entry.
- **Codex Desktop WSL fish compatibility**: Override only the NixOS-WSL
  `shell-wrapper` on WSL hosts so nested Bash-quoted worktree probes bypass
  fish parsing after importing the normal NixOS and fish environment, while
  develop users still default to fish.
- **NZBGet networking**: Move NZBGet off Gluetun's VPN namespace and onto
  `ghostship_net`, updating the internal Homepage URL to `http://nzbget:5001`.
- **Podman auto-update auth**: Merge Agent Zero's GHCR auth into the shared
  Podman auto-update auth file so the daily registry update pass can check the
  private Agent Zero image without failing the whole run.
- **VueTorrent startup**: Stop fetching the VueTorrent LinuxServer Docker mod
  during qBittorrent container startup so the download stack can reach a
  healthy WebUI without depending on a GHCR mod fetch inside the VPN namespace,
  mount a pinned VueTorrent `v2.33.0` release from the Nix store, normalize the
  WebUI address line for the LinuxServer wrapper, and remove stale qBittorrent
  lockfiles before startup.
- **Agent Zero Nix persistence**: Mount `/nix` through a Podman named volume
  with copy-up so the Ghostship Agent Zero image keeps its baked-in Nix install
  while persisting runtime Nix state.
- **Agent Zero Google AI Studio key**: Project the shared Google AI Studio
  provider secret into Agent Zero as `GOOGLE_API_KEY`.
- **Agent Zero shared memory**: Increase the Agent Zero container shared memory
  mount to 2 GiB for browser-heavy workloads.
- **Worktree PR handoff**: Tighten shared agent policy so worktree work must
  end with a pushed branch, draft-first PR, reviewed Codex comments, checked CI,
  resolved conflicts, and a ready/non-WIP PR before user handoff when unblocked.
- **WSL FHS shim replacement**: Replaced patched `envfs` on WSL hosts with
  explicit writable `/bin/...` and `/usr/bin/...` shims under
  `ghostship.wsl.fhsShims`, preserving the known shell, Starship, Node, GitHub
  CLI, and NixOS-WSL helper paths while leaving Docker Desktop free to create
  `/usr/bin/docker-credential-desktop.exe` at runtime.
- **GitHub PR workflow skill**: Add a shared `github-pr-workflow` skill for
  draft-first PRs, native automatic Codex review defaults, review feedback
  handling, merge-conflict readiness, and shared GitHub Actions CI defaults,
  and retire the local `merge-worktree` skill from the shared skill set.
- **Agent Zero plugin contract**: Project the new Agent Zero plugin runtime
  environment names, including `BW_CLIENT_ID`, `BW_CLIENT_SECRET`, and the
  provider plugin API keys for Ollama Cloud, OpenCode Go, NVIDIA Build Free,
  OpenCode Zen Free, and OpenRouter Free.
- **Muximux Cloudflare recovery**: Point RomM at the live NAS ROM library under
  `/mnt/share/Library/ROMS/ROMS`, create its `.romm` assets directory before
  container start, and make the Muximux RomM proxy resolve `romm` at request
  time so a stopped RomM container no longer prevents the dashboard nginx from
  starting.
- **Agent Zero stack service**: Add Agent Zero as an internal-only self-hosted
  Podman service on `ghostship_net`, using the Ghostship GHCR image with
  Bitwarden CLI credentials projected from the shared Bitwarden source.
- **Source-based secret bundles**: Replaced service-tied ragenix bundles with
  source/provider/service files under `secrets/files/sources`, added shared
  runtime recipients for ScreenScraper and RetroAchievements, and moved services
  onto projected `/run/ghostship-secrets` env files while keeping runtime env
  names stable. Firecrawl now gets `OPENAI_API_KEY` from the Google AI Studio
  source, and `OPENCODE_ZEN_API_KEY` is projected from OpenCode Go's
  `GO_API_KEY` instead of stored separately.
- **Boomer emulator recovery hardening**: Generate Ryubing controller IDs from
  Linux input modalias bus/VID/PID/version fields and Ryubing's
  launch-environment input ID list when available, fail Switch smoke tests on
  Ryubing controller rejection logs, force Ryubing launched games to use the
  managed global input profile, mirror that input profile into per-title
  Ryubing configs, keep the standalone hotkey broker attached to the emulator
  process group, and expose verified USB controller pairing through Bluetooth
  Settings with a kiosk-visible message path.
- **PyLoad failed-download retry**: Add a daily `04:00`
  `pyload-restart-failed` systemd timer that runs a one-shot helper on
  `ghostship_net`, checks pyLoad's queue through `http://pyload:8000`, and
  calls the native `restart_failed` API when failed links are present.
- **Boomer controller recovery**: Treat wired Switch Pro-style controllers as
  USB in the resolved launch map, stop USB plug-in events from running the
  broken Bluetooth reconnect wrapper, make Reconnect All a bounded all-device
  pass, disable the always-running controller autoconnect and Bluetooth health
  diagnostics, and remove legacy hidden ES-DE menu tool scripts.
- **Boomer GameMode fix**: Add the kiosk user to the `gamemode` group and set
  conservative GameMode defaults so emulator launches can apply the
  performance governor, renice, I/O priority, and split-lock policy without
  `pkexec` authorization failures.
- **Boomer physical controller maps**: Make Switch Pro/8BitDo face buttons
  physical across emulator launch config, keep RetroArch hotkey gestures on the
  same physical buttons, set left analog as D-pad only for digital-only
  RetroArch systems, map N64 A/B to physical B/Y, align Dolphin GameCube face
  buttons physically, and add Dreamcast `.elf/.lst/.dat` ES-DE launch coverage.
- **Boomer USB controller reconnect fix**: Count wired resolved controllers in
  Bluetooth Settings status, run the legacy Reconnect Controllers tool through
  the bounded 10-second connector, and keep USB-assisted pairing bounded
  without enabling `joycond` by default.
- **Boomer RetroArch launch fix**: Own the resolved controller runtime
  directory as the kiosk user so launch-time RetroArch player-order append
  configs can be written before the emulator starts.
- **Boomer resolved controller launches**: Add a pre-launch controller resolver
  that reconciles LEDs, writes connected-only player order under `/run`, and
  feeds RetroArch, Dolphin, PCSX2, Ryubing, and Xemu launch-time input config.
- **Boomer stable emulator audio**: Prefer PipeWire SDL3 audio with 48 kHz/1024
  frame stable buffering, add matching PipeWire/Pulse defaults, and set Xemu
  audio to `use_dsp = false` and `hrtf = false`.
- **Boomer ES-DE collections**: Seed empty Local Multiplayer and Co-op custom
  collections and enable them in ES-DE settings for later manual population.
- **Boomer PS2 m3u and multiplayer support**: Resolve PS2 `.m3u` playlists in
  `run-emulator` before launching PCSX2, seed a Soulcalibur III playlist when
  the CHD exists, enable PCSX2 port 1 multitap with four SDL controller slots,
  turn on MTVU with neutral cycle settings, and add token-backed PCSX2
  RetroAchievements projection.
- **Boomer PS2 PCSX2 setup**: Manage standalone PCSX2 `2.6.3` before each PS2
  launch with no setup wizard, Vulkan 3x graphics, managed BIOS/ROM/data
  paths, direct `-batch -fullscreen` launches, SDL controller mappings, and
  native PCSX2 hotkey chords for pause menu, reset, save/load slot 1,
  screenshot, OSD/FPS, and hold-turbo.
- **Boomer Switch Ryubing setup**: Manage Ryubing's current lower-case config
  schema before Switch launches, install the newest local firmware archive into
  Ryubing's native `registered/<nca>.nca/00` firmware store layout, keep the
  Canary pin current, and add hidden `.updates`/`.dlc` auto-registration for
  Ryubing title updates and DLC, including native `/...nca` DLC PFS paths.
  Add Switch hotkeys for Minus + X -> F4, Minus + A -> F8, and Square/Capture
  -> F5 through targeted Ryubing X window key events while preserving Minus +
  Plus twice exit. Generate
  Ryubing SDL3 Pro Controller profiles with Ryubing-native stable SDL3 IDs for
  up to four connected players and tune Switch launches for the RX 6650M dGPU,
  2x internal resolution, 16x anisotropic filtering, Vulkan, docked fullscreen,
  shader/PTC cache, and non-null disabled LED config required by Ryubing's
  SDL3 controller backend. Keep ES-DE folders sorted first while hiding Switch
  `.updates` and `.dlc` staging folders.
- **Boomer Dolphin prompt fix**: Reassert Dolphin analytics opt-out and
  stop-confirm settings immediately before each launch with valid INI syntax
  plus Dolphin `-C` overrides, so GameCube kiosk launches do not ask to report
  usage data or confirm quit/stop.
- **Boomer GameCube Dolphin hotkeys**: Configure Dolphin to launch GameCube
  games without analytics, panic, or stop-confirm prompts, use the raw hotkey
  broker for reset, save/load slot 1, screenshot, and fast mode, and keep
  unsupported quick-actions/debug-monitor and bare Square chords explicitly
  unbound. Keep Dolphin's generated keyboard fallback hotkeys under the native
  `[Hotkeys]` section on Dolphin's `XInput2/0/Virtual core pointer` device and
  Dolphin's grouped hotkey keys such as `General/Reset`, then inject them
  through the same raw `ydotool` path used by other standalone hotkey profiles
  so Dolphin 2603 loads and receives them.
- **Boomer Dolphin native button map**: Correct Dolphin's generated SDL
  bindings so GameCube uses label aliases with A/B and X/Y swapped for
  Boomer's Switch Pro controller, Plus as Start, L1/R1 shoulder labels, and R2
  as the right trigger.
- **Boomer Controller Maps hotkey layout**: Render the same full hotkey combo
  list on every controller map with combo-first rows and `None` for unmapped
  actions. Use `L1`/`R1` for shoulder rows, `L2`/`R2` for trigger rows, keep
  stick clicks on `L3`/`R3`, and label hotkeys with spaced `Minus + ...`
  chords starting with `Minus + Plus 2x`.
- **Boomer hotkey and RetroAchievements regression fix**: Restore the
  per-launch Select+Start double-press exit broker, keep RetroArch hotkeys in
  the managed base config plus controller autoconfigs, add 8BitDo udev
  autoconfig aliases, and load generated RetroAchievements credentials as an
  explicit append config so RetroArch sync no longer strips them. Make
  `xemu-hotkeys` the default Xbox launcher so Xbox hotkeys work without
  selecting an alternate emulator.
- **Boomer PICO-8 hotkey launcher**: Make `pico8-hotkeys` the default, keep
  plain PICO-8 as the fallback alternate, launch PICO-8 with a managed
  `-home` directory, seed its config/controller mapping before launch, and map
  supported PICO-8 keyboard shortcuts through the standalone hotkey broker.
- **Boomer N64 Mupen64Plus-Next tuning**: Keep N64 on RetroArch
  Mupen64Plus-Next, switch the managed core options to GLideN64 with 3x native
  resolution, keep shaders on the global `global.slangp` preset, default all
  four N64 controller paks to rumble, and stop generating ParaLLEl N64 and
  shader-profile runtime option files.
- **Boomer standalone hotkey broker**: Replaced the old controller hotkey
  watcher with a generic broker. The shared per-launch broker handles
  Select+Start twice exit, while expanded standalone profiles stay opt-in. Xbox
  keeps plain `xemu` as the default and adds selectable `xemu-hotkeys` for Xemu
  save/load, reset, screenshot, pause, debug-monitor, and quick-action chords
  through a per-launch HMP socket plus host key injection.
- **Boomer controller mapping standardization**: Keep RetroArch on the managed
  base config, XDG `global.slangp`, and XDG per-core `.opt` files, force PC
  Engine-family cores to 6-button pads for all five players, and enable all
  four generated Dolphin GameCube controller ports while leaving analog-capable
  systems on analog stick input.
- **Boomer PC Engine CD launch fix**: Launch PC Engine CD games with Beetle PCE
  Fast, keep SuperGrafx for HuCard/SuperGrafx games, and sync libretro core
  info from `libretro-core-info` so RetroArch sees the managed metadata.
- **Boomer RetroArch core options**: Write managed core options to RetroArch's
  native XDG per-core layout so each core loads its defaults directly.
- **Boomer RetroAchievements defaults**: Enable RetroAchievements by default
  for RetroArch cores when credentials are present, with visible notifications,
  encore/start-active behavior, badges, rich presence, unlock screenshots, and
  unlock sounds while keeping hardcore mode off.
- **Boomer Beetle SuperGrafx config**: Manage the core's CD BIOS/cache settings,
  enable six-button joypads for all five controller ports, and keep multitap
  enabled.
- **Develop agent maintenance fix**: Fixed a failure in `ghostship-agent-maintenance` where a stale patch for `agent-deck` caused the script to exit before updating `gemini`, `codex`, and `opencode`. Removed the stale web-mutations patch for `agent-deck` (now upstreamed in `v1.7.75`) and made the build process non-fatal so it no longer blocks other agent updates.
- **Boomer Controller Maps hotkey audit**: Show emulator hotkeys only where
  they are actually configured, keeping RetroArch save-state controls off
  standalone emulator maps.
- **Boomer PICO-8 ES-DE support**: Seed a small starter set of existing NAS
  PICO-8 carts into an empty ES-DE ROM folder and document the PICO-8 Switch
  controller map in the on-device Controller Maps TUI and generated policy.
  Use clean `.png` PICO-8 cart names for ES-DE scanning.
- **Boomer ES-DE gamelists**: Stop generating ES-DE gamelists from Nix; let
  ES-DE own gamelist creation and updates.
- **Boomer TeknoParrot launchers**: Use TeknoParrot `.xml` profile files in
  ES-DE and launch them through `TeknoParrotUi.exe --profile` under Wine.
- **Boomer TeknoParrot Wine Mono**: Package the Wine Mono MSI expected by the
  managed Wine build and install it into TeknoParrot's Wine prefix before
  starting TeknoParrotUi.
- **Boomer TeknoParrot first-run setup**: Seed TeknoParrot's `ParrotData.xml`
  for kiosk launches and map friendly ES-DE XML profile names to the official
  TeknoParrot `GameProfiles` id before invoking `--profile`.
- **Boomer TeknoParrot ES-DE identity**: Show TeknoParrot as its own ES-DE
  system instead of reusing the generic Arcade theme label.
- **Boomer TeknoParrot theme**: Add TeknoParrot metadata, logo, and system
  artwork to the managed Art Book Next ES-DE theme so it does not render blank.
- **Boomer TeknoParrot polish**: Force ES-DE's custom systems order and copy
  selected XML profiles into TeknoParrot's `UserProfiles` directory before
  launching them.
- **Boomer TeknoParrot artwork**: Apply Art Book Next's diagonal system-art
  mask to the TeknoParrot After Burner artwork so it matches stock system
  panels, and remove the temporary Model 3/Supermodel theme artwork.
- **Boomer Model 3 library**: Add `Arcade - Model 3 (1996)` to ES-DE as a
  Supermodel-backed arcade library using the stock `model3` theme slot.
- **Boomer Supermodel setup**: Seed Supermodel's bundled `Games.xml` and
  `Music.xml` into the managed XDG config and its `Assets` into XDG data so
  Model 3 ROM sets and crosshair textures are detected.
- **Boomer Model 3 launch fix**: Launch Supermodel with force feedback enabled
  so Star Wars Trilogy Arcade clears its feedback-lever setup check.
- **Boomer Star Wars Trilogy setup**: Remove the optional Star Wars Trilogy
  drive-board ROM region from the managed Supermodel `Games.xml` so the game
  does not stop at the feedback-lever setup screen.
- **Boomer TeknoParrot logo**: Use the supplied path-based TeknoParrot SVG for
  the ES-DE system text logo.
- **Boomer controller probe documentation**: Document the live Switch Pro
  kernel event mapping from the Boomer raw input probe so emulator bindings can
  be based on observed `EV_KEY`/`EV_ABS` codes instead of inferred labels.
- **Boomer Xemu first-run setup**: Launch Xemu with the Nix-generated
  `xemu.toml` machine settings and disable Xemu's welcome wizard so Xbox games
  do not stop at the manual machine configuration prompt when the required BIOS
  and HDD files are present. Hide Xemu's menubar during gameplay, and have
  Xbox launchable images use the `.xiso` naming convention while redump
  backups stay outside ES-DE's `.iso` scan suffix.
- **Boomer emulation setup rendering**: Keep the generated GZDoom config
  Python heredoc flush-left so `emulation-setup.service` can complete during
  deployment.
- **Boomer GZDoom controller reset**: Restore the first Boomer GZDoom controls
  cfg from `e0e6880`, using named `Pad_*` controller aliases and no broad
  button unbind block. Reset stale `Doom.Bindings` and automap sections so
  GZDoom regenerates its generic defaults, while keeping the managed right-stick
  axis map and 25% vertical look scale.
- **Boomer GZDoom controller correction pass**: Apply the current in-game
  8BitDo Ultimate 2C probe as targeted `Joy*`/`POV1*` overrides: Y reloads
  instead of jumping, R1/L1 become User 2/User 1, L2 becomes alt-fire, Minus
  toggles automap, D-pad left/right change weapons, and D-pad up/down handle
  inventory.
- **Boomer GZDoom controller correction pass 2**: Keep the confirmed A/B/X,
  Minus, and D-pad mappings, move L1's remaining weapon-switch event from
  `Joy6` to User 1, add config-only R2 fire candidates for `Joy9` plus
  trigger-axis directions, and guess `Joy11`/`Joy12` for Plus/menu while
  leaving L4/R4 documented but unmapped until unique events are proven.
- **Boomer smoke-test kiosk restore**: Restore `greetd` instead of
  `getty@tty1` after root-run smoke tests on kiosk-mode hosts so Boomer returns
  to ES-DE instead of a console login prompt.
- **Boomer Switch Pro controller alignment**: Align generated controller maps
  and emulator policy around physical Switch Pro labels: Star/Home stays
  controller-local turbo, Select/Minus is the hotkey modifier, Select+X opens
  emulator quick menus where supported, Square/Capture opens native console
  Home only where explicitly configured, and unsupported Square/Capture actions
  are no-op.
  Seed GZDoom's SDL
  `[Joy:JS:*]` axis map so the right stick uses yaw/pitch instead of the Linux
  defaults that can look at the ceiling or treat vertical stick motion as
  left/right turning, with reduced vertical look sensitivity.
- **WSL OpenCode server port**: Move the WSL `opencode-server` Home Manager
  user service to `127.0.0.1:4096` for Windows desktop attachment.
- **VueTorrent download paths**: Persist qBittorrent's default save path at
  `/downloads/Torrent`, keep incomplete torrent data under
  `/downloads/Torrent/.incomplete`, and create that directory before
  VueTorrent starts so partfiles do not land in the shared downloads root.
- **Hermes shutdown signal**: Switch the `chill-penguin` Hermes container stop
  signal to `SIGTERM` so s6-overlay handles host-driven shutdown cleanly.
- **Codex queue skill**: Added a shared `codex-queue` skill for long
  manual-review Codex CLI queues with JSONL sharding, tmux-backed worktrees,
  idle-worker monitoring, ledger validation, smoke testing, and merge-preflight
  support while preserving the rule that final item judgments stay manual.
- **Boomer ES-DE tools menu**: Replace the individual controller and Wi-Fi
  tools with large-font `Bluetooth Settings` and `Wi-Fi Settings` TUIs that
  support keyboard and controller input, Bluetooth pairing/audio routing,
  player assignment, Wi-Fi profile management, and the 2.4 GHz policy toggle
  while keeping lower-level helper scripts available outside the visible menu.
  Launch the TUIs through Xwayland `xterm` in the ES-DE Gamescope session and
  log launcher diagnostics under `/srv/emulation/logs/tools/`. Refine the
  settings TUIs to a dark two-column layout with scroll-safe action lists,
  right-pane hover status, a single Bluetooth toggle, and hidden BlueZ host
  discoverable/pairable fields while retaining the active scanning state. Limit
  the raw input-event reader to controller-like devices so keyboard arrow
  presses are not handled twice, keep status blocks on the Status action only,
  compact Bluetooth status for four controllers plus headphones, and allow
  keyboard player assignment with B/Esc cancel. Fix Bluetooth pairing scans to
  run a real 10-second BlueZ discovery and parse newly discovered devices from
  the live scan output, filter the pairing picker to unconnected controllers,
  audio devices, and Bluetooth peripherals, and show whether each candidate is
  already paired. Register the BlueZ pairing agent during the pair command
  itself, tolerate BlueZ pair/connect commands that report an error after the
  device has already paired or connected, add a `Show Paired` Bluetooth menu
  item, ignore Switch Pro IMU/analog-stick idle noise in the raw input reader,
  and update controller LEDs through the controller-specific sysfs LED
  directory with Switch-style player counts. Add a controller-only Switch Pro
  autoconnect service, a `Controller Maps` TUI, and route `Restart ES-DE`
  through a dedicated delayed system service so it does not kill its own
  frontend session before the restart is queued. Tune Boomer's MediaTek
  MT7921/MT7961 Bluetooth stack for four Switch Pro controllers by preferring
  BR/EDR mode, disabling Wi-Fi power save and MT7921e ASPM, keeping BlueZ and
  `hid-nintendo` detailed debug logging available on demand instead of during
  normal play, removing joycond/cemuhook from the active service set,
  rate-limiting controller autoconnect, re-checking live connected state before
  each host-initiated connect, minimizing
  sysfs LED writes, and logging controller HID health plus pairing diagnostics.
  Dynamically compact connected controller player slots so remaining controllers
  slide down when a middle player disconnects and the returning controller joins
  at the end. Trigger controller slot reconciliation from controller input add
  events and BlueZ connected-property changes with short delayed retries for
  HID LED readiness, merge USB Switch-Pro HID nodes so USB controllers share the
  same player assignment and LED path, track the 8BitDo `2dc8:301a` wired USB
  mode as an input-only player identity, avoid treating stale Bluetooth HID
  nodes as connected when BlueZ no longer reports them, and serialize LED/order
  writes to reduce transient wrong player LEDs. Keep one-shot LED applies from
  being start-limited during fast reconnect cycles. Coalesce
  BlueZ-triggered retries through the one-shot unit and avoid force-writing
  already-correct LED entries so hid-nintendo output reports are not flooded.
  Debounce BlueZ event bursts and update the background state marker from
  one-shot applies to prevent immediate duplicate LED rewrites. Restore
  Boomer's default boot path to the ES-DE kiosk session, make the ES-DE restart
  tool handle both greetd kiosk mode and console mode, and give `bluetoothd`
  plus system D-Bus conservative CPU scheduling weight boosts without enabling
  realtime scheduling or IRQ pinning. Disable Bluetooth `SNIFF` low-power link
  policy for connected Switch Pro controllers so multiplayer sessions favor
  input latency over controller battery life. Make controller reconciliation
  fail-soft when BlueZ D-Bus is slow, rate-limit Switch LED sysfs writes to a
  half-second cadence, and modestly boost system D-Bus scheduling for BlueZ
  control traffic. Bound startup `btmgmt` tuning calls so a busy Bluetooth
  adapter does not hold controller services for long. Add Switch-style hotkeys
  with Select+X as quick menu,
  Select/Minus as the hotkey modifier, Star/Home documented as the controller
  turbo button, a raw controller hotkey monitor for normal emulator exits,
  left-stick-as-D-pad overrides for D-pad-only RetroArch systems, text-only
  two-column Controller Maps for every Boomer system family, an N64 direct A/B
  remap, and managed GZDoom Switch-style controller bindings plus a patched
  GZDoom menu confirm/back mapping.
- **Boomer Dolphin defaults**: Seed Dolphin analytics opt-out, fullscreen
  Vulkan graphics, audio, and Switch Pro controller defaults so GameCube, Wii,
  and WiiWare launches do not block on first-run dialogs.
- **Boomer WiiWare ROM support**: Add `.wad` and `.WAD` to the managed Wii
  ES-DE extensions so extracted WiiWare titles launch through Dolphin.
- **Boomer ES-DE preferences**: Enforce ES-DE's manufacturer/type/year
  systems sorting, display clock, Switch Pro controller prompts, and
  all-controller menu input during frontend config sync. Set Boomer to Hawaii
  standard time and patch Art Book Next's clock format with ES-DE-supported
  hour/minute tokens so the clock renders the hour.
- **Boomer service log cleanup**: Disable BlueZ's unused CSIP plugin alongside
  BAP, keep `audio-route` pointed at PipeWire Pulse instead of autospawning
  PulseAudio, and start UPower under the kiosk boot target for WirePlumber.
- **PyLoad download directory**: Set PyLoad's app config default download
  folder to `/downloads/PyLoad` during container initialization while keeping
  the shared `/downloads` mount unchanged, and remove the image's
  `--storagedir /downloads` command-line override so PyLoad honors the managed
  app setting.
- **Self-hosted secrets**: Limit the self-hosted secret module to
  `self-hosted-runtime` units so host-specific emulation secrets stay managed
  by the emulation module.
- **Boomer FBNeo and Switch launch fixes**: Fixed the performance harness so
  FBNeo's harmless romset search misses no longer classify a successfully loaded
  game as `blocked-missing-runtime`, documented the OutRun shader fallback path,
  and made Ryubing `.nro` launches expose sibling homebrew `data/` assets plus
  existing Switch keys through Ryubing's runtime directories.

- **Boomer Kuwanger emulation PC**: Added a dedicated `modules/emulation`
  NixOS module, enabled it on `boomer-kuwanger`, and wired ES-DE with Art Book
  Next, RetroArch cores, bundled shader packs including Mega Bezel, Gamescope
  FSR launch wrappers, standalone emulator coverage, PICO-8 `requireFile`,
  TeknoParrot free prefix scaffolding, Bluetooth/controller services, Wi-Fi
  disable policy, ES-DE tools, and scraper secret catalog entries. Split the
  module into focused submodules and added ROM disk options, per-core RetroArch
  option/override generation, display matrix testing, richer ES-DE tool menus,
  controller-order persistence, shader fallback status, ROM coverage checks,
  and standalone emulator config scaffolds. Declared Boomer's final label-based
  disk layout with the OS disk mounted at `/` and the ROM disk mounted at
  `/srv/emulation/roms`. Enabled durable SSH with root key login only, disabled
  password and keyboard-interactive SSH authentication, and added Boomer's host
  SSH key to the emulation secret recipient group. Replaced the first-pass
  Wi-Fi rfkill service with a 5 GHz-only NetworkManager profile policy so Wi-Fi
  remains available while avoiding 2.4 GHz associations for Bluetooth. Switched
  Boomer's bootstrap startup mode to a tty shell with `kiosk` auto-login and a
  manual `start-esde` Gamescope/ES-DE launch action until hardware
  bring-up is stable. Hardened Boomer's Wi-Fi bootstrap service so it waits for
  NetworkManager, clears stale Wi-Fi interface pins, and explicitly brings up
  saved 5 GHz profiles when autoconnect does not fire on first boot. Disabled
  BlueZ's unused BAP/CSIP LE Audio plugins on Boomer so the Bluetooth daemon
  stops logging ISO-socket errors while keeping controller-oriented Bluetooth
  active.
  Reworked the controller monitor to read BlueZ devices over D-Bus instead of
  polling `bluetoothctl`, added ES-DE preflight/status helpers, cleared
  unexpected service capabilities so the ES-DE AppImage can run under Gamescope,
  and verified manual ES-DE launch/stop with console recovery on the HX100G.
  Renamed public emulation tools and services to drop the project prefix, made
  Gamescope display selection dynamic across connected HDMI/DP outputs, narrowed
  ES-DE scraper secret wiring to ScreenScraper, and added smoke ROM selection,
  sync, launch-test, and report helpers. Added PipeWire HDMI audio routing that
  selects the currently available AMD HDMI/DP profile, exposed an ES-DE Audio
  Status tool, tightened smoke-test fatal-log detection, and documented that
  only proven failing smoke copies should be manually extracted. Added a
  one-page Boomer hardware/software/system overview document.
  Realigned Boomer's default emulator map with RetroAchievements-friendly
  choices, moved PC Engine to Beetle SuperGrafx, NES/FDS to FCEUmm, PS2 to
  standalone PCSX2, PSP to standalone PPSSPP, and 3DS to Azahar where
  available. Removed Gamescope FSR entirely, keeping Gamescope only as the
  fullscreen/session wrapper, changed the RetroArch default shader policy from
  Mega Bezel to clean NNEDI3/sharp profiles, kept Mega Bezel selectable, and
  added a dedicated RetroAchievements secret projection plus RetroArch runtime
  credential renderer. Added a repeatable emulator performance harness with
  quick, overnight, shader-matrix, scaling-matrix, report, compare, and profile
  tools that reuse `run-emulator`, parse MangoHud CSV frame metrics, and write
  tuning recommendations without automatically mutating runtime profiles.
  Cleared transient smoke/perf test capability sets so `steam-run`/bubblewrap
  emulators launch without the unexpected-capabilities failure seen during
  PICO-8 testing, and classified PICO-8 performance tests as 30 FPS by default
  because many carts, including the `POOM.png` smoke cart, target that rate.
  Replaced nixpkgs' stable Ryubing package with a pinned official Ryubing
  Canary binary package and added `update-ryubing-canary` so the pin can be
  advanced from the official latest redirect before Boomer rebuilds. Added
  Batocera-style `.gzdoom` launcher support for the Doom system so ES-DE can
  list curated launch files while GZDoom receives the referenced WAD/PK3 assets,
  and aligned Boomer's ES-DE ROM folder names exactly with the source
  `/mnt/z/Library/ROMs/roms` library.
  Added `POOM.png` as the PICO-8 smoke cart and made PICO-8 launches request
  an explicit Gamescope Xwayland server so SDL can initialize on the TV path.
  Forced ES-DE's live theme setting to Art Book Next during setup and changed
  frontend-launched games to reuse the existing ES-DE Gamescope session instead
  of starting a nested Gamescope compositor.

- **OpenSpec removal**: Removed the managed OpenSpec wrapper, generated agent
  command surfaces, repo-local planning tree, and stale CLI cleanup path from
  develop-host agent tooling. Removed the installed global
  `using-git-worktrees` skill in favor of the maintained `merge-worktree`
  workflow.

- **Hermes 36841a0 env contract**: Updated the `chill-penguin` Hermes env
  wiring for upstream `ghostship-hermes` `36841a0`, restoring
  `GHOSTSHIP_CODEX_CHANNEL=1492841053642817606`, adding
  `DISCORD_WEBHOOK_CHANNEL=1491229248856260799`, and adding staged
  `hermes-secrets` keys for OpenCode Zen, ZenMux, and Electron Hub router
  providers.

- **VueTorrent errored-torrent auto-resume**: Added a managed timer that
  retries errored qBittorrent torrents every 5 minutes without a per-torrent
  retry cap. The retry action uses qBittorrent 5's
  `/api/v2/torrents/start` endpoint.

- **VueTorrent queue limits**: Set the managed qBittorrent queue to 5 active
  downloads, 20 active torrents, a 20 MB/s global download limit, slow torrents
  excluded from active queue limits, and post-completion rechecks enabled.

- **Hermes latest-image contract update**: Updated the `chill-penguin` Hermes
  contract for upstream `ghostship-hermes` `main` at `8a1a5cb`: Codex primary
  is now `openai-codex/gpt-5.5`, the managed web backend is Firecrawl, and
  Hermes receives the image-owned Bitwarden CLI appdata path plus new
  `hermes-secrets` stubs for Bitwarden, GitHub, and NVIDIA Build credentials.

- **WSL patched envfs restore**: Restored `services.envfs` on WSL hosts for
  Linux/FHS paths such as `/usr/bin/bash`, kept Windows PATH import for desktop
  interop, patched envfs to ignore Windows/DrvFS PATH binaries under
  `/usr/bin` even when WSL exposes them as `9p` mounts with `aname=drvfs`, and
  allowed metadata/path probes so shebang launchers such as npm and npx can
  reopen envfs-synthesized entries without WSL wrappers.

- **Merge worktree finish contract**: Updated the shared `merge-worktree` skill
  so its bundled finish helper fast-forwards local `main` without removing the
  source worktree, and clarified that agents should invoke the helper from the
  installed skill path under `$HOME/.agents/skills/merge-worktree`.

- **Firecrawl CloakBrowser loader fix**: Switched the Firecrawl Playwright sidecar patch to load the ESM-only `cloakbrowser` package through a small CommonJS helper, so the embedded CloakBrowser path works under the upstream service's current Node/TypeScript build output.

- **Firecrawl Postgres arm64 fix**: Replaced the broken `ghcr.io/firecrawl/nuq-postgres:latest` sidecar on `chill-penguin` with a repo-owned multi-arch `nuq-postgres` build based on `postgres:16`, preserving Firecrawl's upstream `nuq.sql` and `pg_cron` initialization so the `nuq` schema comes up correctly on arm64.

- **Standalone CloakBrowser manager removal**: Retired the old `cloakhq/cloakbrowser-manager` service, removed its manager-era Changedetection keepalive unit and timer, dropped the Homepage and Muximux manager tiles, and left Changedetection, PriceBuddy scraper, Firecrawl Playwright, and Hermes on their embedded or image-owned CloakBrowser paths only.

- **Homepage group rebalance**: Rebalanced only Homepage's `Services`, `Management`, `Utilities`, and `Infrastructure` columns while leaving the existing `Media`, `Automation`, and `Downloads` groups intact. `Services` now holds the day-to-day apps, `Management` holds dashboards plus control-plane tools like `n8n` and Changedetection, `Utilities` holds helper/search/conversion tools, and `Infrastructure` now focuses on backing caches, sidecars, and service databases including the Firecrawl Playwright/Postgres/RabbitMQ/Redis stack.

- **Firecrawl self-hosted stack**: Added a new internal-only Firecrawl stack on `chill-penguin` with the upstream API image, Redis, RabbitMQ, `nuq-postgres`, and a repo-owned Playwright sidecar image that patches Firecrawl in-place to launch CloakBrowser directly with `humanize=True`. Wired the new `firecrawl-secrets` bundle and `firecrawl-runtime` projection for `OPENAI_API_KEY`, `POSTGRES_PASSWORD`, and `BULL_AUTH_KEY`, reused the existing internal SearXNG instance at `http://searxng:8080`, projected `FIRECRAWL_URL` plus `FIRECRAWL_API_URL` into Hermes, and added Homepage plus Muximux visibility for `https://firecrawl.ghostship.io`.

- **Firecrawl public tile removal**: Removed the Homepage and Muximux links for `https://firecrawl.ghostship.io` and documented Firecrawl as an internal-only API service with no public web surface.

- **Homepage service regrouping**: Removed stale manager-era Homepage entries from the generated `Services` column, moved `SearXNG`, `BookStack`, `n8n`, and `Changedetection` into `Services`, moved `Firecrawl`, `Firecrawl Playwright`, and `PriceBuddy Scraper` into `Management`, kept `FlareSolverr` in `Utilities`, and pruned the old group placements from the generated `services.yaml`.

- **SearXNG Mojeek removal**: Removed `mojeek` from the enabled SearXNG engine set so the managed rendered config no longer includes it in the active Hermes-facing web pool.

- **Hermes Firecrawl API key projection**: Added a dedicated `FIRECRAWL_API_KEY` to the `firecrawl-secrets` bundle and projected it into Hermes' shared runtime env so Hermes can enable its Firecrawl client path while the internal Firecrawl server continues running without self-host DB auth.

- **Hermes Firecrawl env trim**: Removed the redundant `FIRECRAWL_URL` export from Hermes and kept only `FIRECRAWL_API_URL` for the internal Firecrawl integration contract.

- **Embedded CloakBrowser rollout**: Added repo-owned local image build contexts that embed CloakBrowser into `pricebuddy-scraper` and `changedetection`, replaced PriceBuddy's broken arm64 SeleniumBase sidecar with a repo-owned CloakBrowser Playwright service behind the existing `/api/article` contract, replaced changedetection's manager/CDP dependency with an in-image CloakBrowser Playwright path using `humanize=True`, and added a Firecrawl handoff document for the same binary contract.

- **SearXNG performance-first Hermes tuning**: Replaced the old broad allowlist with a much smaller Hermes-facing pool set, tightened SearXNG's global timeout budget, disabled image proxying, enabled a lightweight Hermes-safe limiter backed by the existing Valkey sidecar, added the persistent `/srv/apps/searxng-cache` bind mount for `/var/cache/searxng`, and replaced the old hand-maintained `settings.yml` mutation path with full managed rendering in `podman-searxng` `preStart` that now requires the existing `SEARXNG_SECRET_KEY` secret instead of generating a random key at startup. Live direct probes promoted `presearch` into the default web pool, while `brave` and `karmasearch` stayed out after immediate `429` and `403` responses.
- **Hermes SOUL persona refresh**: Replaced the default Hermes `SOUL.md` seed with the new Argo persona in the repo and on the live `chill-penguin` runtime so fresh seeds and the current host align on the same assistance and supervision contract.

- **WSL OpenCode desktop service**: Restored a repo-managed
  `opencode-server` Home Manager user service on WSL develop hosts so the
  Windows OpenCode desktop app can attach to `127.0.0.1:4096` over localhost
  forwarding, and removed the repo-managed `ghostship-paseo` daemon startup
  path.

- **Managed brainstorming skill**: Added the standalone
  `obra/superpowers/brainstorming` `skills.sh` install to the develop-host
  maintenance flow so `ghostship-agent-maintenance` keeps it installed and
  refreshed without expanding the repo-managed shared skill inventory.

- **Caveman and workflow retirement**: Removed the managed Caveman default
  behavior from develop hosts, replaced the old Codex Caveman injection with
  declarative cleanup of managed Caveman state, stopped maintenance from
  installing the Caveman Gemini extension or external `skills.sh` Caveman
  skill, and removed the obsolete shared `home/config/workflow.md` /
  `~/.agents/workflow.md` surface.

- **Shared agent instructions rewrite**: Replaced the old global agent prompt
  with the new concise Karpathy-style workflow guidance, removed the unused
  managed `~/.agents/AGENTS.md` target, rewired Codex, Gemini, and OpenCode to
  read directly from the canonical `home/config/AGENTS.md` source through their
  native instruction files, and taught WSL activation to publish the same file
  to the Windows-side Codex Desktop path `%USERPROFILE%\.codex\AGENTS.md`.

- **Hermes current-image runtime refresh**: Removed the stale downstream `CLOAKBROWSER_URL` export so Hermes follows the image-owned native CloakBrowser path, documented `/nix` first-boot seeding plus later default-profile reconciliation, and clarified that the next full Hermes reset must pull the latest published `ghcr.io/ghostship-io/ghostship-hermes:latest` image, wipe persisted auth/XDG/custom-skill/workspace/user-Nix state, rely on bundled upstream default skill seeding, and require fresh Codex auth afterward.
- **Ragenix helper path fix**: Fixed `secrets/rules.nix` to emit rule keys relative to the rules file directory so `secret-edit <logical-id>` and other `ragenix` operations match the tracked `secrets/files/**/*.age` paths again.
- **Managed Paseo daemon and Node FHS wrappers**: Added `paseo` to the same wrapper-plus-maintenance flow used by the other agent CLIs, added a WSL-only `ghostship-paseo` system service that keeps a local daemon on `127.0.0.1:6768` for the Windows desktop app, documented Paseo's current daemon/app version-lockstep expectation, and replaced the broken raw WSL `/usr/bin/npm` plus `/usr/bin/npx` paths with explicit wrapper-backed WSL entries that exec the real Nix store binaries.
- **Develop web service removal**: Removed the managed `opencode-web` and
  `agent-deck-web` user services from the develop/WSL Home Manager profiles, so
  those localhost web daemons are no longer started declaratively on develop
  hosts.
- **Agent Deck maintenance alignment**: Moved `agent-deck` off the flake-pinned package path onto the same wrapper-plus-maintenance flow used by the other agent CLIs, so `ghostship-agent-maintenance` now rebuilds the latest upstream source release with the Ghostship web-mutations patch while the managed CLI remains available for manual use.
- **OpenCode Web UI service fix**: Switched the managed `opencode-web`
  user service to the Nix-provided Node binary instead of the nonexistent
  `/usr/bin/node`, restored an explicit `BROWSER` no-op target, and added
  no-op `xdg-open` plus `xdg-debug` shims so the headless service does not try
  to launch a browser while starting OpenCode. The managed service now runs
  `opencode serve` instead of `opencode web` and binds only to
  `127.0.0.1:4096`.
- **WSL explicit Windows interop contract**: Kept `services.envfs` on WSL hosts for Linux/FHS paths such as `/usr/bin/bash`, disabled automatic Windows PATH import so `envfs` stops synthesizing accidental Windows executables under `/usr/bin`, wrapped `wsl-open` around the real Windows PowerShell path, added a repo-managed `win-powershell` entrypoint, and updated WSL docs to require explicit wrappers or `/mnt/c/...` paths for Windows tools.
- **Dev shell export fix**: Reordered the default flake dev-shell packages to keep `git` before `age`, which avoids the current Nix `2.31.3` order-sensitive `get-env.sh failed to produce an environment` failure while preserving the existing tool set. Refresh `direnv` or start a new shell after pulling the change so the repaired environment export path is used.

- **Hermes default skill seed removal**: Stopped repo-managed default skill seeding for `chill-penguin` Hermes by removing the `skill-creator` copy-if-missing path from `podman-hermes` pre-start so the host now seeds only `SOUL.md` and leaves `/home/hermes/.hermes/skills/` entirely operator-managed by default.

- **Hermes Discord home export**: Added `DISCORD_HOME_CHANNEL=1491229269127598281` back to the `chill-penguin` Hermes container env as an explicit compatibility export while keeping the router/Codex lane contract and five-channel free-response list unchanged.

- **Hermes workstation `main` contract realignment**: Reworked `chill-penguin` Hermes host wiring around the current `ghostship-hermes` `main` image by dropping in-container `systemd` startup, removing host-side `/nix` bootstrap, moving the repo-managed `SOUL.md` and `skill-creator` defaults directly into `/srv/apps/hermes/home/.hermes/`, switching the Discord lane contract to `GHOSTSHIP_ROUTER_CHANNEL` plus `GHOSTSHIP_CODEX_CHANNEL`, rendering `DISCORD_FREE_RESPONSE_CHANNELS` with both pinned lanes and the current three Ghostship free-response channels, and documenting the required destructive stop-reset-start rollout for `/srv/apps/hermes/home`, `/srv/apps/hermes/workspace`, and `/srv/apps/hermes/nix`.

- **Develop agent stack refresh**: Removed the repo-managed `launch-agent` helper, moved `openspec` onto the same managed auto-update path as `codex`, `gemini`, and `opencode`, made Caveman full the default agent style across Codex, Gemini, and OpenCode, and taught `ghostship-agent-maintenance` to ensure the configured `skills.sh` repos such as `JuliusBrussee/caveman` are installed and updated on each develop host.

- **Direct ragenix edit workflow**: Removed the repo-managed plaintext mirror
  helpers so operator secret changes now happen directly through
  `secret-edit <logical-id>`, with `secret-rekey` reserved for recipient
  changes.

- **Hermes pyLoad API contract**: Switched the Hermes utility env projection
  to follow the new upstream pyLoad contract by sourcing `PYLOAD_API_KEY`
  instead of `PYLOAD_USER` and `PYLOAD_PASS` from `pyload-secrets`.

- **BookStack documentation wiki**: Added a repo-managed BookStack service plus MariaDB sidecar to the `chill-penguin` self-hosted stack, wired the BookStack secret/env surface through the new `bookstack-secrets` bundle, exposed the service in Homepage's `Services` group, added a Muximux tile after Prowlarr, moved Chaptarr into the dropdown before Bazarr, and projected `BOOKSTACK_URL`, `BOOKSTACK_TOKEN_ID`, plus `BOOKSTACK_TOKEN_SECRET` into Hermes through the managed runtime env path. The public `bookstack.ghostship.io` route and the initial in-app setup plus API token creation remain manual follow-up outside the repo-managed bootstrap path.
- **Ragenix secret catalog and host intake redesign**: Replaced `sops-nix` with `ragenix`, moved tracked secret storage to logical-unit `.age` files declared through `secrets/catalog.nix` and `secrets/recipients.nix`, added catalog-driven secret projections for shared consumers, restored the ignored `secrets.dec.yaml` plaintext mirror as the normal operator edit surface via `secrets-edit` plus `secrets-reencrypt`, and redesigned `bootstrap.sh` to capture temporary host-intake bundles with `hardware-configuration.nix` and SSH host `ed25519` keys for Codex-assisted integration.

- **Develop GitHub CLI ownership rollback**: Moved `gh` back to the shared
  develop Home Manager package set and removed the repo-managed WSL `envfs`
  fallback for `/usr/bin/gh` so the repo only promises GitHub CLI as
  develop-profile user tooling.

- **WSL FHS GitHub CLI compatibility**: Extended the WSL `services.envfs`
  fallback path so Windows-side tools such as Codex Desktop can resolve
  `/usr/bin/gh` even when the calling environment does not carry the develop
  profile PATH.

- **WSL FHS shell compatibility**: Enabled `services.envfs` on WSL hosts so
  hardcoded paths like `/usr/bin/bash` exist for Windows-side tools such as
  Codex Desktop when they target the NixOS guest.

- **Hermes single-agent cutover**: Replaced the old `assistant`/`operations`/`supervisor` runtime contract on `chill-penguin` with the upstream single-agent layout rooted at `/home/hermes/.hermes`, switched host wiring to the generic Discord and webhook env contract, stopped emitting any repo-managed browser CDP default, collapsed Hermes seeds to one root `skill-creator` tree plus one Crush Crawfish `SOUL.md`, limited managed CloakBrowser defaults to `Changedetection`, documented the required destructive reset of `/srv/apps/hermes/home`, `/srv/apps/hermes/workspace`, and `/srv/apps/hermes/nix` before first deployment, and aligned startup with the image-owned `ghostship-hermes-startup.service` plus `ghostship-hermes-user-tooling-refresh.timer` path.

- **Hermes Discord allowed users contract**: Switched the Hermes container env wiring from the retired per-profile `DISCORD_*_ALLOWED_USERS` inputs to the single upstream `DISCORD_ALLOWED_USERS` key so the exported Discord auth scope matches the current image contract.

- **Hermes HUD healthcheck**: Switched the Hermes container health probe to use in-container `curl` against `http://127.0.0.1:7681/` so the check follows the upstream HUD endpoint without embedding host-only Nix store paths that do not exist in the image-seeded `/nix`.

- **Develop agent-browser engine pin**: The managed `agent-browser` wrapper
  now defaults `AGENT_BROWSER_ENGINE=chrome` unless callers override it so
  local browser automation keeps using the profile-capable Chrome engine even
  when upstream auto-launch heuristics drift toward Lightpanda.

- **NZBGet UsenetPrime retirement**: Removed the unused `eu.usenetprime.com` backup server from the managed NZBGet config, dropped the retired `NZBGET_SERVER2_*` entries from the local plaintext secret mirror, and reconciled `chill-penguin` so live NZBGet state stops referencing the dead provider.

- **Develop OpenSpec telemetry opt-out**: The managed `openspec` wrapper now
  exports `DO_NOT_TRACK=1` and `OPENSPEC_TELEMETRY=0` by default so successful
  `openspec` commands stop printing harmless PostHog flush stack traces on
  hosts where telemetry egress is blocked.

- **Hermes pyLoad and n8n secret readiness**: Make Hermes wait for
  `pyload-secrets` and `n8n-secrets` before generating
  `/srv/apps/hermes/runtime.env`, and rerun the runtime env sync when either
  secret file changes so bundled utilities keep receiving the current pyLoad
  and n8n credentials.

- **Hermes utility env projection**: Reduced the Hermes container secret surface to `hermes-secrets` plus a generated `/srv/apps/hermes/runtime.env`, projected only the required utility-facing auth values from service-local secret or runtime files, added the missing internal utility URLs including Changedetection, Chaptarr, PriceBuddy, RSS-Bridge, and Synology, and now supply upstream with the generic single-agent Discord and webhook inputs it expects while leaving browser defaults unset so no repo-managed `BROWSER_CDP_URL` or `BROWSER_*_CDP_URL` values are emitted.

- **Synology NFS hard mounts**: Switched the managed Synology NFS mounts on
  `chill-penguin` and WSL hosts from `soft` to `hard` so transient server or
  network stalls stop surfacing as client-side I/O errors during file copies.

- **VueTorrent tunnel binding**: Reconciled qBittorrent's bound interface
  address to Gluetun's live `tun0` IPv4 in the Gluetun monitor, so qBittorrent
  stops getting stuck in a disconnected state after VPN restarts or namespace
  changes when binding by interface name alone is insufficient.

- **VueTorrent startup binding**: Prime `qBittorrent.conf` with Gluetun's live
  `tun0` IPv4 in `podman-vuetorrent` pre-start so qBittorrent no longer boots
  with the previous tunnel address and spends its first restart window unable
  to bind after Gluetun server changes.


- **Develop Gemini maintenance**: Removed the deprecated `experimental.plan` key from the generated develop-host Gemini system settings so managed Gemini launches stop warning about read-only stale config, and added `bash` to the maintenance runtime inputs so npm and npx subprocesses can spawn `sh` reliably during `ghostship-agent-maintenance`.

- **Develop Agent Deck maintenance and WSL web service**: Expose `agent-deck` through the repo-managed wrapper path, let `ghostship-agent-maintenance` refresh it from the latest upstream release, and keep the WSL-only `agent-deck-web` user service on `127.0.0.1:8420`.
- **Develop Workmux removal**: Removed the repo-managed `workmux` package and
  its known user-home artifacts from the supported develop-host workflow.
- **Develop Codex hook cleanup**: Extend the develop-host workmux cleanup to remove the stale `workmux set-window-status ...` commands from `~/.codex/hooks.json`, preserve unrelated valid hooks, warn on malformed hook JSON, and require a Codex or Agent Deck session restart after the relevant rebuild or switch if an old session was still holding the stale state.
- **OpenSpec Ghostship overrides**: `propose` now creates or reuses the change worktree before planning and ends
  with a detailed overview of the proposed change, `apply` now reports completed
  work, proposal updates, and issues found during apply, and `archive` now ends
  with suggested next issues or follow-up work after cleanup.

- fix(self-hosted): pin Gluetun to the live-benchmarked best PIA region, dynamically enumerate that region's current WireGuard servers at selector time, and only fall back to the global PF pool if the primary region disappears

- fix(self-hosted): use Gluetun's native container healthcheck, make Gluetun namespace dependents follow service restarts with `PartOf`/`Requires`, and switch VueTorrent to a local WebUI health probe instead of external `google.com`

### Changed
- **Develop Workmux packaging**: Added a repo-managed `workmux`
  package to the shared develop Home Manager profile through the local Nix
  overlay so develop hosts get declarative tmux-first worktree orchestration
  without relying on the upstream installer or `cargo install`.
- **Hermes runtime contract**: Aligned the `chill-penguin` Hermes host module with the current single-agent `ghostship-hermes` contract by letting the image-owned startup service and mutable-tooling timer drive internal boot ordering, treating `/home/hermes/.hermes` as the authoritative managed runtime surface, and following the upstream-generated `TERMINAL_CWD=/workspace` root env contract.
- **PyLoad health checks**: Switched the `pyload-ng` container health probe
  from `GET /api` to `GET /favicon.ico` because the current upstream image now
  returns `401 UNAUTHORIZED` on `/api`, which left Podman health checks
  permanently failing and blocked clean NixOS activation.
- **agent-browser bootstrap**: Stopped passing `--with-deps` during develop-host `agent-browser` runtime bootstrap; the Nix wrapper already supplies the needed shared libraries, so maintenance now treats those system dependencies as already packaged instead of attempting unsupported distro package-manager bootstrapping.
- **Codex skill-creator override**: Renamed the shared vendored
  `skills-creator` entry back to `skill-creator`, refreshed the repo-managed
  copy from `vercel-labs/agent-browser` `v0.9.3`, and now reassert the Codex
  built-in `~/.codex/skills/.system/skill-creator` path as a managed symlink to
  `~/.agents/skills/skill-creator` during develop-profile activation and
  `ghostship-agent-maintenance`.
- **Hermes root skill seeds**: Replaced the retired profile-local Hermes `skill-creator` seed copies with one root seed source under `modules/self-hosted/hermes-seeds/skills/skill-creator/`, and `podman-hermes` now seeds `/srv/apps/hermes/home/seeds/skills/skill-creator/` only when that runtime-owned directory is missing while normalizing the copied tree to writable `apps:apps` ownership and permissions.
- **Gluetun PIA WireGuard selector**: Migrated `chill-penguin` Gluetun from native PIA OpenVPN to Gluetun's custom-provider WireGuard path, added a daily PF-capable PIA server selector that caches the preferred winner under `/srv/apps/gluetun/pia-wireguard-selection.json`, regenerated the runtime env at Gluetun startup, kept PIA VPN-side port forwarding on the persisted `/srv/apps/gluetun` state mount, and updated the monitor to use Gluetun's generic `/v1/portforward` control route while still reconciling qBittorrent/VueTorrent after startup and reconnects.
- **Gluetun selector fast-start benchmark flow**: Renamed the helper to a stable `gluetun-pia-selector` binary, changed `podman-gluetun` startup to trust the cached winner or do only a provisional latency pick, pinned selection to Vancouver, added a post-boot plus 8-hour background selector cycle, benchmarked the top 10 Vancouver port-forward-capable servers with bounded generic HTTPS pulls through temporary Gluetun tunnels, and only restart Gluetun when a challenger is materially faster than the current cached winner.
- **Hermes root SOUL seed**: Replaced the retired profile-local persona files with one root `modules/self-hosted/hermes-seeds/SOUL.md` source, and `podman-hermes` now seeds `/srv/apps/hermes/home/seeds/SOUL.md` only when that runtime-owned file is missing so existing operator edits remain preserved after first seed.
- **Chaptarr book stack**: Added a repo-managed Chaptarr service to the `chill-penguin` arr stack with persisted config, shared `/downloads` access for both torrent and usenet flows, Homepage visibility, and declarative Muximux placement after Bazarr and before `n8n`. Grimmory now mounts both `/mnt/share/Library/Books` and `/mnt/share/Library/Audiobooks` so it remains the first-class consumption surface for the shared library roots, while the public `chaptarr.ghostship.io` route stays part of the external Cloudflare/tunnel workflow.
- **Develop GitHub CLI baseline**: Added `gh` to the shared develop Home
  Manager package set so every develop-profile host gets the GitHub CLI by
  default.
- **Develop Agent Deck packaging**: Added a repo-managed `agent-deck`
  package to the shared develop Home Manager profile through the local Nix
  overlay so develop hosts get declarative multi-agent orchestration tooling
  without using the upstream installer.
- **Bootstrap WSL hostname handling**: `bootstrap.sh` is now tracked as an
  executable script and falls back from `hostnamectl` to `hostname`, avoiding
  the unsupported WSL2 systemd-hostname failure while still changing the live
  hostname during bootstrap. It now also requires an explicit hostname argument
  and requires being run through `sudo`. It emits the matching
  `nixos-rebuild switch --flake .#<hostname>` command and a `nix-shell -p git`
  hint alongside the bootstrap JSON. Durable hostname persistence remains
  declarative.
- **Develop agent maintenance**: Replaced the launch-time `npx` preflight flow
  for `codex`, `gemini`, and `opencode` with installed user-local agent CLIs
  under `/home/nixos/.local/share/ghostship-agent-tools/npm`, added a
  boot-triggered plus 4-hour persistent `ghostship-agent-maintenance` systemd
  timer to upgrade those CLIs and refresh shared skills, Gemini extensions,
  `agent-browser`, and OpenCode's free OpenRouter config, and simplified the
  launchers down to approval-default injection plus direct exec of the
  installed binaries.
- **WSL Nix build fanout**: WSL hosts now cap `nix.settings.cores` at `4` so
  each daemon-dispatched build job cannot claim all reported CPU threads and
  recreate the same memory-pressure stalls inside an `8`-job queue.
- **Login descriptor headroom**: Added a shared soft `nofile` login limit of
  `65536` so shell-heavy local workflows have more file descriptor headroom
  before hitting per-session limits.
- **Global `rg` availability**: Added `ripgrep` to the shared
  `environment.systemPackages` baseline so server-role hosts such as
  `chill-penguin` have `rg` available out of the box.
- **CloakBrowser managed profile set**: Replaced the old default `Direct`
  and `VPN` manager profiles with repo-managed `assistant`, `operations`,
  `supervisor`, and `Changedetection` profiles, and added a host-managed
  keepalive so the `Changedetection` profile is relaunched automatically when
  the manager stays healthy but that profile stops.
- **n8n orchestration stack**: Added a single SQLite-backed `n8n` service for `chill-penguin`, exposed it to Hermes over `ghostship_net`, documented the dedicated `N8N_API_KEY` handoff through `hermes-secrets`, added Homepage visibility, and declared the Muximux dropdown placement immediately after Bazarr with a documented one-time live reorder step on the host.
- **OpenSpec worktree handoff**: The develop-host `openspec` wrapper now keeps
  proposal/design/tasks work on `main`, moves worktree creation or reuse to
  `apply` with the `.worktrees/<name>/` path, and treats `archive` as the step
  that reconciles any matching change worktree back into `main`, commits the
  archive move, and removes the worktree.
- **WSL Nix daemon concurrency**: WSL hosts now cap `nix.settings.max-jobs`
  at `8` instead of inheriting `auto`, which was resolving to `22` on
  `launch-octopus` and letting concurrent flake shells, agent sessions, and
  host builds push `nix-daemon` into multi-gigabyte memory spikes and socket
  stalls.
- **Personal OpenSpec workflow**: Develop hosts now reapply append-only
  Ghostship propose/apply/archive snippets after both `openspec init` and
  `openspec update` so upstream workflow files stay intact while
  main-first planning, root-cause-first debugging, and
  worktree-reconcile-before-archive guidance
  survive refreshes without extra OpenSpec config files.
- **RomM proxy base-path fix**: Muximux's same-origin `/romm/` proxy now
  injects a real document `<base href="/romm/">` for RomM before the app
  boots, which keeps current and future bundles on the correct router base
  even when they ship an empty Vite env object instead of a rewritable
  `BASE_URL` literal. The proxy also now handles RomM's leaked
  `/ws/socket.io/` root websocket path instead of returning a Muximux-side
  `404`.
- **Hermes whole-home runtime**: Updated Hermes to follow the upstream whole-home image contract by mounting `/srv/apps/hermes/home` at `/home/hermes`, `/srv/apps/hermes/workspace` at `/workspace`, and a seeded host path `/srv/apps/hermes/nix` at `/nix` so the bundled Nix store survives container replacement without being hidden behind an empty mount.
- **Hermes `/nix` reseed guard**: Hermes startup now compares the persisted `/srv/apps/hermes/nix` store with the current `ghostship-hermes:latest` system closure and refreshes the mount when that closure is missing, preventing stale `/nix` data from masking the image's bootable store after upstream image updates.
- **Muximux service placement**: Removed Honcho from the generated Muximux tile
  list, moved PriceBuddy back into the Muximux dropdown directly after Bazarr,
  and keep the generated dashboard layout aligned with the retired Honcho
  stack.
- **Honcho retirement**: Removed the Honcho self-hosted stack, dropped Hermes'
  `HONCHO_*` integration wiring and shared Honcho compatibility-state
  management, removed Homepage Honcho entries, and removed the stale
  `litellm-secrets` declaration now that the service is retired.
- **Homepage stale-entry pruning**: Homepage activation now explicitly deletes
  stale `Honcho`, `Honcho Redis`, and `Honcho DB` entries from `services.yaml`
  after `ghostship-config set` so retired services do not linger in the live UI.
- **PriceBuddy token verification**: Normalized the managed
  `pricebuddy-agent.env` bearer rewrite so repeated post-start runs preserve a
  single `id|token` pair, and added host-managed post-start checks for the app
  env files, scraper reachability, and final token format without conflating
  known upstream auth-route or Cloudflare target issues with Ghostship runtime
  wiring.
- **OpenCode programming free-model refresh**: The develop-host `opencode`
  wrapper now refreshes a generated OpenCode config once per UTC day from
  OpenRouter's ranked programming free-model frontend endpoint, stores that
  generated config under the user's state directory, exports `OPENCODE_CONFIG`
  to it at launch, sources the free programming models from that endpoint, and
  rewrites the generated OpenCode model display labels from `(free)` to
  `(ghostship-free)`. The static OpenRouter model maps were removed from both
  Nix-managed OpenCode config paths, which now only retain the explicit
  `permission = "allow"` default.
- **Develop auth cache policy**: Moved the managed `ssh-agent` setup into the
  develop Home Manager profile, switched it to a fixed `/run/user/1000/ssh-agent`
  socket with a `12h` key lifetime, removed the brittle WSL-only post-start
  parser that could leave the user service failed, and made develop-host
  `sudo` credential caching global with a `12h` timeout so fresh agent PTYs do
  not constantly re-prompt while server-only hosts keep the stricter default
  scope.
- **Hermes native image entrypoint**: Removed the repo-side Hermes startup
  shim, entrypoint override, command override, and separate `.honcho` bind
  mount so `chill-penguin` follows the image's native
  `/usr/local/bin/ghostship-hermes-runtime entrypoint` contract while the
  current workstation layout owns the persisted `/opt/data`, `/workspace`, and
  `/nix` mounts.
- **Develop agent launcher defaults**: Develop-host `codex`, `gemini`, and
  `opencode` now declare explicit YOLO or allow-all execution defaults instead
  of relying on mixed upstream behavior; Gemini now applies YOLO through its
  wrapper because upstream `settings.json` no longer accepts that mode.
- **Muximux RomM embedding**: Switched Muximux's RomM tile to a same-origin
  `/romm/` reverse proxy and now install a managed Muximux nginx vhost that
  proxies RomM by service name on `ghostship_net`, because the public
  `romm.ghostship.io` hostname is Cloudflare Access-protected and not a stable
  iframe target.
- **RomM startup hook removal**: Removed the stale `podman-romm` post-start
  bundle rewrite after validating that the upstream RomM `4.8.0` image starts
  cleanly without it; the failing patch target was the source of the live
  startup wedge.
- **RomM iframe shim**: Muximux now injects an iframe-only RomM runtime shim
  ahead of RomM's main module entry instead of rewriting the served RomM bundle
  on disk, and the shim cache-bust is owned by the Muximux config so Chrome can
  be forced onto corrected injection changes without touching RomM assets.
- **OpenSpec init defaults**: The develop-host `openspec` wrapper now injects
  `--tools codex,gemini,opencode --profile core` for `openspec init` unless
  the caller passes explicit `--tools` or `--profile` flags.
- **Shell flake timeouts**: Increased Starship's prompt scan timeout and
  direnv's warning timeout to 30 seconds so slow `use flake` environments have
  more time to initialize before the prompt or warning path gives up.

## [0.1.9] - 2026-04-02

### Removed
- **LiteLLM stack**: Removed LiteLLM and its dedicated Postgres container from the self-hosted stack for now, along with Homepage and Muximux entries and the active `litellm-secrets` declaration. Encrypted secret material in `secrets.yaml` is left untouched until it is intentionally cleaned up.

### Changed
- **Agent memory rewrite**: Rewrote the repo `AGENTS.md` into a shorter
  operating-memory format so it keeps durable repo facts without turning into a
  running debug log, and aligned the shared `home/config/AGENTS.md` preference
  layer with the newer commit/verification/documentation workflow.
- **Shared skill rename**: Renamed the vendored shared `skill-creator` skill to
  `skills-creator` locally while keeping it pinned to the upstream
  `vercel-labs/agent-browser` `skill-creator` package.
- **Python skill defaults**: Updated the shared Python skill to require `src/`
  layout, `uv`, `ruff`, `pytest`, and `basedpyright`, with `ruff format .`,
  `ruff check .`, full-project `pytest`, and full type coverage as the default
  workflow.
- **SSH interaction guidance**: Tightened the shared SSH skill around
  non-blocking tmux-driven remote workflows so prompt-driven commands are
  started in detached tmux sessions and advanced through `capture-pane` plus
  `send-keys`.
- **WSL path guidance**: Updated the shared WSL skill to prefer `/mnt/c/...`
  for Windows files, added `wslpath` conversion guidance, and refreshed the
  PowerShell reference with tested non-interactive patterns for this host,
  including the requirement to use a Windows path with
  `powershell.exe -File`.
- **OpenSpec agent workflow**: Replaced the old Superpowers-based CLI workflow with repo-local OpenSpec scaffolding for Codex/Gemini/OpenCode, exposed an `openspec` CLI wrapper in the shared develop toolchain, and migrated active planning references from `docs/superpowers` to the repo-root `openspec/` tree.
- **Legacy Superpowers cleanup**: Develop-profile activation now removes the old `~/.agents/skills/superpowers`, `~/.gemini/extensions/superpowers`, and `~/.config/opencode/plugins/superpowers` checkouts and prunes Gemini's stale enablement record during activation.
- **Agent launcher preflight**: Standardized the develop-host `codex`, `gemini`, and `opencode` wrappers around a shared `npx` launch flow that refreshes global `skills`, refreshes OpenSpec instructions when launched inside an OpenSpec repo, warns instead of aborting on preflight failures, and keeps Gemini extension updates behind the same warning-only contract.
- **Shared skill curation**: Reduced the repo-managed shared skill inventory to `nix`, `python`, `ssh`, `wsl2`, and the vendored shared `skills-creator` package, removed the local `agent-browser`, `build123d`, and `dispatching-cli-subagents` skills, and rewrote the retained local skills into a leaner modular format aligned with current skills.sh guidance.
- **Flake repo shell**: Added a default Linux `devShell` to the root flake so `.envrc` `use flake`, `direnv`, and `nix develop` all work in the local development environments without changing any host outputs.
- **agent-browser local runtime**: Wrapped the develop-host `agent-browser` command with a Nix-managed browser `LD_LIBRARY_PATH` so Puppeteer's downloaded Chrome can launch on NixOS/WSL instead of failing on missing GTK/NSS/X11/GBM shared libraries.
- **SearXNG direct-network max-open tuning**: Moved SearXNG off the Gluetun network namespace onto `ghostship_net`, switched Hermes to the internal `http://searxng:8080` address, restored the container's default internal port `8080`, replaced the implicit default-engine inheritance with a Nix-managed allowlist plus category/weight overrides, moved SearXNG config generation into `podman-searxng` `preStart` so engine changes restart cleanly, and pruned repeatedly blocked or unstable engines such as Brave, Qwant, Kickass, SolidTorrents, PodcastIndex, Geizhals, Tootfinder, and Semantic Scholar from the live search surface.
- **SearXNG live tuning follow-up**: Re-ran the public Access-protected SearXNG instance through iterative API and browser probes, removed engines that still failed or degraded quality off VPN (`annas archive`, `mojeek news`, `qwant*`, plain `duckduckgo`, and the full Brave family), kept stronger contributors like `mojeek`, `google`, `duckduckgo news/images/videos`, `reuters`, `youtube`, `sepiasearch`, and `bt4g`, and added a Google fallback into the `it` category so agent-style infrastructure queries no longer return empty result sets.
- **SearXNG Brave reinstatement**: Re-enabled `brave`, `brave.news`, `brave.images`, and `brave.videos` in the curated engine allowlist because the active search policy now explicitly favors Brave's independent index coverage over the operational cleanliness gained by pruning its rate-limited engine family.
- **SearXNG autocomplete**: Switched the instance autocomplete backend from `duckduckgo` to `bing` after live benchmarking showed Bing suggestions were faster and more complete for agent-style queries than DuckDuckGo, Startpage, Wikipedia, Mwmbl, or Brave.
- **SearXNG category tuning**: Rebalanced the curated engine set around the current agentic-search priorities by enabling Bing web search, Repology package search, Apple Maps, Google Play Apps, Erowid, Moviepilot, and additional icon engines, removing `hoogle` and `gentoo`, promoting Reuters/Google News/YouTube/Wikipedia in their respective categories, and narrowing package, software-wiki, app, movie, and icon engines to the categories where they provide the strongest signal.
- **SearXNG category tuning follow-up**: Dropped `svgrepo` again after live icon probes immediately hit rate limits, and raised per-engine timeouts on the slower app, package, icon, and Erowid sources so the engines explicitly kept for those categories have a chance to contribute before the global request cutoff.
- **SearXNG package and other cleanup**: Removed `duckduckgo weather` after repeated live `400` errors on non-weather queries, pushed package search harder toward `pypi`, `repology`, and Alpine, and demoted the long tail of ecosystem-specific package registries into `it` so package-name lookups are less dominated by unrelated exact-name matches.
- **SearXNG PyPI engine override**: Replaced the upstream PyPI HTML scraper with a local exact-match engine mounted into the container that uses PyPI's JSON API, and marked curated engines `inactive = false` so default-off engines like `repology` can be activated reliably from the repo-managed engine list.
- **SearXNG weather source swap**: Replaced `openmeteo` with `wttr.in` in the curated weather category after live tests showed the old weather path returning no useful answers while wttr's upstream JSON endpoint remained healthy.
- **Global Bash defaults**: Moved Bash completion and baseline readline/history behavior into the shared NixOS layer so all Bash shells, including root, now get `bash-completion`, case-insensitive ambiguous completion, cleaner history handling, incremental history writes, and `checkwinsize` by default.
- **CloakBrowser healthcheck**: Replaced the `wget --spider` Podman probe with a Python `urllib` GET against the local manager endpoint, because the current image on `chill-penguin` serves the app correctly but still reports repeated false-negative healthcheck failures under the `wget` runner.
- **Host role refactor**: Added explicit `ghostship.host.roles` booleans, split WSL into its own top-level module area, and moved Home Manager into `base`, `server`, `develop`, and `wsl` profile layers. Server-role hosts now default to `bash`, develop-role hosts default to `fish`, and the package split is cleaner between system packages and user packages.
- **Flake host construction**: Consolidated repeated `nixosSystem` wiring behind a shared `mkHost` helper and removed the unused `nixpkgs-unstable` input.
- **Self-hosted inventory consistency**: Reordered the flat self-hosted module inventory into documented category blocks and removed the last non-Plex host port exposure by keeping CloakBrowser on internal networking with the standard Podman healthcheck cadence.
- **Workflow docs**: Rewrote the local workflow guidance to match the actual repo workflow instead of the old `plan.md`-driven process.
- **Docker Hub auth support**: Added a `dockerhub-secrets` bundle and runtime auth-file generation so the self-hosted Podman stack can authenticate Docker Hub pulls instead of hitting rate limits during restart-time updates.
- **Docker Hub placeholder fallback**: The Docker Hub auth hook now writes an empty `auths` file when the secret bundle still contains the placeholder values, so public pulls can continue anonymously instead of failing the whole stack during deploy.
- **Podman auto-update**: Every self-hosted OCI container now sets `pull = "always";` and carries Podman's registry auto-update label, and a daily native `podman auto-update` timer refreshes changed images in place. Failed restarts are still surfaced through systemd/journal for now.
- **WSL `/mnt/z` NFS mount**: Replaced the WSL-only `Z:`-backed SMB mount script with a direct Synology NFS automount at `/mnt/z`, reusing the tuned `chill-penguin` mount options so access is faster on-network and fails gracefully when the NAS is unavailable or the host is off-network.
- **WSL `/mnt/z` activation reset**: WSL activation now stops the `/mnt/z`
  automount and unmounts any live NFS mount before reloading the generated
  mount units, so host switches do not fail on stale `/mnt/z` mount state.
- **PyLoad healthcheck**: Switched the PyLoad container health probe from `/` to `/api`, because the current web UI config can leave the root path in an internal redirect loop even while the service itself is healthy.
- **LiteLLM database startup**: LiteLLM now writes a runtime env file that maps the existing secret bundle onto the `DATABASE_URL` variable the upstream image actually uses, and the Postgres side now writes a real `POSTGRES_PASSWORD` runtime env file instead of passing the literal `env:LITELLM_DB_PASS` marker through to the container. The LiteLLM Postgres unit also reconciles the `litellm` role password from secrets on startup so older initialized volumes converge to the current secret. This allows Prisma migrations to run and fixes the LiteLLM UI's `Not connected to DB!` login failure on `chill-penguin`.
- **LiteLLM ChatGPT subscription wiring**: LiteLLM now mounts a persistent ChatGPT OAuth token directory and ships a proxy config for the current `chatgpt/` provider models (`gpt-5.4`, `gpt-5.4-pro`, `gpt-5.3-codex`, `gpt-5.3-codex-spark`, `gpt-5.3-instant`, and `gpt-5.3-chat-latest`) so ChatGPT-subscription-backed models can be added without API keys and keep their OAuth session across container restarts.
- **Native Nix docs**: Updated the repo documentation and agent instructions to use native `nix`, `nixos-rebuild`, and `switch-to-configuration` commands instead of `nh`.
- **CloakBrowser native origin patch**: Replaced the custom aiohttp proxy with a startup patch against the upstream manager's `AuthMiddleware`, so the app now strips incoming `Origin` headers at the ASGI boundary and keeps the native VNC/CDP WebSocket handling intact.
- **PyLoad config application**: `ghostship-config` now recognizes `pyload.cfg` as PyLoad's typed config format and updates the existing section/key lines in place, so the PyLoad activation settings actually take effect instead of being appended as invalid `section.key=value` lines.
- **PyLoad NFS startup**: Restored the LinuxServer image's supported root-run startup mode and replaced the broken `fix-attrs/down` override with a narrow patch to `init-pyload-config/run` that keeps `/config` ownership handling but skips the `/downloads` `chown` on the NFS share.
- **Documentation Migration**: Merged `GEMINI.md` into `AGENTS.md` and removed devenv references from `README.md`. Added self-hosted services overview.
- **ghostship-config YAML Upserts**: Fixed Homepage-style list-group creation in `ghostship-config.py` so paths like `[Utilities].[OmniTools].icon` create missing groups with the correct list container and pass the script self-tests again.
- **Homepage resources widget typing**: The Homepage activation script now writes the resources widget's `cpu`, `memory`, and `network` options as native YAML booleans instead of quoted strings, which restores the network bandwidth section instead of showing `API Error`.
- **Homepage network stats mount**: Homepage now keeps the resources widget pinned to `end0` on `chill-penguin` and mounts only the network-related sysfs paths needed to resolve `end0`'s host symlink target, avoiding the broken `/sys/class/net` links without exposing the wider `/sys` tree that made Homepage's disk probe fail.
- **RomM iframe startup hook**: Added a `podman-romm` `postStart` hook that patches RomM's routed iframe crash trigger in the active hashed frontend bundle and cleans up temporary debug assets created during live investigation.
- **VueTorrent LSIO integration**: Replaced the hand-managed VueTorrent zip extraction with the official `ghcr.io/vuetorrent/vuetorrent-lsio-mod` on the LinuxServer qBittorrent image. The service no longer forces `-u 3000:3000`, the stale manual `/srv/apps/vuetorrent/ui` state is removed during activation, and qBittorrent is configured to use `/vuetorrent`, avoiding the recurring `Unacceptable file type, only regular file is allowed.` failure.
- **Gluetun PIA compatibility**: The `podman-gluetun` `preStart` hook now mirrors legacy `OPENVPN_PASS` into `OPENVPN_PASSWORD` before writing `/run/secrets/gluetun-runtime.env`, keeping the current Gluetun image compatible with the existing secret bundle on `chill-penguin`.

### Added
- **SSH workflow references**: Added shared SSH skill references for common
  tmux background patterns and interactive SSH command patterns.
- **Honcho stack**: Added a local Honcho stack for Hermes using one s6-supervised app container plus database and Redis sidecars, wired Hermes to generate `~/.honcho/config.json` at startup, and added Homepage and Muximux entries.
- **RSS-Bridge and PriceBuddy**: Added internal-only RSS-Bridge and PriceBuddy services to the Ghostship stack, wired both into Homepage's Services column, added the PriceBuddy MySQL/scraper sidecars, and sourced the persistent PriceBuddy agent API token from the `pricebuddy-secrets` bundle.
- **PriceBuddy env bootstrap**: Moved PriceBuddy env-file generation into the service start path so the MySQL and app containers can see `/srv/apps/pricebuddy/{pricebuddy.env,pricebuddy-db.env,pricebuddy-agent.env}` reliably after secrets are installed.
- **PriceBuddy bearer format**: The persisted agent token now writes a shell-safe `PRICEBUDDY_API_TOKEN="id|token"` bearer line into `/srv/apps/pricebuddy/pricebuddy-agent.env` so non-interactive API calls authenticate correctly.
- **PriceBuddy process env**: Restored PriceBuddy's app `environmentFiles` so the upstream `start-app.sh` sees the DB host and credentials it waits on before Apache starts.
- **Nix command reference**: Added a native Nix command reference under the Nix skill with build-first, no-`sudo`, and `chill-penguin` deployment guidance.
- **Hermes service**: Added a new `ghcr.io/ghostship-io/ghostship-hermes:latest` self-hosted service with Homepage and Muximux entries, internal service URL wiring for the existing stack, RomM/Grimmory secret imports for `*_USER` / `*_PASS`, and a named Podman volume for `/nix` so the image keeps its bundled entrypoint store.
- **ghostship-config Utility**: A self-verifying, idempotent configuration manager for surgical updates to XML, YAML, INI, and KV files. Supports secure secret injection via environment/file references.
- **Pure Surgical Migration**: Migrated all self-hosted services (Sonarr, Radarr, Plex, Homepage, etc.) to a pure surgical configuration model, removing all full-file templates and enforcing the "Ghostship Standard" for identity and privacy.
- **Unified Agent Tooling**: Added a shared `~/.agents`-based skill/instructions model and a Gemini delegation MCP server for repo research and plan generation across Gemini, OpenCode, and Codex.

## [0.1.8] - 2026-03-20

### Removed
- **Agent Browser Skill**: Removed the `agent-browser` Gemini skill definition. The `agent-browser-mcp` server remains active for tool-based browser automation.

## [0.1.7] - 2026-03-19

### Added
- **SSH Skill**: Created a new Gemini skill for advanced remote server management based on `mcp-ssh-manager`.
- **Agent Browser Skill**: Created a new Gemini skill for token-efficient browser automation via `agent-browser-mcp`.

### Changed
- **SSH MCP**: Swapped `@aiondadotcom/mcp-ssh` for `mcp-ssh-manager` by `bvisible` for enhanced remote management capabilities.
- **Browser Automation**: Swapped `browser-use` for `agent-browser-mcp` to leverage token-efficient accessibility trees and semantic locators.

## [0.1.6] - 2026-03-18

### Changed
- **Gemini Template**: Overhauled `home/config/gemini.md` to follow 2026 Open Source Software (OSS) best practices.
- **Workflow**: Updated Conductor `workflow.md` to prioritize autonomous verification and report results.
- **Policies**: 
    - Established "Open Source Excellence" as a baseline for all projects.
    - Added "Continuous Learning" as a HIGH PRIORITY directive to record mistakes and new discoveries in project memory.
    - Prohibited `save_memory` in favor of centrally managed cross-project memory via user prompts.
    - Prioritized `nh` for all supported system operations.
    - Updated TDD policy to prioritize unit/integration tests for applications and test environments for infra/config.

## [0.1.5] - 2026-03-11

### Added
- **Python Skill**: Added a new Gemini skill for modern Python development using `uv`, Nix flakes, `black`, `isort`, and `pyright`/`pylance`.

## [0.1.4] - 2026-03-11

### Added
- **SSH MCP**: Added `mcp-ssh` for remote task execution via `@aiondadotcom/mcp-ssh`.
- **Browser Automation**: Switched from `playwright` to `browser-use` MCP using `mcp-browser-use`.
- **Gemini Extension**: Installed `richardcb/oh-my-gemini` for advanced workflow orchestration.
- **System Packages**: Added `uv` to common system packages for MCP runners.

## [0.1.3] - 2026-03-11

### Changed
- **Gemini Config**: Enabled the experimental `plan` mode in `modules/develop/gemini.nix`.

## [0.1.2] - 2026-03-10

### Added
- **Host Bootstrap Script**: Implemented `bootstrap.sh` for initial host setup, age key generation, and hardware configuration capture.
- **Host Registration**: Added `register-host` CLI tool to automatically integrate new hosts (updating `.sops.yaml`, creating host directories, and re-encrypting secrets).
- **Documentation**: Added comprehensive "Bootstrap a New Host" section to `README.md`.

## [0.1.1] - 2026-03-09

### Added
- **System Skill Update**: Added `nh os build` to the Command Reference Matrix for testing NixOS configurations.

## [0.1.0] - 2026-03-09

### Added
- **Automated Maintenance**: Configured automated daily Nix garbage collection and system generation pruning (keeping 7 days) in `modules/common/default.nix`.
- **Maintenance Documentation**: Added a "Maintenance & Cleanup" section to `README.md` with instructions for `nh clean`.
- **System Skill Update**: Reinforced the "Documentation Mandate" and added "Versioning & Conductor" autoincrement logic in `home/config/skills/system.md`.
- **Version Tracking**: Created the `VERSION` file and initialized it at `0.1.0`.
- **Initial Changelog**: Created `CHANGELOG.md` to track project evolution.

### Changed
- **Config Apply Workflow**: Updated documentation to prefer `nh os switch` over `nixos-rebuild`.
- **Memory Policy**: Updated `AGENTS.md` to track the new maintenance automation.
