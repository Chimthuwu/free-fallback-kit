# Running on free models, indefinitely

A guide to building a fallback chain that survives free-tier quota walls — in your own
code, or in any tool that lets you configure more than one model.

Everything here was verified by live API calls, not read off a docs page. No API keys
appear in this file.

---

## The mistake almost everyone makes

You sign up for OpenRouter, point your app at a `:free` model, and add five more `:free`
models as fallbacks. It works for an hour, then everything dies at once.

**OpenRouter's free-tier daily cap is account-wide.** Every `:free` model draws from one
shared bucket. Chaining ten of them gives you ten ways to hit the same wall
simultaneously — it is one bucket wearing ten hats.

A fallback chain only buys resilience when consecutive entries draw on **different
buckets**. That is the entire idea. Everything below is mechanics.

---

## What counts as a separate bucket

| Boundary | Separate bucket? |
|---|---|
| Two `:free` models, same OpenRouter account | ❌ No — same daily cap |
| Two API keys, same OpenRouter account | ❌ No — cap is per account |
| Two API keys, **different** OpenRouter accounts | ✅ Yes |
| OpenRouter vs Groq vs Google AI Studio | ✅ Yes |
| Two Google AI Studio keys, same Cloud project | ❌ No — free tier meters per project |
| Two Google keys, different accounts/projects | ✅ Yes |
| Different models on **one** Google key | ✅ Partly — Google meters per model per day |

That last row is easy to miss and genuinely useful: two Gemini models on the same key
have *separate* daily allowances. Exhausting one does not exhaust the other.

To check whether two keys are really two accounts, ask the provider. On OpenRouter:

```python
import json, urllib.request
d = json.load(urllib.request.urlopen(urllib.request.Request(
    "https://openrouter.ai/api/v1/key",
    headers={"Authorization": "Bearer <KEY>"}), timeout=30))["data"]
print(d["creator_user_id"], d["is_free_tier"], d["usage"])
```

Different `creator_user_id` = different account = genuinely separate cap.

---

## The three layers, in firing order

Whatever you build on, resilience comes in the same three layers, and the order is why
the first one is worth the setup effort.

**1. Key rotation** — swap keys *within* one provider. Fires **before** any model
switch, so the model stays the same and the caller never notices. This is the only
layer that gets ahead of a limit rather than reacting to one. Worth doing only with 2+
keys on *different accounts*.

**2. Model chain** — switch to a different provider:model once a provider's keys are
spent. Reactive by nature: something must fail first.

**3. Background work on separate models** — summarisation, title generation, embeddings,
classification. Pin these to the smallest usable model so they never eat the quota your
main path depends on.

---

## Step 1 — Find out what actually works

Do not trust model catalogs. Providers list models whose endpoints refuse to serve, and
any model list you remember is stale — the free tier turns over completely every few
months.

```bash
export OPENROUTER_API_KEY=sk-or-v1-...
python scripts/discover_free_models.py                 # probe every :free model
python scripts/discover_free_models.py --require-tools # agents only: tool-calling
python scripts/discover_free_models.py --provider groq # any OpenAI-compatible provider
python scripts/discover_free_models.py --json          # machine-readable chain
```

The script calls each model for real and prints `LIVE` / `DEAD` with latency. Pick from
the `LIVE` rows, and pick on the axis your workload actually cares about:

| Workload | Rank by |
|---|---|
| Agent driving tools | tool-calling support first, then quality |
| Long documents | context length |
| Interactive / voice / anything a human waits on | **measured latency** — a reasoning model that thinks for 20s is unusable however smart it is |
| Batch processing | throughput and cap size, latency irrelevant |

**Read the failures, don't just skip them.** They say different things, and one of them
you can fix in thirty seconds:

| Error signature | Meaning | Action |
|---|---|---|
| `404 No endpoints available matching your ... data policy` | Your privacy settings exclude logging providers — which is most of the free tier | Fixable, see gotcha #1 |
| `429 ... limit_source: upstream_provider_shared_pool` | Provider's shared key saturated by other users, not your quota | Usable but unreliable — put it near the bottom |
| `404 Function id '...' is not found` | Upstream deployment deleted; stale catalog entry | Exclude permanently |
| `402 Payment Required` | No free-tier allowance on that account | Exclude; check that provider's billing page |
| `403 error code: 1010` | Cloudflare browser-signature block on `python-urllib`, **not** a bad key | Retry with a normal `User-Agent` |
| `200` with empty content | Endpoint overloaded and answering with nothing | Treat as a failure at runtime |

