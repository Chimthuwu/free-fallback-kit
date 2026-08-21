# Free Fallback Kit

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

## Pick your entry point

| You are | Start here |
|---|---|
| Handing this to an AI coding agent | **[`SETUP.agent.md`](SETUP.agent.md)** — an imperative runbook with hard rules and a verification gate |
| Doing it yourself | **[`GUIDE.md`](GUIDE.md)** — the same material explained, with the reasoning |
| Writing the fallback logic into your own code | **[`examples/python/fallback_chain.py`](examples/python/fallback_chain.py)** — a dependency-light reference implementation |
| Configuring Hermes Agent or OpenClaw | **[`SETUP.agent.md`](SETUP.agent.md)** — tool-specific branches (marked ⚡) live in the same file, no separate download needed |

---

## Quick start

```bash
git clone https://github.com/<you>/free-fallback-kit
cd free-fallback-kit

# 1. Find which free models actually answer on your key
export OPENROUTER_API_KEY=sk-or-v1-...
python scripts/discover_free_models.py

# 2. Same script, any OpenAI-compatible provider
python scripts/discover_free_models.py --provider groq
python scripts/discover_free_models.py --base-url https://api.cerebras.ai/v1 --key-env CEREBRAS_API_KEY

# 3. Emit a chain your code can load
python scripts/discover_free_models.py --json > models.json
```

Or hand the folder to a coding agent:

> Follow `SETUP.agent.md` in this repo and wire free-tier fallback into <my project>.

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
  last          models you tolerate but don't love   never fires in normal use
```

---

## Free buckets worth collecting

All free, none need a card.

| Provider | Signup | Endpoint |
|---|---|---|
| OpenRouter | https://openrouter.ai/settings/keys | `https://openrouter.ai/api/v1` |
| Google AI Studio | https://aistudio.google.com/apikey | `https://generativelanguage.googleapis.com/v1beta/openai/` |
| Groq | https://console.groq.com/keys | `https://api.groq.com/openai/v1` |
| Cerebras | https://cloud.cerebras.ai/ | `https://api.cerebras.ai/v1` |
| NVIDIA NIM | https://build.nvidia.com/ | `https://integrate.api.nvidia.com/v1` |
| A 2nd account anywhere | — | separate cap — worth as much as a new provider |

Every one of them speaks the OpenAI chat-completions wire format, so one client class
covers the lot.

---

## Known limits

**Fallback is reactive.** It fires *on* an error, not before one — the failing request
pays the latency of discovering the wall. Key rotation is the only layer that moves
ahead of a limit, and it needs 2+ keys on *different accounts* to be worth anything.

**Prompt cache resets on every switch.** Caches key on model + account, so each fallback
re-reads the full history at full input cost — as does the return to the primary.
Irrelevant on free models; expensive the moment a paid model enters the chain.

**Free tiers rot.** Models get delisted, quotas change, endpoints break without notice.
Re-run `discover_free_models.py` every few weeks and prune what died. A chain entry that
no longer exists burns a failover hop on every single request.

---

## Contributing

Provider free tiers move constantly. PRs welcome for new buckets, corrected wiring, new
error signatures for the classification table in `GUIDE.md` — that table is the most
useful thing here and the easiest to keep current — and new tool-specific (⚡-marked)
branches in `SETUP.agent.md` for tools with their own fallback configuration.

## License

MIT — see [LICENSE](LICENSE).
