# Provider zero-data-retention and no-training state

This page records the strongest available data-retention and training control for
every inference provider Ghostship uses, what turned it on, and the evidence for
it. `scripts/provider-zdr-doctor` re-checks the machine-readable parts and flags
drift. Account toggles are read back in the provider console; the date is the day
of that read-back.

No provider's model list is filtered or allowlisted to obtain ZDR. When a
provider's own ZDR mode removes models, that is recorded in the detail column, not
worked around.

State meanings:

- **ON** — the strongest control the provider offers on the current plan is
  enabled, or the provider's own default is zero retention and no training.
- **NOT AVAILABLE** — the provider offers no zero-retention or no-training control
  on the current plan, and nothing was changed.
- **BLOCKED** — a control exists but needs an owner sign-in, a plan or billing
  change, a contract, or an unverified console path. Nothing was bypassed.
- **OWNER DECLINED** — the remaining control needs a paid plan, contract,
  billing change, or team the owner declined. Nothing was changed.

| Provider | Surface | Mechanism | State | Evidence | Checked | Detail |
| --- | --- | --- | --- | --- | --- | --- |
| Command Code GOAT | T3 OpenCode | `x-cmd-zdr: 1` on every OpenCode request; ZDR-capable upstream required | ON | `packages/t3code/command-code/provider.json` https://commandcode.ai/docs/resources/zdr | 2026-10-24 | Enforced by `provider.json` and the startup provider merge; the API key comes from the projected secret. A model with no ZDR-capable upstream fails instead of falling back. The catalog is not filtered for ZDR. |
| Anthropic Claude Code | T3 `claudeAgent` | Consumer privacy controls: Help improve our AI models OFF and Location metadata OFF; commercial/API no training by default; ZDR by Claude for Enterprise agreement | ON | https://code.claude.com/docs/en/data-usage https://code.claude.com/docs/en/zero-data-retention https://claude.ai/settings/data-privacy-controls | 2026-10-24 | Live read-back: "Help improve our AI models" false and "Location metadata" false on the signed-in consumer account. ZDR is declined: it needs Claude for Enterprise and Anthropic enablement. The managed setup also adds the nonessential-traffic, telemetry, error-reporting, and feedback opt-outs; it does not create ZDR. |
| OpenAI Codex | T3 `codex` | ChatGPT Data Controls: Improve the model for everyone OFF; API/Codex commercial training off by default; ZDR for eligible API customers | ON | https://help.openai.com/en/articles/7730893-data-controls-in-chatgpt https://openai.com/index/offering-zero-data-retention-for-frontier-models/ | 2026-10-24 | Live read-back shows the training switch off. No Codex Cloud environments are configured. ZDR is not offered on the personal plan. |
| OpenCode Go and Zen | T3 `opencode` and free pool | Provider zero-retention agreements; named free-model exceptions | ON | https://opencode.ai/zen https://opencode.ai/v2/docs/console/models/#privacy | 2026-10-24 | Provider default. Exceptions that may collect or train: Big Pickle, Flint 40B Free, MiMo-V2.6-Flash Free, and the NVIDIA Nemotron free endpoints. Those models are recorded, not filtered out here. |
| Ollama Cloud | T3 and free pool | Provider processes prompt/response content transiently and does not train on it | ON | https://ollama.com/privacy | 2026-10-24 | Provider policy; there is no account toggle. |
| Google Antigravity | T3 `antigravity` | `agy` /config > Enable Telemetry off; the choice is saved with the Google account | ON | https://antigravity.google/docs/settings https://antigravity.google/schemas/v1/settings.json | 2026-10-24 | `agy` `/config` read-back on 2026-10-24 shows "Enable Telemetry off" for the signed-in Google AI Pro account. The deprecated `enableTelemetry` settings.json key is not read; the CLI removes it. No GUI is needed. |
| Google AI Studio / Gemini API | Free pool `google` | Paid Gemini API does not train; unpaid quota and AI Studio may use content and have no opt-out | OWNER DECLINED | https://ai.google.dev/gemini-api/terms | 2026-10-24 | Owner declined paid Gemini API quota. The pool remains on unpaid quota, where Google may use content and offers no opt-out. |
| Grok / xAI | T3 `grok` and xAI API | Data Controls: Improve the Model OFF and Personalize Grok using X OFF; Grok CLI codebase upload/sharing off; team ZDR declined | ON | https://docs.x.ai/developers/faq/security https://grok.com/?_s=data `~/.grok/settings_cache.json` | 2026-10-24 | Live read-back: "Improve the Model" false and "Personalize Grok using X" false on the signed-in individual account. CLI settings read back `disable_codebase_upload=true` and `sharing_enabled=false`. Team ZDR is declined: it needs a team, which the owner does not want to create. |
| OpenRouter | Free pool `openrouter` | Account privacy ZDR for all five scopes, strict Google option, all training/publish/discount toggles OFF; model-catalog filter OFF | ON | https://openrouter.ai/docs/guides/features/zdr https://openrouter.ai/settings/privacy | 2026-10-24 | Live read-back: five ZDR scopes true, strict Zero retention only for Google, paid/free training, publish-prompts, and 1% data discount false, model-catalog filter false. The account-level setting covers every request. |
| Groq | Free pool `groq` | Data Controls: Global ZDR | ON | https://console.groq.com/docs/your-data https://console.groq.com/settings/data-controls | 2026-10-24 | Live read-back: Global ZDR true; Inference APIs ZDR true; batch and fine-tuning switches disabled by ZDR. |
| Mistral | Free pool `mistral` | API Privacy: Allow API calls to train OFF; Labs models OFF; ZDR on pay-as-you-go only, by request | ON | https://help.mistral.ai/en/articles/455207-can-i-opt-out-of-my-input-or-output-data-being-used-for-training https://help.mistral.ai/en/articles/347612-can-i-activate-zero-data-retention-zdr https://admin.mistral.ai/plateforme/privacy | 2026-10-24 | Live read-back: training toggle false, Labs models false. The owner declined the paid ZDR path; it needs pay-as-you-go and a support request. |
| NVIDIA | Free pool `nvidia` | API trial logs and may use data to improve products; no self-service toggle | NOT AVAILABLE | https://assets.ngc.nvidia.com/products/api-catalog/legal/NVIDIA%20API%20Trial%20Terms%20of%20Service.pdf https://opencode.ai/v2/docs/console/models/#privacy | 2026-10-24 | The pool uses free NVIDIA endpoints; the trial terms log sessions for security and improvement. |
| Cloudflare Workers AI | Free pool `cloudflare-workers-ai` | Zero retention and no training by provider policy; no toggle | ON | https://developers.cloudflare.com/workers-ai/platform/data-usage/ | 2026-10-24 | Provider commitment for standard inference; stateful features are not used by the pool. |
| Cohere | Free pool `cohere` | Dashboard Data Controls training opt-out; ZDR by enterprise request | OWNER DECLINED | https://cohere.com/enterprise-data-commitments https://dashboard.cohere.com/data-controls | 2026-10-24 | Owner declined the payment method needed for Data Controls and the enterprise ZDR request. Data Controls currently returns "You need to have a payment method on file". |
| Kilo | Free pool `kilo` and `kilo-keyed` | No self-service ZDR; gateway routes through OpenRouter under Kilo's account | NOT AVAILABLE | https://kilo.ai/privacy https://kilo.ai/gateway | 2026-10-24 | The account-level OpenRouter ZDR does not apply to traffic routed through Kilo. Kilo publishes no per-account ZDR control. |
| Vercel AI Gateway | Free pool `vercel` | Team-wide ZDR or per-request `providerOptions.gateway.zeroDataRetention` | OWNER DECLINED | https://vercel.com/docs/ai-gateway/security-and-compliance/zdr https://vercel.com/dashboard | 2026-10-24 | Owner declined the Pro or Enterprise plan needed for either ZDR path. The team remains on Hobby. |
| OVHcloud AI Endpoints | Free pool `ovh` | Provider policy: data is not stored or shared during or after model use | ON | https://docs.ovhcloud.com/en/guides/public-cloud/ai-machine-learning/ai-endpoints-capabilities | 2026-10-24 | The anonymous lane has no account-level control; the provider states no storage or sharing. |
| Poolside | Free pool `poolside` and Poolside-served routes | Training opt-out recorded in the pool catalog; platform ends 2026-10-31 | BLOCKED | https://poolside.ai/legal/privacy `modules/self-hosted/inference-pool.json` | 2026-10-24 | The pool catalog records the opt-out, but no Poolside console was reachable to read it back independently. The platform is already scheduled to shut down on 2026-10-31. |
| Z.ai | Free pool `zai` | ZDR is an announced opt-in MaaS feature; no verified self-service path | BLOCKED | https://docs.z.ai/guides/overview/pricing | 2026-10-24 | The console path for the ZDR opt-in was not verified. No claim is made that it is on. Needs an owner/console check. |
| Requesty | Free pool `requesty` | Organization ZDR (Enterprise, irreversible) or per-key logging off; upstream provider policy is separate | OWNER DECLINED | https://docs.requesty.ai/features/data-privacy https://app.requesty.ai/api-keys | 2026-10-24 | Owner declined the enterprise ZDR contract. The key's Logging row is unset and no payload logging is configured. Provider-side retention depends on the upstream. |
| OrcaRouter | Free pool `orcarouter` | Default no body logging; ZDR agreement via sales, not self-service; `X-Orca-ZDR` response header | OWNER DECLINED | https://docs.orcarouter.ai/operations/zero-data-retention https://docs.orcarouter.ai/privacy/provider-retention | 2026-10-24 | Owner declined the signed ZDR agreement. The default keeps metadata only; no request bodies are logged. |
| Upstage | Free pool `upstage` | No API training opt-out found; welcome credit | NOT AVAILABLE | https://www.upstage.ai/privacy-policy/updated-jun-01-2026 | 2026-10-24 | The public policy permits service-improvement processing and publishes no API opt-out. |
| Inception | Free pool `inception` | Enterprise: no training and configurable retention; standard API policy permits improvement | OWNER DECLINED | https://www.inceptionlabs.ai/docs/privacy-policy https://www.inceptionlabs.ai/enterprise | 2026-10-24 | Owner declined the enterprise contract. The free plan remains on the standard policy, which permits service-improvement processing. |
| Hugging Face Inference Providers | Free pool `huggingface` (disabled) | Routing layer stores no request bodies; each upstream provider's policy applies | NOT AVAILABLE | https://huggingface.co/docs/inference-providers/security `modules/self-hosted/inference-pool.json` | 2026-10-24 | The pool disables this provider (`data_policy_approved` false), so it is not dispatched. |