---

## Step 2 — Collect independent buckets

Each of these is free, needs no card, and takes about a minute. All speak the OpenAI
wire format, so adding one is a base URL and a key.

| Provider | Where | Base URL |
|---|---|---|
| OpenRouter | https://openrouter.ai/settings/keys | `https://openrouter.ai/api/v1` |
| Google AI Studio | https://aistudio.google.com/apikey | `https://generativelanguage.googleapis.com/v1beta/openai/` |
| Groq | https://console.groq.com/keys | `https://api.groq.com/openai/v1` |
| Cerebras | https://cloud.cerebras.ai/ | `https://api.cerebras.ai/v1` |
| NVIDIA NIM | https://build.nvidia.com/ | `https://integrate.api.nvidia.com/v1` |

A second account at a provider you already use is worth as much as a new provider, and
is usually faster to set up.

---

## Step 3 — Order the chain

1. **Cheap hops first** — same provider, different model, best quality first. Covers
   per-model rate limits and single-model outages.
2. **Then independent buckets**, ranked by how good the model is. Without at least one,
   the whole chain dies at the same instant.
3. **Models you dislike go last.** They still catch a total outage without appearing in
   normal operation.
4. **Exclude anything that failed Step 1**, and write down why — otherwise you will
   re-add it in three weeks.

Keys live in the environment or a `.env` file. Never in code, never in a config file you
might commit. See [`examples/.env.example`](examples/.env.example).

---

## Step 4 — Classify failures before reacting to them

Retrying blindly wastes the one thing you are short of. Every failure falls into one of
three scopes:

| Scope | Trigger | Reaction |
|---|---|---|
| **Model is gone** | `400`/`404` invalid model id, deleted deployment, policy block | Disable for the session — never retry |
| **Key is spent** | `429` per-minute, `401`/`403` | Rotate to the next key for that provider; nap this one |
| **Transient** | `5xx`, timeout, empty completion | Short nap, move down the chain |

Two details worth getting right:

- **A daily cap is not a per-minute limit.** Nap the entry for half an hour, not sixty
  seconds — otherwise you burn a hop on it every request for the rest of the day.
- **Honour `Retry-After` when the provider sends it.** It is usually accurate.

Then **always start the next request at the top of the chain**. The primary comes back
on its own the moment its cooldown expires, with no extra bookkeeping and no restart.

[`examples/python/fallback_chain.py`](examples/python/fallback_chain.py) is a working
implementation of exactly this — roughly 200 lines, no dependencies beyond the OpenAI
SDK.

---

## Gotchas that cost real time

**1. OpenRouter's privacy setting silently hides most of the free tier.**
Symptom: `404 No endpoints available matching your guardrail restrictions and data
policy` on the best free models, while a few lesser ones work fine.

Fix — `openrouter.ai/settings/privacy`, enable both:
- *Allow free endpoints that train on request data*
- *Allow free endpoints that publish prompts*

Also confirm **Zero Data Retention → Non-frontier** is **off**; it forces ZDR endpoints
for every open model and re-blocks everything you just unlocked.

The tradeoff is real: those providers may retain, train on, and publish your prompts and
completions. Fine for hobby work. Do not point it at credentials or client code.

**2. Catalog metadata beats remembered model names.** Model ids you know are stale, but
the catalog ships a description for every entry. Filter on it: guardrail and moderation
models, embedding and rerank models, and coding agents will all happily accept a chat
request and return something useless. Watch for negation when you do —
"advises against agentic coding" is not a coding model.

**3. Some providers sit behind Cloudflare and reject `python-urllib`.**
Cerebras and Groq return `403 error code: 1010` on `/v1/models` for default Python
user-agents. That is a browser-signature block, not a bad key — retry with a normal
`User-Agent` before concluding anything. Their *chat* endpoints accept the OpenAI SDK's
user-agent fine.

