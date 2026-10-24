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

| Provider | Surface | Mechanism | State | Evidence | Checked | Detail |
| --- | --- | --- | --- | --- | --- | --- |
| Command Code GOAT | T3 ACP | `CMD_ZDR=1` on every native process; ZDR-capable upstream required | ON | `packages/t3code/command-code/provider.json` https://commandcode.ai/docs/resources/zdr | 2026-10-24 | Enforced by `provider.json` and the ACP tests; free models excluded by the existing reviewed policy, not by this work. |
| Anthropic Claude Code | T3 `claudeAgent` | Consumer data-privacy control; commercial/API no training by default; ZDR by Claude for Enterprise agreement | BLOCKED | https://code.claude.com/docs/en/data-usage https://code.claude.com/docs/en/zero-data-retention | 2026-10-24 | Personal browser profile is not signed in to claude.ai; the popup-based Google sign-in cannot complete in one tab. ZDR is not in the standard Enterprise plan and needs Anthropic enablement. The managed setup adds the nonessential-traffic, telemetry, error-reporting, and feedback opt-outs; it does not create ZDR. |
| OpenAI Codex | T3 `codex` | ChatGPT Data Controls: Improve the model for everyone OFF; API/Codex commercial training off by default; ZDR for eligible API customers | ON | https://help.openai.com/en/articles/7730893-data-controls-in-chatgpt https://openai.com/index/offering-zero-data-retention-for-frontier-models/ | 2026-10-24 | Live read-back shows the training switch off. No Codex Cloud environments are configured. ZDR is not offered on the personal plan. |
| OpenCode Go and Zen | T3 `opencode` and free pool | Provider zero-retention agreements; named free-model exceptions | ON | https://opencode.ai/zen https://opencode.ai/v2/docs/console/models/#privacy | 2026-10-24 | Provider default. Exceptions that may collect or train: Big Pickle, Flint 40B Free, MiMo-V2.6-Flash Free, and the NVIDIA Nemotron free endpoints. Those models are recorded, not filtered out here. |
| Ollama Cloud | T3 and free pool | Provider processes prompt/response content transiently and does not train on it | ON | https://ollama.com/privacy | 2026-10-24 | Provider policy; there is no account toggle. |
| Google Antigravity | T3 `antigravity` | Settings > Account > Enable Telemetry OFF | BLOCKED | https://antigravity.google/docs/settings | 2026-10-24 | The choice is saved with the Google account, not in `settings.json`; it needs the owner in the Antigravity app. T3 ACP sign-in is separate from the CLI login. |
| Google AI Studio / Gemini API | Free pool `google` | Paid Gemini API does not train; unpaid quota and AI Studio may use content and have no opt-out | NOT AVAILABLE | https://ai.google.dev/gemini-api/terms | 2026-10-24 | The pool uses unpaid quota. Moving to paid billing is a plan change and was not made. |
| Grok / xAI | T3 `grok` and xAI API | Grok CLI codebase upload off; team-wide ZDR toggle in xAI Console | BLOCKED | https://docs.x.ai/developers/faq/security `~/.grok/settings_cache.json` | 2026-10-24 | CLI settings read back `disable_codebase_upload=true` and `sharing_enabled=false`. The xAI Console team has not been created, so the team ZDR toggle is unavailable; creating a team was not authorized. The CLI `/privacy` code-retention control remains an owner decision. |
| OpenRouter | Free pool `openrouter` | Account privacy ZDR for all five scopes, strict Google option, all training/publish/discount toggles OFF; model-catalog filter OFF | ON | https://openrouter.ai/docs/guides/features/zdr https://openrouter.ai/settings/privacy | 2026-10-24 | Live read-back: five ZDR scopes true, strict Zero retention only for Google, paid/free training, publish-prompts, and 1% data discount false, model-catalog filter false. The account-level setting covers every request. |
| Groq | Free pool `groq` | Data Controls: Global ZDR | ON | https://console.groq.com/docs/your-data https://console.groq.com/settings/data-controls | 2026-10-24 | Live read-back: Global ZDR true; Inference APIs ZDR true; batch and fine-tuning switches disabled by ZDR. |
| Mistral | Free pool `mistral` | API Privacy: Allow API calls to train OFF; Labs models OFF; ZDR on pay-as-you-go only, by request | ON | https://help.mistral.ai/en/articles/455207-can-i-opt-out-of-my-input-or-output-data-being-used-for-training https://help.mistral.ai/en/articles/347612-can-i-activate-zero-data-retention-zdr https://admin.mistral.ai/plateforme/privacy | 2026-10-24 | Live read-back: training toggle false, Labs models false. ZDR is not available on the free plan; enabling it needs pay-as-you-go and a support request, which is a billing change and was not made. |
| NVIDIA | Free pool `nvidia` | API trial logs and may use data to improve products; no self-service toggle | NOT AVAILABLE | https://assets.ngc.nvidia.com/products/api-catalog/legal/NVIDIA%20API%20Trial%20Terms%20of%20Service.pdf https://opencode.ai/v2/docs/console/models/#privacy | 2026-10-24 | The pool uses free NVIDIA endpoints; the trial terms log sessions for security and improvement. |
| Cloudflare Workers AI | Free pool `cloudflare-workers-ai` | Zero retention and no training by provider policy; no toggle | ON | https://developers.cloudflare.com/workers-ai/platform/data-usage/ | 2026-10-24 | Provider commitment for standard inference; stateful features are not used by the pool. |
| Cohere | Free pool `cohere` | Dashboard Data Controls training opt-out; ZDR by enterprise request | BLOCKED | https://cohere.com/enterprise-data-commitments https://dashboard.cohere.com/data-controls | 2026-10-24 | Data Controls returns "You need to have a payment method on file". Adding billing is a plan change and was not made. ZDR also needs an enterprise request. |
| Kilo | Free pool `kilo` and `kilo-keyed` | No self-service ZDR; gateway routes through OpenRouter under Kilo's account | NOT AVAILABLE | https://kilo.ai/privacy https://kilo.ai/gateway | 2026-10-24 | The account-level OpenRouter ZDR does not apply to traffic routed through Kilo. Kilo publishes no per-account ZDR control. |
| Vercel AI Gateway | Free pool `vercel` | Team-wide ZDR or per-request `providerOptions.gateway.zeroDataRetention` | BLOCKED | https://vercel.com/docs/ai-gateway/security-and-compliance/zdr https://vercel.com/dashboard | 2026-10-24 | Live read-back: the team is on Hobby. Both ZDR paths require Pro or Enterprise. Upgrading is a plan change and was not made. |
| OVHcloud AI Endpoints | Free pool `ovh` | Provider policy: data is not stored or shared during or after model use | ON | https://docs.ovhcloud.com/en/guides/public-cloud/ai-machine-learning/ai-endpoints-capabilities | 2026-10-24 | The anonymous lane has no account-level control; the provider states no storage or sharing. |
| Poolside | Free pool `poolside` and Poolside-served routes | Training opt-out recorded on the Poolside account; platform ends 2026-10-31 | ON | https://poolside.ai/legal/privacy `modules/self-hosted/inference-pool.json` | 2026-10-24 | The pool catalog records the opt-out. No console was reachable; the platform is already scheduled to shut down. |
| Z.ai | Free pool `zai` | ZDR is an announced opt-in MaaS feature; no verified self-service path | BLOCKED | https://docs.z.ai/guides/overview/pricing | 2026-10-24 | The console path for the ZDR opt-in was not verified. No claim is made that it is on. Needs an owner/console check. |
| Requesty | Free pool `requesty` | Organization ZDR (Enterprise, irreversible) or per-key logging off; upstream provider policy is separate | BLOCKED | https://docs.requesty.ai/features/data-privacy https://app.requesty.ai/api-keys | 2026-10-24 | Live read-back: the key's Logging row is unset and no payload logging is configured. Organization ZDR is not available on the current plan. Provider-side retention depends on the upstream. |
| OrcaRouter | Free pool `orcarouter` | Default no body logging; ZDR agreement via sales, not self-service; `X-Orca-ZDR` response header | BLOCKED | https://docs.orcarouter.ai/operations/zero-data-retention https://docs.orcarouter.ai/privacy/provider-retention | 2026-10-24 | Default keeps metadata only. A ZDR agreement is a signed contract and was not requested. |
| Upstage | Free pool `upstage` | No API training opt-out found; welcome credit | NOT AVAILABLE | https://www.upstage.ai/privacy-policy/updated-jun-01-2026 | 2026-10-24 | The public policy permits service-improvement processing and publishes no API opt-out. |
| Inception | Free pool `inception` | Enterprise: no training and configurable retention; standard API policy permits improvement | BLOCKED | https://www.inceptionlabs.ai/docs/privacy-policy https://www.inceptionlabs.ai/enterprise | 2026-10-24 | The free plan is on the standard policy. The no-training commitment is an enterprise term. |
| Hugging Face Inference Providers | Free pool `huggingface` (disabled) | Routing layer stores no request bodies; each upstream provider's policy applies | NOT AVAILABLE | https://huggingface.co/docs/inference-providers/security `modules/self-hosted/inference-pool.json` | 2026-10-24 | The pool disables this provider (`data_policy_approved` false), so it is not dispatched. |