## Repo-managed changes

- `packages/t3code/provider-privacy/setup.py` merges the Claude Code
  nonessential-traffic/telemetry/feedback opt-outs into
  `~/.claude/settings.json` before T3 starts. This reduces logging and telemetry;
  it does not create ZDR, which needs the Anthropic agreement above.
- `scripts/provider-zdr-doctor` checks the table, the Command Code OpenCode route
  environment, the Claude opt-out, the Grok upload setting, the free-pool policy,
  and with `--browser` the OpenRouter, Groq, ChatGPT, Mistral, Claude, and Grok
  account read-backs. `--antigravity` reads the `agy` `/config` panel. It fails
  on a missing required provider, an invalid state, stale evidence, or a live
  state that differs from this table.

## Owner decisions

Completed on 2026-10-24 from the individual accounts and the CLI, without a team,
enterprise plan, or GUI:

- Anthropic: "Help improve our AI models" and "Location metadata" are off. Claude
  for Enterprise ZDR is declined.
- xAI: "Improve the Model" and "Personalize Grok using X" are off on grok.com;
  the Grok CLI codebase upload and sharing are off. Team ZDR is declined.
- Antigravity: `agy` `/config` shows "Enable Telemetry off" for the signed-in
  Google AI Pro account. The deprecated `enableTelemetry` settings.json key is
  not read.

Remaining:

- The owner declined the paid and contract paths: Cohere (payment method and
  enterprise ZDR), Vercel (Pro/Enterprise ZDR), Mistral (pay-as-you-go ZDR),
  Google AI Studio (paid quota), and Requesty, OrcaRouter, and Inception
  (enterprise contracts).
- Z.ai: confirm the console path for the announced ZDR opt-in.
- Poolside: no console was reachable; the catalog opt-out is unverified; the
  platform ends 2026-10-31.