**4. Prompt cache resets on every fallback.** Caches are keyed to model and account.
Each switch re-reads your whole history at full input cost, and so does the trip back to
the primary. Irrelevant on free models, expensive if any paid model is in the chain.

**5. Disable client-side retries, or they fight the chain.** The OpenAI SDK retries
twice by default. Against an already-rate-limited model that is three wasted round trips
before your fallback even runs. Set `max_retries=0` on the client and let the chain do
the work.

**6. A `200` is not a success.** Overloaded free endpoints return empty content, and
reasoning models return their thinking with an empty answer. Check for empty content and
treat it as a failure, or you will silently ship blank output.

**7. (Hermes) A stale `HERMES_HOME` silently redirects the whole install.** Hermes reads
this env var before falling back to `~/.hermes`, and the installer never asks — it just
honors whatever's set. If it's left over from an old project, Hermes lands there again on
every reinstall, even after you delete the directory it points at. Check
`echo $HERMES_HOME` (and, on Windows, `HKCU:\Environment`, since a shell can be clean
while the persisted value isn't) before installing or chasing a "wrong location" bug.

---

## Verify before you rely on it

Re-run discovery after any change, and before anything that matters. A config that has
not been live-tested is a guess:

```bash
python scripts/discover_free_models.py --json > models.json
```

Every entry your app loads should have answered a real request at least once. Free tiers
move constantly — re-run every few weeks and prune what died.

---

## Tool-specific wiring

If your app is a framework or CLI that already supports multiple models, the concepts
above map onto its own configuration:

- **Hermes Agent** ([hermes-agent.ai](https://hermes-agent.ai/) ·
  [github.com/NousResearch/hermes-agent](https://github.com/nousresearch/hermes-agent))
  — install with `curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash`
  (macOS/Linux/WSL2/Termux) or `iex (irm https://hermes-agent.nousresearch.com/install.ps1)`
  (Windows PowerShell), then `hermes doctor` and `hermes setup` to pick a provider.
  Config lives at `~/.hermes/config.yaml` and `~/.hermes/.env` by default, regardless of
  where the CLI itself is installed — **but not always**: Hermes honors a `HERMES_HOME`
  environment variable if one is already set, and the installer uses it silently instead
  of asking. A stale `HERMES_HOME` from an old project is a real trap — it makes Hermes
  install into whatever directory that variable still points at, even after you delete
  that directory and reinstall. Check `echo $HERMES_HOME` (and, on Windows, the
  persisted `HKCU:\Environment` value) before installing or debugging a "wrong
  location" issue. `SETUP.agent.md`'s ⚡ Hermes branch in Step 01 checks this and
  confirms with you whether to reuse the existing home or reset to the default. Fallback
  wiring — `config.yaml`, credential pools, auxiliary task chains, a verifier script — is
  fully covered in [`SETUP.agent.md`](SETUP.agent.md)'s ⚡-marked branches (Steps 01,
  05a, 06, 07); no separate install doc needed.
- **OpenClaw** ([openclaw.ai](https://openclaw.ai/) ·
  [github.com/openclaw/openclaw](https://github.com/openclaw/openclaw)) — install with
  `curl -fsSL https://openclaw.ai/install.sh | bash` (macOS/Linux), `iwr -useb
  https://openclaw.ai/install.ps1 | iex` (Windows), or `npm install -g openclaw@latest
  --allow-scripts=openclaw`; needs Node.js 22.22.3+/24.15+/25.9+ if you're not using one
  of the bundled installers. Run `openclaw onboard --install-daemon` to finish setup and
  pick a model provider — that's the slot this repo's fallback chain fills. `SETUP.agent.md`
  has an install/verify branch for it in Step 01 (🦞); beyond that it has no dedicated
  config-writing branch yet, so follow the 🌐 generic path — OpenClaw speaks an
  OpenAI-compatible API, so the generic chain logic ports in with minimal changes.

Other tools follow the same shape: find where it accepts a list of models, where it
takes a `base_url`, and whether it can hold more than one key per provider.
