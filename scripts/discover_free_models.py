#!/usr/bin/env python3
"""Discover which models your key can actually use, on any OpenAI-compatible provider.

Catalogs list models whose endpoints refuse to serve, and any model list you
remember is stale. This script calls each candidate for real and reports what
genuinely answers, so a chain only ever contains entries that work.

Usage:
    export OPENROUTER_API_KEY=sk-or-v1-...
    python discover_free_models.py                      # OpenRouter :free models
    python discover_free_models.py --require-tools      # agents: tool-calling only
    python discover_free_models.py --provider mistral   # a known provider
    python discover_free_models.py --base-url https://api.cerebras.ai/v1 \
                                   --key-env CEREBRAS_API_KEY
    python discover_free_models.py --base-url https://oai.endpoints.kepler.ai.cloud.ovh.net/v1 \
                                   --no-key              # OVHcloud: no signup, no key
    python discover_free_models.py --rank latency       # interactive workloads
    python discover_free_models.py --json > models.json # machine-readable chain
    python discover_free_models.py --prompt "Translate to Swedish: good evening"

Exit codes:
    0  at least one usable model found
    1  no usable models (or the key is bad)
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

# Every provider here speaks the OpenAI chat-completions dialect.
PROVIDERS = {
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai/", "GOOGLE_API_KEY"),
    "cerebras": ("https://api.cerebras.ai/v1", "CEREBRAS_API_KEY"),
    "nvidia": ("https://integrate.api.nvidia.com/v1", "NVIDIA_API_KEY"),
    "mistral": ("https://api.mistral.ai/v1", "MISTRAL_API_KEY"),
    # Cohere's own v2/chat shape is not OpenAI-compatible -- this is their
    # separate compatibility layer, which speaks the same dialect as the rest.
    "cohere": ("https://api.cohere.ai/compatibility/v1", "COHERE_API_KEY"),
}

# Some provider edges (Cloudflare) reject default Python user-agents with a
# 403 "error code: 1010". A normal UA avoids that misdiagnosis entirely.
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0 Safari/537.36")

# Error signature -> (label, what it means)
SIGNATURES = [
    ("matching your", "DATA-POLICY",
     "Your OpenRouter privacy settings exclude logging providers. FIXABLE - see below."),
    ("shared_pool", "SHARED-POOL",
     "Provider's shared key is saturated by other users. Not your quota; may recover."),
    ("is not found", "DEAD-DEPLOY",
     "Upstream deployment deleted. Stale catalog entry - exclude permanently."),
    ("not a valid model", "DEAD-MODEL",
     "Model ID no longer exists. Exclude permanently."),
    ("payment required", "NO-CREDIT",
     "No free-tier allowance active on this account."),
    ("error code: 1010", "CLOUDFLARE",
     "Browser-signature block, not a bad key."),
    ("user not found", "BAD-KEY",
     "The key was rejected. Check it, or that it belongs to this provider."),
    ("invalid api key", "BAD-KEY",
     "The key was rejected. Check it, or that it belongs to this provider."),
    ("no auth credentials", "BAD-KEY",
     "No usable credential was sent."),
    ("rate limit", "RATE-LIMIT",
     "Quota exhausted right now. Re-run later to judge this one."),
]

# Models that will accept a chat request and return something useless.
UNSUITABLE = r"guardrail|content.safety|moderation|classifier|embed|rerank|\btts\b|whisper|image-gen"
CODE_SPECIALIST = r"coding (agent|model)|agentic coding|code generation model"
SLOW_ID = r"(^|[-/])r1|reasoning|thinking|qwq|distill"
SLOW_TEXT = r"reasoning model|frontier.reasoning|thinking model|chain.of.thought"


def classify(detail):
    for needle, label, meaning in SIGNATURES:
        if needle.lower() in detail.lower():
            return label, meaning
    return "ERROR", detail[:110]


def score_model(model):
    """Rough fitness for general chat work. None means 'not a chat model'.

    Deliberately reads the catalog's own metadata rather than matching model
    families by name -- the free tier turns over completely every few months and
    a hardcoded preference list is stale before it ships.
    """
    mid = model.get("id", "").lower()
    name = str(model.get("name", "")).lower()
    description = str(model.get("description", "")).lower()
    blurb = f"{name} {description}"
    # Model cards lead with what the model is for, so only the opening counts --
    # and "advises against agentic coding" must not read as "is a coding model".
    opening = description[:140]
    disclaimed = re.search(r"against|not recommended|avoid|discourage|rather than", opening)

    if re.search(UNSUITABLE, mid) or re.search(UNSUITABLE, blurb):
        return None
    if re.search(CODE_SPECIALIST, name) or (re.search(CODE_SPECIALIST, opening) and not disclaimed):
        return None

    score = 50.0
    # MoE ids spell the active parameter count out as "-a4b"; dense models give one number.
    active = re.search(r"-a(\d+(?:\.\d+)?)b", mid)
    totals = [float(t) for t in re.findall(r"(\d+(?:\.\d+)?)b", mid)]
    if active:
        score += min(float(active.group(1)), 30.0) / 3.0
    elif totals:
        score += min(totals[0], 30.0) / 3.0
    if totals:
        score += min(max(totals), 200.0) / 40.0
    if re.search(SLOW_ID, mid) or re.search(SLOW_TEXT, blurb):
        score -= 30.0
    if "multilingual" in blurb:
        score += 5.0
    return score


def http_json(url, key, payload=None, timeout=90):
    headers = {"User-Agent": UA}
    if key:
        headers["Authorization"] = "Bearer " + key
    data = None
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    with urllib.request.urlopen(urllib.request.Request(url, data, headers), timeout=timeout) as fh:
        return json.load(fh)


def list_models(base_url, key, timeout, free_only):
    data = http_json(base_url.rstrip("/") + "/models", key, timeout=timeout)["data"]
    if free_only:
        data = [m for m in data if m.get("id", "").endswith(":free")]
    return data


def probe(base_url, key, model_id, prompt, timeout):
    """Return (ok, seconds, detail). Sends a real completion request."""
    payload = {"model": model_id,
               "messages": [{"role": "user", "content": prompt}],
               "max_tokens": 64}
    started = time.time()
    try:
        body = http_json(base_url.rstrip("/") + "/chat/completions", key, payload, timeout)
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode())["error"]["message"]
        except Exception:
            detail = f"HTTP {exc.code}"
        return False, time.time() - started, detail
    except Exception as exc:  # network, TLS, timeout
        return False, time.time() - started, str(exc)

    elapsed = time.time() - started
    try:
        reply = (body["choices"][0]["message"]["content"] or "").strip()
    except (KeyError, IndexError, TypeError):
        return False, elapsed, "malformed response"
    if not reply:
        # Overloaded endpoints answer 200 with nothing. So do reasoning models
        # that spent the whole budget thinking. Both are failures.
        return False, elapsed, "empty completion"
    return True, elapsed, reply.replace("\n", " ")[:60]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--provider", default="openrouter", choices=sorted(PROVIDERS),
                    help="known provider to probe (default: openrouter)")
    ap.add_argument("--base-url", help="any OpenAI-compatible endpoint; overrides --provider")
    ap.add_argument("--key-env", help="env var holding the key for --base-url")
    ap.add_argument("--key", help="key value (default: read the provider's env var)")
    ap.add_argument("--no-key", action="store_true",
                    help="provider needs no key at all (e.g. OVHcloud AI Endpoints)")
    ap.add_argument("--all", action="store_true",
                    help="probe paid models too, not just :free ones")
    ap.add_argument("--require-tools", action="store_true",
                    help="keep only models advertising tool-calling (agents need this)")
    ap.add_argument("--rank", default="score", choices=("score", "latency", "context"),
                    help="ordering of the surviving models (default: score)")
    ap.add_argument("--limit", type=int, default=0, help="probe at most N candidates")
    ap.add_argument("--prompt", default="Reply with the single word: ready",
                    help="probe prompt; use a real one from your workload")
    ap.add_argument("--timeout", type=int, default=90, help="per-request timeout, seconds")
    ap.add_argument("--json", action="store_true",
                    help="emit a machine-readable chain on stdout instead of a report")
    args = ap.parse_args()

    if args.base_url:
        base_url = args.base_url
        key_env = args.key_env or ("" if args.no_key else "OPENROUTER_API_KEY")
        # Name the bucket after its key variable: CEREBRAS_API_KEY -> cerebras.
        provider = (re.sub(r"_api_key.*$", "", key_env, flags=re.I).lower()
                    if key_env else "custom")
    else:
        base_url, key_env = PROVIDERS[args.provider]
        provider = args.provider

    key = args.key or os.environ.get(key_env)
    if not key and not args.no_key:
        print(f"error: no key. Set {key_env}, pass --key, or pass --no-key "
              "if this provider genuinely needs none", file=sys.stderr)
        return 1

    out = sys.stderr if args.json else sys.stdout
    free_only = not args.all and provider == "openrouter"

    try:
        catalog = list_models(base_url, key, args.timeout, free_only)
    except Exception as exc:
        print(f"error: could not list models from {base_url}: {exc}", file=sys.stderr)
        return 1

    print(f"\nScreening {len(catalog)} models listed by {base_url}\n", file=out)
    candidates = []
    for model in catalog:
        mid = model.get("id")
        if not mid:
            continue
        if args.require_tools and "supported_parameters" in model:
            if "tools" not in (model.get("supported_parameters") or []):
                print(f"  NO-TOOLS  {mid:<52} (cannot drive an agent)", file=out)
                continue
        score = score_model(model)
        if score is None:
            print(f"  SKIP      {mid:<52} not a general chat model", file=out)
            continue
        candidates.append((score, model.get("context_length") or 0, mid))

    candidates.sort(key=lambda row: (-row[0], -row[1], row[2]))
    if args.limit:
        candidates = candidates[: args.limit]

    print(f"\nProbing {len(candidates)} candidates with a real request\n", file=out)

    usable, policy_blocked = [], 0
    for score, ctx, mid in candidates:
        ok, elapsed, detail = probe(base_url, key, mid, args.prompt, args.timeout)
        if ok:
            usable.append({"provider": provider, "model": mid, "base_url": base_url,
                           "key_env": key_env or None, "context": ctx,
                           "latency_s": round(elapsed, 2), "score": round(score, 1)})
            print(f"  LIVE      {mid:<52} {elapsed:5.1f}s  ctx={ctx:<9} {detail}", file=out)
        else:
            label, meaning = classify(detail)
            policy_blocked += label == "DATA-POLICY"
            print(f"  {label:<9} {mid:<52} {meaning[:60]}", file=out)

    print(f"\n{'=' * 78}", file=out)
    print(f"{len(usable)} usable, {len(candidates) - len(usable)} failed\n", file=out)

    if policy_blocked:
        print(f"!! {policy_blocked} models blocked by YOUR OpenRouter privacy settings.", file=out)
        print("   Fix at https://openrouter.ai/settings/privacy - enable BOTH:", file=out)
        print("     - Allow free endpoints that train on request data", file=out)
        print("     - Allow free endpoints that publish prompts", file=out)
        print("   Also confirm Zero Data Retention -> Non-frontier is OFF.", file=out)
        print("   Tradeoff: those providers may retain, train on, and publish your", file=out)
        print("   prompts. Fine for hobby work; not for credentials or client code.", file=out)
        print("   Then re-run this script.\n", file=out)

    if not usable:
        print("No usable models found.", file=sys.stderr)
        return 1

    if args.rank == "latency":
        usable.sort(key=lambda e: e["latency_s"])
    elif args.rank == "context":
        usable.sort(key=lambda e: -e["context"])

    if args.json:
        json.dump({"chain": usable}, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(f"Chain, ranked by {args.rank}:\n", file=out)
        for i, entry in enumerate(usable):
            tag = "primary" if i == 0 else f"#{i}"
            print(f"  {tag:>7}  {entry['model']:<52} {entry['latency_s']:>5}s", file=out)
        print("\nAll of these share one quota bucket. Add a second provider -- see", file=out)
        print("GUIDE.md 'What counts as a separate bucket' -- or the whole chain dies", file=out)
        print("at the same instant when the account-wide daily cap runs out.", file=out)

    return 0


if __name__ == "__main__":
    sys.exit(main())