## Repo-managed changes

- `packages/t3code/provider-privacy/setup.py` merges the Claude Code
  nonessential-traffic/telemetry/feedback opt-outs into
  `~/.claude/settings.json` before T3 starts. This reduces logging and telemetry;
  it does not create ZDR, which needs the Anthropic agreement above.
- `scripts/provider-zdr-doctor` checks the table, the Command Code ZDR
  environment, the Claude opt-out, the Grok upload setting, the free-pool policy,
  and with `--browser` the OpenRouter, Groq, ChatGPT, and Mistral account
  read-backs. It fails on a missing required provider, an invalid state, stale
  evidence, or a live state that differs from this table.

## Owner decisions

- Anthropic: sign in to the Claude account (or provide access) and decide whether
  to pursue Claude for Enterprise ZDR.
- Antigravity: turn off Settings > Account > Enable Telemetry.
- xAI: decide whether to create a team and enable team ZDR, and run the Grok CLI
  `/privacy` code-retention control.
- Cohere: decide whether to add a payment method (Data Controls) and request
  enterprise ZDR.
- Vercel: decide whether to move the team to Pro/Enterprise for ZDR.
- Mistral: decide whether to enable pay-as-you-go and request ZDR.
- Requesty, OrcaRouter, Inception: decide whether to pursue the enterprise ZDR
  contracts.
- Z.ai: confirm the console path for the announced ZDR opt-in.
- Google AI Studio: decide whether to move the free-pool route to paid Gemini API
  quota, which disables training.
