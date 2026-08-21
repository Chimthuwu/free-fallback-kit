"""A fallback chain for free-tier LLM APIs. Copy this file into your project.

    pip install openai

    from fallback_chain import build_chain

    chain = build_chain(log=print)          # keys come from env / .env
    reply, endpoint = chain.chat([
        {"role": "user", "content": "hello"}
    ])

What it does, and why each part is there:

  * Tries entries top-down on every request. Starting from the top each time
    means the primary comes back by itself once its cooldown expires -- no
    restart, no bookkeeping.
  * Rotates keys *within* a provider before switching models. This is the only
    layer that moves ahead of a rate limit rather than reacting to one.
  * Classifies failures: a dead model id is disabled for the session, a spent
    key is rotated away from, a transient error is a short nap. Blind retries
    against a limited model waste the one thing you are short of.
  * Treats an empty completion as a failure -- overloaded free endpoints answer
    200 with nothing.
  * Builds the chain from live catalog data, never from hardcoded model ids.
    Free tiers turn over completely every few months.

See GUIDE.md for the concepts and scripts/discover_free_models.py for the
verification step that should feed models.json.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.error
import urllib.request

from openai import OpenAI

OPENROUTER_BASE = "https://openrouter.ai/api/v1"

# Every provider below speaks the OpenAI chat-completions dialect.
PROVIDER_BASES = {
    "openrouter": OPENROUTER_BASE,
    "groq": "https://api.groq.com/openai/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "cerebras": "https://api.cerebras.ai/v1",
    "nvidia": "https://integrate.api.nvidia.com/v1",
}

# First variable listed is the primary key; the rest form the rotation pool.
PROVIDER_KEY_ENVS = {
    "openrouter": ["OPENROUTER_API_KEY", "OPENROUTER_API_KEY_2", "OPENROUTER_API_KEY_3"],
    "groq": ["GROQ_API_KEY", "GROQ_API_KEY_2"],
    "gemini": ["GOOGLE_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY_2"],
    "cerebras": ["CEREBRAS_API_KEY"],
    "nvidia": ["NVIDIA_API_KEY"],
}

# Last-resort ids, used only when a provider's own model listing is unreachable.
# discover_provider_model() and models.json both replace these.
PROVIDER_DEFAULT_MODELS = {
    "groq": "llama-3.3-70b-versatile",
    "gemini": "gemini-2.0-flash",
    "cerebras": "llama3.1-8b",
}

MODELS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models.json")

COOLDOWN_MINUTE_LIMIT = 60          # per-minute 429
COOLDOWN_DAILY_LIMIT = 30 * 60      # daily cap: napping 60s just burns a hop per request
COOLDOWN_TRANSIENT = 20             # 5xx, timeout, empty completion
REQUEST_TIMEOUT = 30.0


# --------------------------------------------------------------------------- #
# Keys                                                                         #
# --------------------------------------------------------------------------- #

def load_env_files(*extra_paths):
    """Read KEY=VALUE lines from nearby .env files. Existing env vars win."""
    here = os.path.dirname(os.path.abspath(__file__))
    for path in [os.path.join(here, ".env"),
                 os.path.join(os.path.dirname(here), ".env"),
                 os.path.join(os.path.expanduser("~"), ".env"),
                 *extra_paths]:
        if not path or not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8-sig") as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    name, _, value = line.partition("=")
                    name, value = name.strip(), value.strip().strip('"').strip("'")
                    if name and value and name not in os.environ:
                        os.environ[name] = value
        except OSError:
            continue


def keys_for(provider, extra_key=None):
    """Every key available for a provider, deduplicated, extra_key first."""
    keys = []
    for candidate in [extra_key] + [os.environ.get(v) for v in PROVIDER_KEY_ENVS.get(provider, [])]:
        candidate = (candidate or "").strip()
        if candidate and candidate not in keys:
            keys.append(candidate)
    return keys


# --------------------------------------------------------------------------- #
# Failure classification                                                       #
# --------------------------------------------------------------------------- #

def classify_failure(exc):
    """Map an exception to (scope, cooldown_seconds, reason).

    scope: "model" -- this id is gone, disable it for the session
           "key"   -- this key is spent or rejected, rotate
           "entry" -- transient, nap and move down the chain
    """
    status = getattr(exc, "status_code", None)
    message = str(getattr(exc, "message", "") or exc)
    low = message.lower()

    if status in (400, 404):
        if "data policy" in low or "no endpoints" in low:
            return "model", None, "blocked by provider privacy settings"
        if "not a valid model" in low or "is not found" in low or "no allowed providers" in low:
            return "model", None, "model id no longer exists"
        return "entry", COOLDOWN_TRANSIENT, message[:120]

    if status in (401, 403):
        return "key", None, "key rejected"
    if status == 402:
        return "model", None, "no free allowance on this account"

    if status == 429:
        retry_after = _retry_after(exc)
        if "per day" in low or "daily" in low or "free-models-per-day" in low:
            return "entry", retry_after or COOLDOWN_DAILY_LIMIT, "daily cap reached"
        return "key", retry_after or COOLDOWN_MINUTE_LIMIT, "rate limited"

    if status and 500 <= status < 600:
        return "entry", COOLDOWN_TRANSIENT, f"upstream {status}"

    return "entry", COOLDOWN_TRANSIENT, message[:120] or exc.__class__.__name__


def _retry_after(exc):
    headers = getattr(getattr(exc, "response", None), "headers", None) or {}
    raw = headers.get("retry-after") or headers.get("Retry-After")
    try:
        return max(1.0, float(raw))
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- #
# Chain                                                                        #
# --------------------------------------------------------------------------- #

class _KeySlot:
    def __init__(self, key, base_url):
        self.key = key
        self.uses = 0
        self.cooldown_until = 0.0
        self.dead = False
        # max_retries=0: the SDK's own retries would fight the chain, spending
        # three round trips on an already-limited model before failover runs.
        self.client = OpenAI(base_url=base_url, api_key=key,
                             timeout=REQUEST_TIMEOUT, max_retries=0)

    def available(self, now):
        return not self.dead and now >= self.cooldown_until


class Endpoint:
    """One (provider, model) pair plus its pool of keys."""

    def __init__(self, provider, model, keys, base_url=None, bucket=None):
        self.provider = provider
        self.model = model
        self.base_url = (base_url or PROVIDER_BASES.get(provider) or OPENROUTER_BASE).rstrip("/") + "/"
        # Quota bucket: every free model on one account shares a cap, so the
        # provider is the bucket unless the caller knows better.
        self.bucket = bucket or provider
        self.dead = False
        self.cooldown_until = 0.0
        self._slots = [_KeySlot(k, self.base_url) for k in keys]

    def __str__(self):
        return f"{self.provider}:{self.model}"

    def available(self, now):
        if self.dead or now < self.cooldown_until:
            return False
        return any(s.available(now) for s in self._slots)

    def pick_slot(self, now):
        """least-used rotation -- balances per-minute pressure across accounts."""
        live = [s for s in self._slots if s.available(now)]
        if not live:
            return None
        slot = min(live, key=lambda s: s.uses)
        slot.uses += 1
        return slot

    def penalise(self, slot, scope, seconds, now):
        if scope == "model":
            self.dead = True
        elif scope == "key" and slot is not None:
            if seconds is None:
                slot.dead = True
            else:
                slot.cooldown_until = now + seconds
            # Last usable key just went down -> rest the entry too, or the chain
            # keeps picking an entry that cannot serve anyone.
            if not any(s.available(now) for s in self._slots):
                self.cooldown_until = now + (seconds or COOLDOWN_TRANSIENT)
        else:
            self.cooldown_until = now + (seconds or COOLDOWN_TRANSIENT)


class FallbackChain:
    def __init__(self, endpoints, log=None):
        self.endpoints = list(endpoints)
        self._log = log or (lambda msg: None)
        self._lock = threading.Lock()
        self._serving = None

    def __len__(self):
        return len(self.endpoints)

    def describe(self):
        lines = []
        for i, ep in enumerate(self.endpoints):
            tag = "primary" if i == 0 else f"#{i}"
            pool = len(ep._slots)
            lines.append(f"  {tag:>7}  {ep}  (bucket: {ep.bucket}"
                         + (f", {pool} keys" if pool > 1 else "") + ")")
        return "\n".join(lines)

    def chat(self, messages, **kwargs):
        """Chat completion over the chain. Returns (text, endpoint)."""
        def call(client, model):
            completion = client.chat.completions.create(
                model=model, messages=messages, **kwargs)
            content = (completion.choices[0].message.content or "").strip()
            if not content:
                raise RuntimeError("empty completion")
            return content
        return self.run(call)

    def run(self, call):
        """Run call(client, model) against the chain. Returns (result, endpoint).

        Raises RuntimeError only when every entry is dead or cooling down.
        """
        errors = []
        with self._lock:
            endpoints = list(self.endpoints)

        for index, endpoint in enumerate(endpoints):
            now = time.time()
            if not endpoint.available(now):
                errors.append(f"{endpoint}: " + ("disabled" if endpoint.dead else
                              f"cooling down {max(0, int(endpoint.cooldown_until - now))}s"))
                continue
            slot = endpoint.pick_slot(now)
            if slot is None:
                errors.append(f"{endpoint}: all keys rate limited")
                continue
            try:
                result = call(slot.client, endpoint.model)
            except Exception as exc:  # noqa: BLE001 - classified, not swallowed
                scope, seconds, reason = classify_failure(exc)
                endpoint.penalise(slot, scope, seconds, time.time())
                note = "disabled" if scope == "model" else f"skipping {int(seconds or 0)}s"
                self._log(f"[Fallback] {endpoint} failed ({reason}) - {note}")
                errors.append(f"{endpoint}: {reason}")
                continue

            # Announce only a *change* of server, or a permanently dead primary
            # would print a fallback notice on every single request.
            if self._serving is not endpoint:
                self._serving = endpoint
                position = "primary" if index == 0 else f"fallback #{index}"
                self._log(f"[Fallback] now serving from {endpoint} ({position})")
            return result, endpoint

        raise RuntimeError("every entry in the chain is unavailable: " + "; ".join(errors))


# --------------------------------------------------------------------------- #
# Building the chain                                                           #
# --------------------------------------------------------------------------- #

# Models that will accept a chat request and return something useless.
_UNSUITABLE = r"guardrail|content.safety|moderation|classifier|embed|rerank|\btts\b|whisper|image-gen"
_CODE_SPECIALIST = r"coding (agent|model)|agentic coding|code generation model"
_SLOW_ID = r"(^|[-/])r1|reasoning|thinking|qwq|distill"
_SLOW_TEXT = r"reasoning model|frontier.reasoning|thinking model|chain.of.thought"


def score_model_id(model_id, meta=None, penalise_slow=True):
    """Rough fitness for general chat. None means 'not a chat model'.

    Reads the catalog's metadata rather than matching remembered model families
    -- names you recognise are exactly the ones that have been delisted. Set
    penalise_slow=False if your workload is batch and latency does not matter.
    """
    mid = model_id.lower()
    meta = meta or {}
    name = str(meta.get("name", "")).lower()
    description = str(meta.get("description", "")).lower()
    blurb = f"{name} {description}"
    opening = description[:140]
    disclaimed = re.search(r"against|not recommended|avoid|discourage|rather than", opening)

    if re.search(_UNSUITABLE, mid) or re.search(_UNSUITABLE, blurb):
        return None
    if re.search(_CODE_SPECIALIST, name) or (re.search(_CODE_SPECIALIST, opening) and not disclaimed):
        return None

    score = 50.0
    active = re.search(r"-a(\d+(?:\.\d+)?)b", mid)
    totals = [float(t) for t in re.findall(r"(\d+(?:\.\d+)?)b", mid)]
    if active:
        score += min(float(active.group(1)), 30.0) / 3.0
    elif totals:
        score += min(totals[0], 30.0) / 3.0
    if totals:
        score += min(max(totals), 200.0) / 40.0
    if penalise_slow and (re.search(_SLOW_ID, mid) or re.search(_SLOW_TEXT, blurb)):
        score -= 30.0
    return score


def discover_openrouter_free(api_key, limit=6, timeout=15, require_tools=False):
    """Which :free models exist right now, best first.

    Catalog presence is not proof an endpoint serves -- that is what runtime
    classification and scripts/discover_free_models.py are for -- but it does
    guarantee the id was not deleted months ago.
    """
    request = urllib.request.Request(
        OPENROUTER_BASE + "/models",
        headers={"Authorization": f"Bearer {api_key}", "User-Agent": "fallback-chain/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.load(response)["data"]

    free = []
    for model in data:
        mid = model.get("id", "")
        params = model.get("supported_parameters") or []
        if not mid.endswith(":free") or "temperature" not in params:
            continue
        if require_tools and "tools" not in params:
            continue
        score = score_model_id(mid, model)
        if score is None:
            continue
        free.append((score, model.get("context_length") or 0, mid))

    free.sort(key=lambda row: (-row[0], -row[1], row[2]))
    return [mid for _score, _ctx, mid in free[:limit]]


def discover_provider_model(provider, api_key, timeout=15):
    """Best-scoring chat model a non-OpenRouter provider will admit to having.

    Falls back to a known-stable id if the listing is unreachable -- some of
    these endpoints sit behind Cloudflare and refuse plain Python user agents.
    """
    base = PROVIDER_BASES.get(provider)
    default = PROVIDER_DEFAULT_MODELS.get(provider)
    if not base:
        return default
    request = urllib.request.Request(
        base.rstrip("/") + "/models",
        headers={"Authorization": f"Bearer {api_key}",
                 "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) fallback-chain/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.load(response).get("data") or []
    except (urllib.error.URLError, OSError, ValueError, KeyError):
        return default

    ranked = []
    for model in data:
        # Google's OpenAI-compatible layer lists ids as "models/gemini-...".
        mid = (model.get("id") or "").split("/", 1)[-1] if provider == "gemini" else model.get("id")
        if mid and score_model_id(mid, model) is not None:
            ranked.append((score_model_id(mid, model), mid))
    return max(ranked)[1] if ranked else default


def load_verified_models(path=None):
    """Chain written by scripts/discover_free_models.py --json."""
    path = path or MODELS_FILE
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh).get("chain") or None
    except (OSError, ValueError):
        return None


def build_chain(openrouter_key=None, log=None, limit=6, require_tools=False, models_file=None):
    """Assemble the chain: verified entries if available, else live discovery.

    Order: OpenRouter models first (cheap hops, one bucket), then one entry per
    other provider the user has a key for -- those are what survive the
    account-wide daily cap.
    """
    log = log or (lambda msg: None)
    load_env_files()

    or_keys = keys_for("openrouter", openrouter_key)
    endpoints = []

    for entry in load_verified_models(models_file) or []:
        provider = entry.get("provider", "openrouter")
        model = entry.get("model")
        keys = keys_for(provider, openrouter_key if provider == "openrouter" else None)
        if model and keys:
            endpoints.append(Endpoint(provider, model, keys,
                                      base_url=entry.get("base_url"),
                                      bucket=entry.get("bucket")))
    if endpoints:
        log(f"[Fallback] loaded {len(endpoints)} verified entries")
        return FallbackChain(endpoints, log=log)

    if or_keys:
        try:
            for model in discover_openrouter_free(or_keys[0], limit, require_tools=require_tools):
                endpoints.append(Endpoint("openrouter", model, or_keys))
            log(f"[Fallback] discovered {len(endpoints)} free OpenRouter models")
        except (urllib.error.URLError, OSError, ValueError, KeyError) as exc:
            log(f"[Fallback] could not list OpenRouter models ({exc})")

    for provider in PROVIDER_DEFAULT_MODELS:
        keys = keys_for(provider)
        if keys:
            model = discover_provider_model(provider, keys[0])
            endpoints.append(Endpoint(provider, model, keys))
            log(f"[Fallback] added independent bucket: {provider}:{model}")

    if not endpoints:
        raise RuntimeError("No usable models. Set OPENROUTER_API_KEY, GROQ_API_KEY, "
                           "GOOGLE_API_KEY or CEREBRAS_API_KEY -- see examples/.env.example")

    buckets = {e.bucket for e in endpoints}
    if len(buckets) == 1:
        log("[Fallback] warning: every entry shares one quota bucket. When it runs "
            "dry the whole chain dies at once -- add a key from another provider.")
    return FallbackChain(endpoints, log=log)


if __name__ == "__main__":
    chain = build_chain(log=print)
    print(chain.describe())
    text, served_by = chain.chat([{"role": "user", "content": "Say hello in five words."}])
    print(f"\n{served_by}: {text}")
