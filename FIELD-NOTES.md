# Field notes — free-model APIs, from a live build

Practitioner notes written **after** building a working six-deep chain
(Hermes Agent, Windows, Claude subscription primary + five free/independent
fallbacks). These are the things that were *not* in the catalog, the docs, or
the runbook — the ones that each cost a wrong "DEAD" verdict and nearly caused a
working bucket to be deleted.

Scope note: this file does **not** repeat what's already in
[`GUIDE.md`](GUIDE.md#gotchas-that-cost-real-time) (Cloudflare 1010 blocks,
`200 ≠ success`, `free_only`, stale `HERMES_HOME`). Those held up under test.
What's here is new, and in five cases it contradicts something the catalog
implies.

Every claim below was live-tested. Where a finding is inference rather than
observation, it says so.

---

## Contents

- [A free-looking model can be a paid model](#1-a-free-looking-model-can-be-a-paid-model)
- [Reasoning models need a token budget, or they fake a 200](#2-reasoning-models-need-a-token-budget-or-they-fake-a-200)
- [Your probe script is a measurement instrument — calibrate it](#3-your-probe-script-is-a-measurement-instrument--calibrate-it)
- [Router beats pinned, and you have to measure to know](#4-router-beats-pinned-and-you-have-to-measure-to-know)
- [A key truncated by your own parser is indistinguishable from a revoked one](#5-a-key-truncated-by-your-own-parser-is-indistinguishable-from-a-revoked-one)
- [Read the rate-limit headers: they tell you what tier you're on](#6-read-the-rate-limit-headers-they-tell-you-what-tier-youre-on)
- [Auth tier ≠ model tier (Nous)](#7-auth-tier--model-tier-nous)
- [Spend guards have a precedence trap](#8-spend-guards-have-a-precedence-trap)
- [Cheat sheet](#cheat-sheet)

---

## 1. A free-looking model can be a paid model

**The `:free` suffix is a property of the model id, not of what you'll be
charged.** A route can present as free and bill.

Observed on a Nous Portal account with an active OAuth credential:

```
nous/welcome   ->  HTTP 404
   "Model 'deepseek/deepseek-v4-flash-0731' requires available credits"
```

`nous/welcome` is the *anonymous* tier id. It is not a model — it's a pointer to
whatever the free tier is currently serving, and behind that pointer sat a
**paid** DeepSeek. The account had no credits, so the call 404'd.

Two things make this nasty:

1. **Auth is the thing that changes the routing.** Anonymous → free backend.
   Authenticated → whatever the account's tier maps to. The same config line
   behaves differently before and after `auth add`.
2. **It fails at the exact moment you need it.** It sat in a working chain
   looking correct, because login succeeded and the model id looked free.

Rule: **treat "free" as a claim to be verified on the credential that will
actually use it**, never as a naming convention. Verify after auth, not before.

## 2. Reasoning models need a token budget, or they fake a 200

`GUIDE.md` gotcha 6 says check for empty content and treat it as failure. This
is the other half: **empty content is often a probe bug, not a dead endpoint.**

Observed, same model, same key, seconds apart:

| `max_tokens` | HTTP | content |
|---|---|---|
| 5 | 200 | `""` |
| 512 | 200 | `"ok"` |

`openai/gpt-oss-120b` spent **52 of its 52 completion tokens on reasoning**
before emitting `ok`. Cap it below its thinking budget and it returns a
perfectly healthy 200 with nothing in it.

This bit twice, in both directions:

- A **live** model was reported DEAD.
- The fix — raise the budget — is applied to the *probe*, so nothing about the
  endpoint actually changed. Then the next low-budget probe "broke" it again.

Reasoning models surface their thinking as a separate field
(`reasoning_content` / `reasoning` / `reasoning_details`, name varies by
provider). If that field is non-empty while `content` is empty, **the model
worked and you under-funded it.** That is a positive signal, not a failure.

Budget guidance for probes:

| Model class | Probe `max_tokens` |
|---|---|
| plain chat | 64–256 |
| reasoning (gpt-oss, nemotron, cohere/north) | 512–1024 |
| anything reached via a router | 1024 (you don't know what you'll get) |

## 3. Your probe script is a measurement instrument — calibrate it

Five of the six bugs in this build were **in the measuring apparatus**, not in
the thing being measured. Every one produced a confident false negative.

The pattern: a probe that has never been checked against a *known-good*
response will confidently report "dead" for reasons that have nothing to do with
the endpoint.

Before trusting a discovery run, sanity-check the probe against one entry you
have personally confirmed working end-to-end. If the probe can't reproduce a
success you saw by hand, fix the probe.

Concretely, this run's false DEADs, and the real cause in each:

| Verdict | Actual cause |
|---|---|
| Groq 403, key "invalid" | Cloudflare UA block (key was fine) |
| `openrouter/free` DEAD | router → reasoning model, 64-token cap |
| `openrouter/free` EMPTY, then LIVE | same model, 1024-token cap |
| Mistral 401 "Invalid API Key" | key truncated 45→38 by my own regex |
| `qwen3.8-27b:free` 429×5 | genuinely throttled — **this one was real** |

Five false, one true. If you'd trusted any of the five you'd have deleted
working buckets, and if you'd trusted the run as a whole you'd have learned
nothing about which models are actually throttled.

## 4. Router beats pinned, and you have to measure to know

`openrouter/free` self-selects, so the usual advice is "pin a specific model for
stability." Measured on one account, three attempts each, minutes apart:

| Model | Result |
|---|---|
| `openrouter/free` (router) | **3/3** |
| `nvidia/nemotron-3-super-120b-a12b:free` | 3/3 |
| `dots-studio/dots-3-note-preview:free` | 3/3 |
| `google/gemma-4-31b-it:free` | 2/3 |
| `qwen/qwen3.8-27b:free` | **0/3** (429 every time) |
| `thinkingmachines/inkling-small:free` | **0/3** (403) |

Two things fall out:

- **The router was the single most reliable option**, because it steps around
  throttled upstreams itself. A hard pin cannot do that — it's a single point
  of failure wearing a model name.
- **Free-tier throttling is per-model and volatile.** `qwen3.8-27b` served
  cleanly during one test run and was 0/5 minutes later. **One success is not
  evidence of reliability.** Take the median of ≥3, spaced attempts.

Corollary: a pinned `:free` sibling is only worth its place if it's a
**different model family** from what the router usually picks — otherwise
you're paying a second hop to re-enter the same throttled upstream.

## 5. A key truncated by your own parser is indistinguishable from a revoked one

Provider keys are not all `[A-Za-z0-9]`. Mistral keys can contain `_` in the
body.

```
regex:  mstrl_[A-Za-z0-9]+     -> captured 38 of 45 chars
result: HTTP 401 {"detail":"Invalid API Key"}
```

The API cannot tell a truncated key from a revoked one. It said "invalid," the
evidence said "revoked," and the obvious action — reissue a perfectly good key —
was wrong.

**Detect by length.** Print the captured length next to the verdict (never the
value). A key that suddenly fails *and* is a different length than the one that
worked is a parser bug until proven otherwise. Rotate last, not first.

Related: don't build key regexes at all when you can read the key from a file
and let the provider be the validator. Strip only known separators
(`\r`, whitespace, quotes) — never "sanitize" to a character class.

## 6. Read the rate-limit headers: they tell you what tier you're on

Free and paid tiers look identical in the API surface. The headers differ:

```
Mistral, "free-ish" key:   x-ratelimit-limit-req-minute: 188
                           x-ratelimit-limit-tokens-minute: 625000
Mistral free experimental:  1 req/sec
```

188 req/min is ~3× a single sustained request. That key bills.

Corroborating signal: on that same key, `mistral-small-latest` and
`magistral-medium-latest` returned **429** while open-weights models
(`open-mistral-nemo`, `ministral-8b-latest`, `codestral-latest`) served fine.
Paid-tier throttling on premium SKUs, free headroom on the rest.

**Check the headers before you put a key in a chain.** A key you believe is free
is the one that quietly drains a balance, and "free model" in a config comment
is not a billing control.

## 7. Auth tier ≠ model tier (Nous)

Extends §1. Concretely, on one Portal account, all live-tested on the same
OAuth token:

| Model id | Result |
|---|---|
| `stealth/space-bunny-alpha` | **LIVE** — `"ok"`, 10 completion tokens |
| `nous/welcome` | 404 — routes to a paid model, no credits |
| `Hermes-4-405B` | 404 — **retired** |
| `deepseek/deepseek-v4.1-flash:US` | 404 — requires credits |

And from the Portal's own recommendation cache, the **paid** pick was
`x-ai/grok-4.7` at **$2 in / $6 out per 1M**. A chain entry that lands there
turns a free-tier fallback into a metered one, silently, on the day you least
want a surprise invoice.

Worth stating plainly: a tool that reports *which model the provider recommends
for your account* is reporting something different from *which model you should
put in a free chain*. Those disagree here, and the second question is the one
that matters.

Takeaway: **a fallback chain needs a spend ceiling, not just a free-model
list.** Order paid-but-capable entries last, and put a hard guard above the
background/auxiliary tier so a title or a compression can never become a bill.

## 8. Spend guards have a precedence trap

Adding a guard that restricts an auxiliary lane to `:free` SKUs had an
unintended effect: it **silently skipped the entire provider** for those tasks,
because the configured model was a *router*, and a router is not a `:free` SKU.

Worse, the obvious fix didn't work. The guard resolved
`configured_model or global_default`, so a **per-task** model silently overrides
the global setting you'd just corrected. The warning kept naming the per-task
value. The fix had to happen at the task, not the default.

Symptom to recognize: a guard that logs "skipping provider X" for a provider
you have working credentials for, repeatedly, with no error. Read the warning's
**named value** — it's telling you which config key actually won.

General rule for any layered config: **when a setting appears not to apply,
assume a more specific one is overriding it, and go looking for the override
before changing the thing you can see.**

---

## Cheat sheet

Ordered by how much time each one cost.

| # | Check | Cost of skipping |
|---|---|---|
| 1 | Rate-limit headers — is this key actually free? | Silent drain of a real balance |
| 2 | Probe `max_tokens` ≥512 for reasoning models | Live models reported DEAD |
| 3 | Sanity-check the probe against a known-good response | You debug the instrument, not the endpoint |
| 4 | ≥3 spaced attempts before judging reliability | One lucky 200 reads as "stable" |
| 5 | Compare key length before believing a 401 | Revoke a working key |
| 6 | Verify models **after** auth, on the real credential | Free-looking id bills, or 404s |
| 7 | Prefer router over pin where both are free | Pin becomes a single point of failure |
| 8 | Pin siblings in a different model family | Second hop into the same throttled upstream |
| 9 | Check per-task overrides before a global setting | Guard skips a provider you configured |
| 10 | Re-run discovery on a schedule | (see `GUIDE.md` — GitHub Models died silently) |

**The through-line:** almost nothing that fails on a free tier fails for the
reason the error message implies. `403` means a UA block, not a bad key. `401`
means a truncated key, not a revoked one. `200` means nothing. `429` means
upstream capacity, not your balance — adding credits does not fix it
(verified: identical 429 rates before and after funding an account). Diagnose
by **differential measurement**, not by reading the status code.

---

## Applying this to `discover_free_models.py`

Concrete changes this build argues for, in priority order:

1. **Per-model-class token budgets** (§2). A single global `max_tokens` is what
   produced the false DEADs. Classify from the catalog
   (`reasoning`/known-reasoning families) and scale.
2. **Repeat-and-median** (§4). One attempt per model cannot distinguish
   "throttled" from "unlucky." Default to 3, spaced.
3. **Print key length with any auth failure** (§5). Cheap, and it separates
   "revoked" from "I mangled it."
4. **Surface rate-limit headers** in provider output (§6), so a key's tier is
   visible in the report rather than assumed.
5. **Model-on-credential post-auth check** (§1, §7) as an explicit second pass,
   for any provider where auth changes routing.
6. **Optional User-Agent override** — already needed for Groq/Cerebras per
   `GUIDE.md` gotcha 3; this build hit it on the **chat** endpoint via a
   named-provider config, not just `/v1/models`, so the override needs to apply
   to the full client, not just the catalog probe.

Items 1–3 are the ones that would have prevented every false negative recorded
above.
