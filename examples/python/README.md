# Reference implementation

`fallback_chain.py` is a working chain in ~350 lines with one dependency (`openai`).
Copy it into your project and import it — it is meant to be edited, not installed.

```bash
pip install openai
export OPENROUTER_API_KEY=sk-or-v1-...
python fallback_chain.py          # builds a chain and sends one request
```

```python
from fallback_chain import build_chain

chain = build_chain(log=print)                      # keys from env or .env
print(chain.describe())

text, endpoint = chain.chat([{"role": "user", "content": "hello"}])
```

Anything that isn't a plain chat call goes through `run()`, which hands you a client and
a model id and applies the same failover:

```python
def call(client, model):
    return client.chat.completions.create(
        model=model, messages=msgs, tools=my_tools)

completion, endpoint = chain.run(call)
```

## Feeding it verified models

By default the chain discovers OpenRouter's current `:free` list and ranks it from
catalog metadata. Better: verify first, and let the chain load the result.

```bash
python ../../scripts/discover_free_models.py --json > models.json
```

`build_chain()` reads `models.json` next to `fallback_chain.py` and prefers it over
discovery. Every entry in it answered a real request. Re-run it every few weeks.

## Tuning it to your workload

| Situation | Change |
|---|---|
| Agent with tools | `build_chain(require_tools=True)` |
| Batch work, latency irrelevant | `score_model_id(..., penalise_slow=False)` — stop demoting reasoning models |
| Long documents | rank by context: `discover_free_models.py --rank context` |
| Interactive / voice | rank by measured latency: `--rank latency` |
| More keys | add `OPENROUTER_API_KEY_2`, `GROQ_API_KEY_2`, … — they rotate automatically |
| Different cooldowns | `COOLDOWN_MINUTE_LIMIT`, `COOLDOWN_DAILY_LIMIT`, `COOLDOWN_TRANSIENT` |

## What it deliberately does not do

- **No background health checks.** Failover is driven by real requests only; a probe
  loop against free endpoints spends the quota it is trying to protect.
- **No persistence across restarts.** Cooldowns live in memory. A restart re-tries
  everything, which costs one failed request per dead entry and keeps the code simple.
- **No streaming helper.** `run()` gives you the raw client — stream from it directly,
  but note that a failure *mid-stream* cannot be retried transparently.
- **No thread-per-endpoint racing.** One request, one endpoint, in order.

## Porting it elsewhere

The parts that matter, in the order they matter: classify before reacting, rotate keys
before switching models, start every request at the top of the chain, and treat an empty
`200` as a failure. Everything else is bookkeeping. See [`../../GUIDE.md`](../../GUIDE.md).
