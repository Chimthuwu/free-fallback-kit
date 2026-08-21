# Free Fallback Kit

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Dependencies: none](https://img.shields.io/badge/dependencies-stdlib%20only-brightgreen.svg)](scripts/discover_free_models.py)
[![Providers](https://img.shields.io/badge/providers-7%2B-orange.svg)](GUIDE.md#step-2--collect-independent-buckets)

**Keep an LLM app running on free tiers without dying at the first quota wall.**

A fallback chain of five free models sounds resilient. It usually isn't — on OpenRouter
every `:free` model draws from one **account-wide** daily cap, so a chain of ten is one
bucket wearing ten hats. They all fail in the same second.

This kit is the method and the tooling for building a chain where consecutive entries
draw on **different quota buckets**, plus key rotation that moves *before* a wall instead
of after it.

Nothing here is tied to one framework or one provider. The concepts apply to a Python
script, a JS app, an agent framework, or a CLI tool that happens to take a `base_url`.
No model list is baked in — the scripts discover what actually works on your account,
because free tiers change weekly.

---

## Contents

- [Pick your entry point](#pick-your-entry-point)
- [Quick start](#quick-start)
- [What's in here](#whats-in-here)
- [The core idea in one table](#the-core-idea-in-one-table)
- [The shape you're aiming for](#the-shape-youre-aiming-for)
- [Free buckets worth collecting](#free-buckets-worth-collecting)
- [Known limits](#known-limits)
- [Further reading](#further-reading)
- [Contributing](#contributing)

---

## Pick your entry point

| You are | Start here |
|---|---|
| Handing this to an AI coding agent | **[`SETUP.agent.md`](SETUP.agent.md)** — an imperative runbook with hard rules and a verification gate |
| Doing it yourself | **[`GUIDE.md`](GUIDE.md)** — the same material explained, with the reasoning |
| Writing the fallback logic into your own code | **[`examples/python/fallback_chain.py`](examples/python/fallback_chain.py)** — a dependency-light reference implementation |
| Configuring Hermes Agent or OpenClaw | **[`SETUP.agent.md`](SETUP.agent.md)** — tool-specific branches (marked ⚡) live in the same file, no separate download needed |
| In a hurry, just want *something* free right now | Point at `openrouter/free` — see [below](#fast-path) — then come back and read the rest |

---

## Quick start

```bash
git clone https://github.com/Chimthuwu/free-fallback-kit
cd free-fallback-kit

# 1. Find which free models actually answer on your key
export OPENROUTER_API_KEY=sk-or-v1-...
python scripts/discover_free_models.py

# 2. Same script, any OpenAI-compatible provider
python scripts/discover_free_models.py --provider mistral
python scripts/discover_free_models.py --base-url https://api.cerebras.ai/v1 --key-env CEREBRAS_API_KEY

# 3. Emit a chain your code can load
python scripts/discover_free_models.py --json > models.json
```

Or hand the folder to a coding agent:

> Follow `SETUP.agent.md` in this repo and wire free-tier fallback into <my project>.

<a id="fast-path"></a>
**Fast path, zero setup:** OpenRouter ships a router model, `openrouter/free`, that
auto-picks a live `:free` model per request (200K context, filters by whatever the
request needs — vision, tools, structured output). Point at it as `model:
"openrouter/free"` and you're answering requests immediately. It's still one model on
one account, though — same daily cap as everything else on OpenRouter, so it's a good
entry #0, not a substitute for a second bucket. Details in
[`GUIDE.md`](GUIDE.md#fast-path-the-openrouterfree-router).

---

## What's in here

```
SETUP.agent.md                    runbook written for an AI agent to execute — self-
                                   contained, including the Hermes/OpenClaw branches
GUIDE.md                          the human explainer — concepts, mechanics, gotchas
scripts/discover_free_models.py   probes real endpoints, reports what works, emits a chain
examples/.env.example             which key goes in which variable
examples/python/fallback_chain.py drop-in chain: rotation, classification, cooldowns
```

---

## The core idea in one table

A fallback only helps when the next entry draws on a different bucket.

| Boundary | Separate bucket? |
|---|---|
| Two `:free` models, same OpenRouter account | **No** — same daily cap |
| Two API keys, same OpenRouter account | **No** — cap is per account |
| Two API keys, different OpenRouter accounts | **Yes** |
| OpenRouter vs Groq vs Google AI Studio | **Yes** |
| Two Google keys, same Cloud project | **No** — free tier meters per project |
| Two Google keys, different accounts | **Yes** |
| Two different models on **one** Google key | **Partly** — Google meters per model per day |

That last row is the one people miss: two Gemini models on the same key hold separate
daily allowances.

---

## The shape you're aiming for

```
ROTATE   keys within one provider — fires first, nothing downstream notices
  openrouter    N keys · N different accounts
  gemini        N keys · N different accounts

CHAIN    only once a provider's keys are all spent
  0 … k         same provider, descending quality    cheap hops
  k+1           independent bucket A                 survives the daily cap
  k+2           independent bucket B                 survives A
  last          models you tolerate but don't love    never fires in normal use
```

---

## Free buckets worth collecting

All free, none need a card unless noted. Every OpenAI-compatible one works with a base
URL and a key — no new SDK.

| Provider | Signup | Endpoint | Notes |
|---|---|---|---|
| OpenRouter | https://openrouter.ai/settings/keys | `https://openrouter.ai/api/v1` | account-wide daily cap across every `:free` model |
| Google AI Studio | https://aistudio.google.com/apikey | `https://generativelanguage.googleapis.com/v1beta/openai/` | meters per model per day — two models, two allowances |
| Groq | https://console.groq.com/keys | `https://api.groq.com/openai/v1` | fast, generous, independent of the rest |
| Cerebras | https://cloud.cerebras.ai/ | `https://api.cerebras.ai/v1` | verify — a valid key can still 402 with no active free allowance |
| NVIDIA NIM | https://build.nvidia.com/ | `https://integrate.api.nvidia.com/v1` | | 
| Mistral AI | https://console.mistral.ai/api-keys | `https://api.mistral.ai/v1` | ~1 req/s, 500K TPM, ~1B tokens/month |
| Cohere (compat layer) | https://dashboard.cohere.com/api-keys | `https://api.cohere.ai/compatibility/v1` | trial key, 20 RPM/1,000 calls-month, **non-commercial only** |
| OVHcloud AI Endpoints | *none — no signup, no key* | `https://oai.endpoints.kepler.ai.cloud.ovh.net/v1` | 2 RPM per IP — last-resort bucket, EU-hosted |
| A 2nd account anywhere | — | — | separate cap — worth as much as a new provider |

Two more work but need extra wiring rather than a plain base URL + key, so they're
covered in [`GUIDE.md`](GUIDE.md#step-2--collect-independent-buckets) instead of here:
**Hugging Face** (its catalog mixes free and metered models inside one entry) and
**Cloudflare Workers AI** (its base URL has your account ID baked in).

---

## Known limits

**Fallback is reactive.** It fires *on* an error, not before one — the failing request
pays the latency of discovering the wall. Key rotation is the only layer that moves
ahead of a limit, and it needs 2+ keys on *different accounts* to be worth anything.

**Prompt cache resets on every switch.** Caches key on model + account, so each fallback
re-reads the full history at full input cost — as does the return to the primary.
Irrelevant on free models; expensive the moment a paid model enters the chain.

**Free tiers rot.** Models get delisted, quotas change, endpoints break without notice —
or the whole product does: GitHub Models, playground and inference API alike, was fully
retired on 2026-07-30 with no successor free tier. Re-run `discover_free_models.py`
every few weeks and prune what died. A chain entry that no longer exists burns a
failover hop on every single request.

---

## Further reading

For a wider provider list than this kit tracks directly:

- [mnfst/awesome-free-llm-apis](https://github.com/mnfst/awesome-free-llm-apis) —
  rate limits and base URLs per provider, updated frequently.
- [open-free-llm-api/awesome-freellm-apis](https://github.com/open-free-llm-api/awesome-freellm-apis) —
  similar coverage, a useful second opinion when the two disagree.

Treat both as leads, not ground truth, for the same reason this whole kit exists —
verify with `discover_free_models.py` before anything in either list enters a chain you
depend on. (One list recommended elsewhere as *the* clearest reference had been deleted
outright by the time this was checked. That's not a knock on either repo above — it's
the entire argument for probing live instead of trusting a snapshot.)

---

## Contributing

Provider free tiers move constantly. PRs welcome for new buckets, corrected wiring, new
error signatures for the classification table in `GUIDE.md` — that table is the most
useful thing here and the easiest to keep current — and new tool-specific (⚡-marked)
branches in `SETUP.agent.md` for tools with their own fallback configuration.

## License

MIT — see [LICENSE](LICENSE).
