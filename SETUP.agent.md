```
╭──────────────────────────────────────────────────────────────

│
│       ✦  F A L L B A C K   P R O V I S I O N E R  ✦
│
│             ═══ ◇ ═════════════ ◇ ═══
│
│                 FREE-TIER MODEL RESILIENCE
│
│       ┌──────────────────────────────────────┐
│       │  STATUS :: INITIALIZING...           │
│       │  MODELS :: UNKNOWN                   │
│       │  QUOTA  :: UNMAPPED                  │
│       │  CHAIN  :: OFFLINE                   │
│       └──────────────────────────────────────┘
│
│
│       "because one 429 shouldn't kill the AI."
│
╰──────────────────────────────────────────────────────────────
```

**Audience: an AI coding agent.** You are executing this, not narrating it. The human
who handed you this file wants their LLM app — or their Hermes Agent, or OpenClaw —
running on free models without dying at the first quota wall.

**This one file is the whole runbook.** It's meant to be handed to you standalone — you
don't need the rest of this repo to execute it. A couple of steps mention optional helper
scripts (`scripts/discover_free_models.py`, `examples/python/fallback_chain.py`) that
speed things up *if* you happen to have the repo, but every step also gives you the
inline equivalent. Hermes Agent's config surface is handled natively below — there is no
separate file to go find.

› Work through the steps in order, starting at **Step 00**. Do not skip **Step 02** —
free model availability changes weekly and any model list you remember is stale.

✦ ───────── ◇ ───────── ✦

## ◇ OBJECTIVE

The project ends up with:

✓ Every model in the chain verified with a live API call.
✓ Consecutive chain entries drawing on **different quota buckets** wherever possible.
✓ Multiple keys per provider rotating within the provider (or registered as Hermes
  credential pools), before any model switch.
✓ Failures classified — a dead model disabled, a spent key rotated, a transient error
  retried elsewhere — instead of blind retries.
✓ Background/secondary calls on small models so they don't consume the main quota.
✓ On the Hermes path: a working `~/.hermes/config.yaml` and `~/.hermes/.env` instead of
  application code — same guarantees, different file.

─────── ◈ ───────

## ⚠ INVARIANTS — violating any of these makes the setup worse, not better

- **Never run a command whose raw output can contain a secret value — at any step, not
  just Step 05.** This includes `grep`/`cat`/`type`/`Get-Content` against `.env` or
  `config.yaml`, a Python script that reads a key and prints even a truncated slice of
  it, and `hermes doctor`/verbose logs if they ever echo a value back. Tool output lands
  in the visible transcript the same way chat text does — "just for diagnostics" is not
  an exception. To check whether a variable is *present*, grep for the variable **name**
  only, never let the match include `=<value>` (`grep -c '^DISCORD_BOT_TOKEN='`, not
  `grep '^DISCORD'`). To check whether a value is *valid*, do it inside a subprocess that
  reads the file itself and prints only a verdict (`LIVE`/`DEAD`, `valid`/`invalid`) —
  same pattern as the verify script in Step 05 step 3 and Step 07, applied everywhere,
  not just there. If a key does end up in a tool result or the chat despite this, say so
  immediately and tell the human to rotate it — don't quietly continue as if it didn't
  happen.
- **Never write an API key into code or into a config file that might be committed.**
  Keys live in the environment or a gitignored `.env`.
- **Never add a model you have not successfully called.** Catalogs list models whose
  endpoints refuse to serve. An unverified entry burns a failover hop on every request.
- **Never add a model that lacks a capability the app depends on** — tool calling for an
  agent, vision for image input, a large context for long documents. It fails on first
  use, every time.
- **Do not invent model IDs.** Use exactly what Step 02 returns.
- **Do not restrict data collection on OpenRouter** (`data_collection: "deny"` or the
  equivalent privacy setting). It removes nearly every free endpoint from routing.
- **(⚡ Hermes path) Never write an API key into `config.yaml`.** Keys live in
  `~/.hermes/.env`, referenced with `key_env: VAR_NAME`.
- **(⚡ Hermes path) `key_env` is valid in `fallback_providers` only.** Entries under
  `auxiliary.<task>.fallback_chain` accept only `provider`, `model`, `base_url`,
  `api_key`, `timeout` — no env-var indirection there.
- Re-running this runbook must be safe. Check before appending to any `.env`.

```
🛡️  CREDENTIAL SAFETY

API keys NEVER belong in:

    ✕ source code
    ✕ committed config
    ✕ this chat, if you can possibly avoid it
    ✕ command output — including `grep`/`cat`/diagnostic
      scripts run at ANY step, not just while writing them

Keys belong in:

    ✓ environment variables
    ✓ a gitignored `.env`
    ✓ pasted straight into the file by the human —
      never typed through you (Step 05)

──────── ◈ ════════ ◈ ────────

⟡ SECURITY RULE ⟡
```

✦ ───────── ◇ ───────── ✦

## ◇ TALKING TO THE USER — the interface kit

This runbook is a conversation with a tiny AI provisioning console, not a form. Use these
conventions for every prompt you send the human, starting at Step 00.

**› Links open with Ctrl+Click** (Cmd+Click on macOS). Say this the first time you send a
link in a session — nobody needs to copy/paste out of a terminal.

**› One question at a time.** Ask, wait for the reply, then send the next box. Never
stack two questions in a single message.

**› Secrets never go through the chat if you can avoid it.** Open the target file
directly and let the human paste into it themselves — see Step 05 for the mechanics.

**› Small questions get a small box** — a closed frame around the question only, with
lettered options listed underneath it, unwalled:

```
╭──────────────────────────────────────────────────╮
│ 🔀 WHAT'S THIS FALLBACK CHAIN FOR?
╰──────────────────────────────────────────────────╯

  【 A 】  🤖 A regular chatbot
  【 B 】  🕸️ A multi-channel agent
  【 C 】  🌐 A webapp or service
  【 D 】  👽 Something else

  › Reply with a letter.
```

**› An option that needs more than a label gets a plain indented line under it — never a
`│` continuation.** The same "unwalled" rule applies once options carry an explanation,
not just a short label; a stray `│` hanging off a removed frame is the same visual break
the bare-heading rule above exists to avoid, just one level down:

```
╭──────────────────────────────────────────────────╮
│ 🔐  WHO'S ALLOWED TO TALK TO THE BOT?
╰──────────────────────────────────────────────────╯

  【 A 】  👤 Just me — DISCORD_ALLOWED_USERS=<your id>
          Safest. Bot responds only to you, in DMs or
          any channel both of you can see.

  【 B 】  🔓 Open — DISCORD_ALLOW_ALL_USERS=true
          Anyone who can see the bot can trigger it.
          Fine on a private server with friends, risky
          in a public one.

  › Reply with a letter.
```

Blank line between options once they carry explanations — it's what keeps a four-option
question skimmable instead of a wall of text.

**› Big moments get a bare heading, never a box** — system state, warnings, hard stops,
completion, anything running past one line. Box-drawing (`╭ │ ╰ ╮ ╯`) is reserved
entirely for the single-line closed question box above; the moment content wraps to a
second line, drop the frame instead of stretching it. Use a `◇ HEADING`, then plain body
text below, one thought per line:

```
◇ LIKE THIS

Longer explanations, status, whatever needs room to breathe live here, one thought
per line.
```

If the message has more than one beat — facts, then a verdict; a scan, then a result —
separate them with this divider, and only then close with a state line:

```
◇ WHAT HAPPENED

First beat: what you found, one thought per line.

──────── ◈ ════════ ◈ ────────

Second beat: the conclusion, or what happens next.

⟡ STATE ⟡
```

Skip the divider and the `⟡ STATE ⟡` line on a single-beat panel — they mark a
transition between parts, not decoration to add on every message.

**› Symbol vocabulary** — keep these meanings fixed everywhere in this file:

| Symbol | Meaning |
|---|---|
| `✦` | major identity / important heading |
| `◇` | stage / subsystem |
| `◈` | transition / divider |
| `⟡` | waiting / user input / system state |
| `◌` | processing / scanning |
| `◎` | active / online |
| `✓` | verified / successful |
| `⚠` | warning |
| `✕` | failure / exclusion |
| `→` | progression |
| `›` | next action |
| `【 A 】` | selectable option |
| `⚡` | this step branches — Hermes path |
| `🌐` | this step branches — generic / OpenClaw path |

**› Emoji, used sparingly** — cute and futuristic, not Discord spam. One per option or
concept, never one per line:

```
⚡ Hermes Agent      🦞 OpenClaw         👽 something else / unknown
🤖 chatbot           🕸️ multi-channel    🌐 webapp
💬 chat              🧠 model            🔑 credentials
🔄 fallback          🛡️ security         📡 API / network
🧪 testing           📁 install location
```

**› A tiny ASCII face, once in a while, when a moment earns it** — not on every line:

```
✓ Model responded!        (｡•̀ᴗ-)✧
⚠ Endpoint refused.       (╥﹏╥)
◌ Probing endpoint...     (¬‿¬)
```

The boxed prompts through the rest of this file show the shape to reproduce — the exact
wording is yours to adapt to the conversation.

✦ ───────── ◇ ───────── ✦

## ✦ STEP 00 — INTENT

◇ Ask what this is for

Before grepping anything, ask the user what the fallback chain will sit behind. The
answer changes what Step 02 filters for, what Step 01's workload question resolves to,
and — for Hermes — replaces the whole "write application code" track with "write a
config file" track from Step 05 onward.

```
╭──────────────────────────────────────────────────╮
│ 🔀 WHAT'S THIS FALLBACK CHAIN FOR?
╰──────────────────────────────────────────────────╯

  【 A 】  🤖  A regular chatbot — Discord, Telegram, Slack, or similar
  【 B 】  🕸️  A multi-channel agent — Hermes, OpenClaw, or similar
  【 C 】  🌐  Integrated into a webapp or service
  【 D 】  👽  Something else — just tell me

  › Reply with a letter.
```

Route on the answer:

**【 A 】 chatbot.** Ask one follow-up, on its own message, and wait:

```
╭──────────────────────────────────────────────────╮
│ 💬 WHICH PLATFORM?
╰──────────────────────────────────────────────────╯

  【 A 】  Discord
  【 B 】  Telegram
  【 C 】  Slack
  【 D 】  👽 Something else

  › Reply with a letter.
```

If they answer **Discord**, flag it — you'll walk them through creating a bot in
**Step 04a**, during key collection. Then treat this as a low-latency interactive
workload for Step 01: reasoning models are usually the wrong default (see Reference
section) unless the user explicitly wants depth over speed.

**【 B 】 multi-channel agent.** Ask one follow-up, on its own message, and wait:

```
╭──────────────────────────────────────────────────╮
│ 🧰 WHICH TOOL ARE WE CONFIGURING?
╰──────────────────────────────────────────────────╯

  【 A 】  ⚡ Hermes Agent
  【 B 】  🦞 OpenClaw
  【 C 】  👽 Something else

  › Reply with a letter.
```

- **⚡ Hermes** — this file has you covered natively. Every step from here on marks its
  Hermes-specific branch with ⚡; steps with no ⚡ branch are identical either way. Hermes
  writes the chain into its own `config.yaml` and credential pools instead of application
  code (Steps 05a and 06).
- **🦞 OpenClaw** — Step 01 has an install/verify branch for it (`openclaw --version`,
  the installer one-liners, `openclaw onboard`). Beyond installation, no tool-specific
  config-writing branch exists yet, so follow the 🌐 generic branch for the rest — most
  of these tools speak an OpenAI-compatible API, so the chain logic in Step 06's generic
  branch usually ports in with minimal changes. Because it drives an agent, treat
  tool-calling as required in Step 02 (`--require-tools`).
- **Anything else** — same as OpenClaw above, minus the Step 01 install branch: follow
  🌐 generic throughout.

If OpenClaw (or something else) was picked, ask where it should live — this decides
where Step 01 looks for (or installs) the thing:

```
╭──────────────────────────────────────────────────╮
│ 📁 WHERE SHOULD IT LIVE?
╰──────────────────────────────────────────────────╯

  【 A 】  📍 Right here — the current working directory
  【 B 】  🗂️  Somewhere else — I'll paste a path

  › Reply with a letter.
```

If **B**, ask for the path as free text and wait — not a lettered reply this time:

```
  › Paste the filepath:
```

Record the answer as `<INSTALL_LOCATION>`; Step 01's 🦞 branch uses it.

**If Hermes was picked, ask the layout question instead — it is not the same question.**
The official installer has no "install here" flag; it reads `HERMES_HOME` and puts
*everything* under it — code, the venv, and all user data (`config.yaml`, `.env`,
`sessions/`, `skills/`, `logs/`, `cron/`, `cache/`, `state.db`, …). There is no built-in
knob for "code in the project, data at home." Picking "right here" without understanding
that just moves your whole data directory into the project unless you also do a
from-source install — say so before asking:

```
╭──────────────────────────────────────────────────╮
│ 🔧 HOW SHOULD HERMES BE LAID OUT?
╰──────────────────────────────────────────────────╯

  【 A 】  📦 Standard — ~/.hermes, everything in your home directory
  【 B 】  🪛 From-source in this project, data stays at ~/.hermes
  【 C 】  🪛 From-source in this project, data moves in too

  › Reply with a letter.
```

- **A — standard.** Use the official installer as-is. `<HERMES_HOME>` = `~/.hermes`
  (subject to the `HERMES_HOME` check in Step 01). `hermes update` keeps working. Nothing
  Hermes-related lives in the project directory. This is what the rest of this runbook
  assumes unless told otherwise.
- **B — from-source, split.** `git clone` the repo into `<INSTALL_LOCATION>`, build the
  venv there yourself (Step 01 has the commands), and leave `HERMES_HOME` unset so data
  stays at the default `~/.hermes`. Clean separation — code you can `git pull`, data that
  doesn't clutter the repo — but `hermes update` no longer works; updates are a manual
  `git pull` instead.
- **C — from-source, self-contained.** Same clone as B, but also set `HERMES_HOME` to a
  path under `<INSTALL_LOCATION>` (e.g. `<INSTALL_LOCATION>/.hermes`). Everything —
  code, venv, config, sessions, keys — lives inside the project. Fully portable, but
  `.env` and the rest now sit inside a project directory that must be gitignored (not
  just `.env` itself — the whole `HERMES_HOME` subdirectory), and every invocation needs
  `HERMES_HOME` set or exported, since there's no per-command flag for it.

If **B** or **C**, ask for the path as free text and wait:

```
  › Paste the filepath:
```

Record the answer as `<INSTALL_LOCATION>`. Whichever option was picked, this is what
Step 01 resolves `<HERMES_HOME>` from — combined with the live `HERMES_HOME` check
described there, since a pre-existing env var can still override any of this.

Either way, ask which channel(s) it runs on — this is what actually decides whether a
Discord bot needs creating:

```
╭──────────────────────────────────────────────────╮
│ 📡 WHICH CHANNEL(S)?
╰──────────────────────────────────────────────────╯

  【 A 】  💬 Discord
  【 B 】  📡 Telegram / Slack / other chat platform
  【 C 】  🌐 Web UI only — no chat platform
  【 D 】  👽 Not sure yet

  › Reply with a letter.
```

If Discord is in the mix:

```
        ✦ CHANNEL ROUTE DETECTED ✦

        ⚡ HERMES AGENT  /  🦞 OPENCLAW
                 │
                 ◇
                 ↓
             💬 DISCORD
                 │
                 ◇
                 ↓
        🧠 FALLBACK CHAIN
                 │
                 ◇
                 ↓
          ◈ FREE MODEL POOL
```

flag it — walk them through bot creation in **Step 04a** once you reach key collection.

**【 C 】 webapp/service.** Continue with this runbook as written. Ask what the response
is used for (chat completion, structured extraction, etc.) — that also feeds Step 01.

**【 D 】 other.** Let them describe it, then judge which of the three patterns above it's
closest to and proceed accordingly.

✦ ───────── ◇ ───────── ✦

## ✦ STEP 01 — TARGET / INSTALL

◇ Locate what you're configuring

**🌐 Generic / OpenClaw path:** find, and write down, four things before changing
anything:

1. **Where the model is chosen.** Grep for a base URL (`openrouter.ai`, `api.groq.com`,
   `generativelanguage`), a client construction (`OpenAI(`, `new OpenAI`,
   `ChatOpenAI`), or a model id string. A hardcoded model id is usually the whole bug.
2. **How the key is supplied** — env var, `.env`, config file, UI field. Note the exact
   variable names already in use so you don't invent parallel ones.
3. **Whether the app already has a retry or fallback layer.** Two competing retry layers
   are worse than one; disable the SDK's own retries (`max_retries=0`) and let the chain
   own the decision.
4. **What the workload needs.** This decides how you rank models in Step 04:
   interactive/voice needs low latency above all; an agent needs tool calling; document
   work needs context length. Step 00's answer usually settles this already.

Also check whether `.env` is gitignored. If it isn't yet, this is a hard stop until you
fix it — not a note for later:

```
✕  PROVISIONING HALTED

This setup cannot safely continue yet.

Reason:
`.env` is not protected by `.gitignore`.

No credentials will be written until this is fixed.

──────── ◈ ════════ ◈ ────────

⟡ SETUP PAUSED ⟡
```

Fix it yourself — add `.env` to `.gitignore` (create the file if it doesn't exist) — then
continue. This is a self-resolving stop, not something to hand to the user.

**⚡ Hermes path:** recall which layout Step 00 settled on (**A** standard, **B**
from-source split, or **C** from-source self-contained) and `<INSTALL_LOCATION>` if B or
C was picked.

**Resolve `<HERMES_HOME>` first, before installing or looking for anything — this step
is the same regardless of layout, and skipping it is what causes a "why is Hermes
installed in the wrong place" bug later.** The installer never asks for a directory; it
reads `HERMES_HOME` and, if unset, defaults to `~/.hermes`. Check both the live shell and
the persisted value — on Windows the two can disagree, since the registry value survives
across terminals and reboots even when the current shell looks clean:

```bash
echo "HERMES_HOME=$HERMES_HOME"
```

```powershell
# Windows — persisted value can differ from what's live in the current shell
[Environment]::GetEnvironmentVariable('HERMES_HOME', 'User')
[Environment]::GetEnvironmentVariable('HERMES_HOME', 'Machine')
```

**If layout A or B was picked** (data expected at the default `~/.hermes`) **and
`HERMES_HOME` is already set to something else**, stop and ask before installing or
looking anywhere else — a leftover value here is exactly what silently redirects the
install, and re-running the installer after deleting that directory just recreates it in
the same wrong place:

```
╭──────────────────────────────────────────────────╮
│ 📁 HERMES_HOME IS ALREADY SET
╰──────────────────────────────────────────────────╯

  Found HERMES_HOME = <VALUE>
  This is where Hermes will install and read config from — not ~/.hermes.

  【 A 】  ✅ Reuse it — treat <VALUE> as the config home
  【 B 】  🧹 Reset it — unset HERMES_HOME and use the standard ~/.hermes instead

  › Reply with a letter.
```

- **Reuse:** set `<HERMES_HOME>` = the existing value for the rest of this runbook.
  Check whether it already holds a working install before installing again — it may be
  the correct, intentional location, not leftover junk.
- **Reset:** unset `HERMES_HOME` for the current shell and remove its persisted value so
  it doesn't silently reassert itself later, then set `<HERMES_HOME>` = `~/.hermes`:

```bash
unset HERMES_HOME   # current shell
```

```powershell
[Environment]::SetEnvironmentVariable('HERMES_HOME', $null, 'User')
[Environment]::SetEnvironmentVariable('HERMES_HOME', $null, 'Machine')  # needs admin; skip if it errors
```

  Only delete the old directory if the human confirms it's not holding anything they
  want — it's a destructive step, not an automatic one.

If `HERMES_HOME` was unset from the start on layout A or B, `<HERMES_HOME>` = `~/.hermes`
and none of the above applies.

**If layout C was picked**, you're not just checking `HERMES_HOME`, you're deliberately
setting it — but the same stop applies if it's already set to something you didn't
expect; confirm with the human whether to override it or keep the existing value before
proceeding. Otherwise set it explicitly to a path under the project:

```bash
export HERMES_HOME="<INSTALL_LOCATION>/.hermes"    # current shell — every invocation needs this
```

```powershell
[Environment]::SetEnvironmentVariable('HERMES_HOME', "<INSTALL_LOCATION>\.hermes", 'User')
```

Now find or install, branching on layout:

**A — standard install.** Everything (code, venv, and data) lands under `<HERMES_HOME>`;
there's no separate location to track.

```bash
ls -a <HERMES_HOME>/     # config dir — create if absent
which hermes             # find the CLI on PATH
```

If nothing is found and the human wants a fresh install:

```bash
# Linux / macOS / WSL2 / Termux
curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash
source ~/.bashrc   # or ~/.zshrc — reload PATH before the next command
```

```powershell
# Windows, native PowerShell — bundles Python 3.11, Node.js, uv, ripgrep, ffmpeg, Git Bash
iex (irm https://hermes-agent.nousresearch.com/install.ps1)
```

**B or C — from-source.** Clone into `<INSTALL_LOCATION>` and build the venv there
(`cd <INSTALL_LOCATION>` first if it's not the current directory):

```bash
git clone https://github.com/NousResearch/hermes-agent.git <INSTALL_LOCATION>
```

Don't guess the venv/dependency setup from memory — the official one-line installer
bundles specific pinned tooling (`uv`, a matched Python version) that a hand-rolled
`python -m venv` + `pip install` may not reproduce correctly. Read the cloned repo's own
`README`/`CONTRIBUTING`/build scripts for the current from-source build command and run
that instead of inventing one.

```bash
which hermes || ls <INSTALL_LOCATION>/venv/Scripts/hermes.exe || ls <INSTALL_LOCATION>/venv/bin/hermes
```

**All layouts — verify and pick a provider before touching `config.yaml`:**

```bash
hermes --version        # confirm the install landed on PATH
hermes doctor           # health check — flags missing deps before you debug something else
hermes setup            # or: hermes model  — interactive provider/model picker
hermes config path       # prints the active config.yaml location — confirm it matches <HERMES_HOME>
hermes config env-path   # prints the active .env location — same check
hermes chat -q "Reply with one sentence confirming Hermes works."
```

If `hermes config path` doesn't match `<HERMES_HOME>`, something is still overriding it
(a different env var, a per-invocation flag) — stop and reconcile before continuing;
don't proceed on a mismatch and hope it doesn't matter.

Prerequisites the installer expects on PATH already: `git`. Everything else (Python,
Node.js, ripgrep, ffmpeg) is bundled by the installer itself, so don't pre-install them
separately. One model provider is required at `hermes setup` time — Nous Portal login,
an OpenRouter/OpenAI/Anthropic key, or a local provider like Ollama all work; this repo's
fallback chain slots in as (or alongside) that provider in Step 05a/06.

Record the CLI path either way; you need it in Step 05a.

If `<HERMES_HOME>/.env` already exists, read it and note which keys are already present
— do not clobber them. The gitignore hard-stop above doesn't apply here (the config
lives outside any repo, in the home directory) unless `<HERMES_HOME>` or
`<INSTALL_LOCATION>` itself turns out to be inside a tracked repo — if so, apply the same
check to whatever gets written there.

**🦞 OpenClaw path:** OpenClaw has no fixed home-directory config path the way Hermes
does — check whether it's already installed before offering to install it:

```bash
which openclaw
openclaw --version
```

If nothing is found and the human wants a fresh install, into `<INSTALL_LOCATION>` if
it's a source checkout, otherwise globally:

```bash
# macOS / Linux / WSL2 — one-liner
curl -fsSL https://openclaw.ai/install.sh | bash
```

```powershell
# Windows PowerShell
iwr -useb https://openclaw.ai/install.ps1 | iex
```

```bash
# npm/pnpm instead, if the human already manages Node tooling that way
npm install -g openclaw@latest --allow-scripts=openclaw

# or from source, into <INSTALL_LOCATION>
git clone https://github.com/openclaw/openclaw.git <INSTALL_LOCATION>
cd <INSTALL_LOCATION> && corepack enable && pnpm install
```

Then onboard and verify:

```bash
openclaw onboard --install-daemon
openclaw gateway status
openclaw dashboard
```

Prerequisite: Node.js 22.22.3+, 24.15+, or 25.9+ (the curl/PowerShell installers bring
their own Node if none is found; the npm and source paths need it on PATH already).
Onboarding is where OpenClaw asks for a model provider — same slot this repo's fallback
chain fills. Record wherever `openclaw onboard` writes its config so the generic 🌐
branch in later steps knows where to write the chain.

✦ ───────── ◇ ───────── ✦

## ✦ STEP 02 — MODEL DISCOVERY

◇ Discover which free models actually work

Ask the user for an OpenRouter API key if `OPENROUTER_API_KEY` is not already set
(free, no card: `openrouter.ai/settings/keys`).

If you have the repo, this ships as a script — prefer it, it also probes non-OpenRouter
providers:

```bash
python scripts/discover_free_models.py                  # probe everything
python scripts/discover_free_models.py --require-tools  # agents: tool-calling only
python scripts/discover_free_models.py --json           # machine-readable output
```

**⚡🦞 Hermes / OpenClaw path:** always use `--require-tools` (or the inline equivalent
below, filtered the same way) — an agent that can't call tools can't drive either of
these.

Standalone equivalent, if you don't have the script — this calls every free model rather
than trusting the catalog, which is the part that actually matters:

```python
import json, urllib.request

KEY = "<OPENROUTER_API_KEY>"

models = json.load(urllib.request.urlopen(
    "https://openrouter.ai/api/v1/models", timeout=30))["data"]
free = sorted((m for m in models if m["id"].endswith(":free")),
              key=lambda m: -(m.get("context_length") or 0))

for m in free:
    tools = "tools" in (m.get("supported_parameters") or [])
    body = json.dumps({"model": m["id"],
                       "messages": [{"role": "user", "content": "hi"}],
                       "max_tokens": 5}).encode()
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions", body,
        {"Authorization": "Bearer " + KEY, "Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=90)
        print(f"LIVE  {m['id']:<50} ctx={m.get('context_length'):<9} tools={tools}")
    except Exception as e:
        try:    d = json.loads(e.read().decode())["error"]["message"][:100]
        except Exception: d = str(e)
        print(f"DEAD  {m['id']:<50} {d}")
```

Keep only rows that are `LIVE` and have whatever capability the app needs (`tools=True`
for an agent).

While it runs, you can narrate progress in an open panel if you like — fill in real
numbers from the script's actual output, never invented ones, and skip the panel
entirely rather than guess:

```
✦ FALLBACK PROVISIONER

◇ MODEL DISCOVERY

◌  scanning live endpoints...

    Candidates       <N>
    Live              <N>
    Tool-capable      <N>
    Compatible        <N>

    (｡•̀ᴗ-)✧  looking for survivors...

──────── ◈ ════════ ◈ ────────

⟡ SCANNING ⟡
```

**Filter on the catalog's description, not on model names you recognise.** Guardrail,
moderation, embedding, rerank and coding-agent models all accept a chat request and
return something useless. Watch for negation: "advises against agentic coding" describes
a general model, not a coding one.

Optional flourish, use sparingly: when you want to call out one exceptional find — the
new primary, say — you can present it as a little module instead of a table row. Don't
do this for every model in a long list; a table is better for that.

```
◇ VERIFIED MODEL

🧠 provider/model-name

    TOOLS       ✓
    VISION      ✓
    CONTEXT     ✓

    QUOTA       ◈ BUCKET A
    STATUS      ◎ READY

    (ﾉ◕ヮ◕)ﾉ*:･ﾟ✧
```

Only display capabilities you actually verified.

✦ ───────── ◇ ───────── ✦

## ✦ STEP 03 — FAILURE TRIAGE

◇ Classify every failure before moving on

Do not silently discard `DEAD` rows. Each error means something different and one of
them is fixable by the user in 30 seconds.

| Error signature | Meaning | Your action |
|---|---|---|
| `404 No endpoints available matching your ... data policy` | The user's OpenRouter privacy settings exclude logging providers — which is most of the free tier | **Stop and tell the user.** See Step 03a. This typically unlocks the best models. |
| `429 ... limit_source: upstream_provider_shared_pool` | Provider's shared key saturated by other users, not the user's quota | Usable but unreliable — place near the bottom of the chain |
| `404 Function id '...' is not found` | Upstream deployment deleted; stale catalog entry | Exclude permanently. Note it in your report. |
| `402 Payment Required` | No free-tier allowance on that account | Exclude. Tell the user to check that provider's billing page. |
| `403 error code: 1010` | Cloudflare browser-signature block on `python-urllib`, **not** a bad key | Retry with `User-Agent: Mozilla/5.0 ...` before concluding anything |
| `200` with empty content | Endpoint overloaded, or a reasoning model that emitted only thinking | Treat as failure both here and at runtime |

### ✦ STEP 03a — the data-policy wall

```
⚠  ACTION REQUIRED

OpenRouter is blocking most free endpoints.

At `openrouter.ai/settings/privacy`, enable:
  · "Allow free endpoints that train on request data"
  · "Allow free endpoints that publish prompts"
and confirm Zero Data Retention → Non-frontier is off.

Tradeoff: those providers may retain, train on, and
publish prompts and completions. Fine for hobby work —
do not use it with credentials or client code.

──────── ◈ ════════ ◈ ────────

⟡ SETUP PAUSED ⟡
```

After they confirm, re-run Step 02 before continuing.

✦ ───────── ◇ ───────── ✦

## ✦ STEP 04 — QUOTA PROVISIONING

◇ Collect independent quota buckets

A chain of models from one account is one bucket wearing many hats. OpenRouter's
free-tier daily cap is **account-wide** across every `:free` model. Real resilience
comes from other providers, and walking the human through signup is your job — don't
just print a table and wait.

```
        ✦ QUOTA TOPOLOGY — an example, not a mandate ✦

        ┌─ BUCKET A ──────────────────

        │  Google AI Studio
        │  └─ Account Alpha
        │       ├─ key-01
        │       └─ key-02

        └──────────────────────────────

                    ↓

        ┌─ BUCKET B ──────────────────

        │  Groq
        │  └─ Account Beta
        │       └─ key-01

        └──────────────────────────────
```

    same account    ≠ new quota bucket
    different account = potentially new bucket

**Ask, don't assume.** Tell the user what's available and let them pick — the chain
works with as few as two buckets, more is better, and they don't need all five. Send
them something close to this, verbatim, and wait for their reply:

> To build a real fallback chain — not five models sharing one quota — I can set you up
> with any of these free accounts. No card needed for any of them. Ctrl+click a link
> below to open it without leaving the terminal, sign up, and grab a key. Hold onto each
> one — once you've got everything you want, I'll open the file directly so you can paste
> them straight in. None of this has to be typed into this chat.
>
> | Provider | Link | Click | Becomes |
> |---|---|---|---|
> | Google AI Studio | https://aistudio.google.com/apikey | "Create API key" | `GOOGLE_API_KEY` |
> | Groq | https://console.groq.com/keys | "Create API Key" | `GROQ_API_KEY` |
> | Cerebras | https://cloud.cerebras.ai/ | sign up → **API Keys** (left nav) → "Generate API Key" | `CEREBRAS_API_KEY` |
> | NVIDIA NIM | https://build.nvidia.com/ | sign in → profile → **Settings → API Keys** → "Generate Key" | `NVIDIA_API_KEY` |
> | Mistral AI | https://console.mistral.ai/api-keys | sign up → "Create new key" | `MISTRAL_API_KEY` |
> | Cohere | https://dashboard.cohere.com/api-keys | sign up → "Generate Trial Key" (non-commercial only) | `COHERE_API_KEY` |
> | A 2nd OpenRouter account | https://openrouter.ai/settings/keys | "Create Key" — use a different login than your first account | `OPENROUTER_API_KEY_2` |
>
> Which ones do you want? Two or three is a real chain — you don't need all seven.
> (Bonus, no signup at all: OVHcloud AI Endpoints, `https://oai.endpoints.kepler.ai.cloud.ovh.net/v1`
> — no key, but capped at 2 requests/min per IP, so treat it as a last-resort entry.)

**⚡ Hermes path — one more source, with no key to paste:** Hermes also has a native Nous
Portal integration on its free plan, no card needed. This one's interactive OAuth, so the
**user** has to run it themselves — you can't drive it on their behalf:

```bash
<HERMES> auth add nous
```

Once done, `provider: nous` in `config.yaml` just works.

**⚡ Hermes path — how each provider above maps into `config.yaml`:**

| Provider | Wiring |
|---|---|
| Google AI Studio | native `provider: gemini`, reads `GOOGLE_API_KEY` |
| Groq | `provider: custom`, `base_url: https://api.groq.com/openai/v1` |
| Cerebras | `provider: custom`, `base_url: https://api.cerebras.ai/v1` |
| NVIDIA NIM | native `provider: nvidia` |
| Mistral AI | `provider: custom`, `base_url: https://api.mistral.ai/v1` |
| Cohere | `provider: custom`, `base_url: https://api.cohere.ai/compatibility/v1` — this is Cohere's OpenAI-compatibility layer, not its native `v2/chat` shape |
| 2nd OpenRouter account | same `provider: openrouter` — register as a credential pool (Step 05a), not a second `fallback_providers` entry |

**Two more, advanced — skip these unless the user specifically asks:** Cloudflare
Workers AI is real (10,000 Neurons/day) but its base URL has the account ID baked in, so
it needs `--account-id` when verifying (`GUIDE.md` → *Step 2*). Hugging Face is wired
into `discover_free_models.py --provider huggingface` but, checked live, currently has
zero models flagged genuinely free — its "free tier" is a one-time $0.10/month credit,
not a bucket. Don't walk a user through either unless they bring it up.

Once everything's pasted into the file in Step 05, verify each key before it enters the
chain:

```bash
python scripts/discover_free_models.py --base-url <BASE_URL> --key-env <KEY_VAR>
```

Or, without the script, for any OpenAI-compatible provider:

```python
import json, urllib.request
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36"
body = json.dumps({"model": "<MODEL>", "messages":[{"role":"user","content":"hi"}],
                   "max_tokens": 5}).encode()
r = urllib.request.Request("<BASE_URL>/chat/completions", body,
      {"Authorization": "Bearer <KEY>", "Content-Type": "application/json", "User-Agent": UA})
print(json.load(urllib.request.urlopen(r, timeout=60))["choices"][0]["message"])
```

If a key fails, read Step 03's table before telling the user it "didn't work" — most
failures have a specific, sayable cause.

**Bucket boundary rules — apply these when ordering the chain:**

- Two `:free` models, same OpenRouter account → **same** bucket
- Two keys, same OpenRouter account → **same** bucket (cap is per account)
- Two keys, **different** OpenRouter accounts → **separate** buckets
- Two Google keys, same Cloud project → **same** bucket (free tier meters per project)
- Two Google keys, different accounts → **separate** buckets
- Two different models on one Google key → **separate** daily allowances

If the user gives you multiple keys for one provider, check they are actually distinct
accounts. On OpenRouter, `GET /api/v1/key` returns `creator_user_id`:

```python
import json, urllib.request
d = json.load(urllib.request.urlopen(urllib.request.Request(
    "https://openrouter.ai/api/v1/key",
    headers={"Authorization": "Bearer <KEY>"}), timeout=30))["data"]
print(d["creator_user_id"], d["is_free_tier"], d["usage"])
```

Different `creator_user_id` = different account = genuinely separate cap. Say so in your
report; it changes what the setup can achieve.

─────── ◈ ───────

### ✦ STEP 04a — DISCORD UPLINK

◇ Discord bot setup — only if Step 00 flagged Discord

Skip this entirely if Discord isn't in play. Otherwise this is its own kind of "key" — a
bot token, not an LLM provider — so walk it start to finish before moving on to the
provider hunt above. Send each panel below as its own message and wait for a reply
before sending the next; don't dump all three at once.

**1. Create the application and get the bot token.**

```
🤖  CREATE YOUR DISCORD BOT

Ctrl+click to open — no need to leave the terminal:
👉 https://discord.com/developers/applications

1) Click "New Application" (top right) → name it →
   accept terms.
2) Left sidebar → "Bot".
3) Click "Reset Token" (or "Copy" the first time) to
   reveal it. Keep this tab open — you'll paste it
   straight into the file as DISCORD_BOT_TOKEN in
   Step 05, no need to send it here.

──────── ◈ ════════ ◈ ────────

⟡ CONTINUE WHEN VISIBLE ⟡
```

You never handle this value directly — it goes from their clipboard straight into the
file in Step 05, same as every other key.

**2. Turn on the three privileged intents.** Most bot frameworks — Hermes and OpenClaw
included — need at least Message Content to see what anyone types.

```
⚙  ENABLE THESE THREE INTENTS

Still on the "Bot" page → scroll to "Privileged
Gateway Intents" → switch ON all three → click
"Save Changes":

    [ ] PRESENCE INTENT
    [ ] SERVER MEMBERS INTENT
    [ ] MESSAGE CONTENT INTENT

⚠  Don't skip any of them. A bot with Message Content
   off connects, looks healthy, and silently receives
   empty message bodies — a bug that's easy to blame
   on the fallback chain days later.

──────── ◈ ════════ ◈ ────────

⟡ WAITING FOR CONFIRMATION ⟡
```

Do not proceed until they confirm all three are on and saved. If they ask: past 10,000
servers, each of these three requires a Discord review — irrelevant at setup time, worth
knowing exists.

**3. Get the Client ID and hand back the install link.**

```
🔗  ONE MORE ID

Left sidebar → "OAuth2" → CLIENT ID is near the top
of the page. Keep it visible — you'll paste it into
the file as DISCORD_CLIENT_ID in Step 05.

──────── ◈ ════════ ◈ ────────

⟡ CONTINUE WHEN VISIBLE ⟡
```

Once you have the Client ID, build the install-tab link yourself and send it back —
ctrl+click to open:

```
https://discord.com/developers/applications/<CLIENT_ID>/installation
```

That's where they pick install scopes (`bot`, `applications.commands`) and bot
permissions, and generate the actual invite link that adds the bot to a server. That part
is manual on their side — there's nothing there for you to write.

**4. Decide who's allowed to talk to it — now, not after it's already online.** Ask this
here, while you're already gathering Discord-shaped decisions, not later as a
troubleshooting afterthought — a bot with no access restriction is reachable by anyone
who can see it the moment it connects in Step 06a:

```
╭──────────────────────────────────────────────────╮
│ 🔐  WHO'S ALLOWED TO TALK TO THE BOT?
╰──────────────────────────────────────────────────╯

  【 A 】  👤 Just me — DISCORD_ALLOWED_USERS=<your id>
          Safest. Bot responds only to you, in DMs or
          any channel both of you can see.

  【 B 】  🔓 Open — DISCORD_ALLOW_ALL_USERS=true
          Anyone who can see the bot can trigger it.
          Fine on a private server with friends, risky
          in a public one.

  【 C 】  🏷️ By role — DISCORD_ALLOWED_ROLES=<id>
          They create or pick a role on Discord and
          paste its ID here. Only that role can talk
          to the bot; nobody else can.

  【 D 】  📍 By channel — DISCORD_ALLOWED_CHANNELS=<id1,id2>
          Bot responds only in those specific channels
          — DMs and other channels stay silent.

  › Reply with a letter.
```

If **A**, their Discord user ID (not a secret, safe to have them paste directly in chat)
— right-click their own name with Developer Mode on, "Copy User ID". If **C** or **D**,
same mechanism for a role or channel ID. Record whichever variable applies; it's one more
line for Step 05's pass, and it's what `hermes gateway setup` in Step 06a should pick up
alongside the token — confirm it did rather than assuming.

Both `DISCORD_BOT_TOKEN` and `DISCORD_CLIENT_ID`, plus whichever access-control variable
was picked above, get pasted directly into the file in Step 05, same as every other key —
never echoed into this chat. **Pasting the token is not the end of Discord setup** — on
the ⚡ Hermes path, Step 06a actually installs the gateway dependency and turns the bot
on; skipping it leaves a bot that looks configured but never connects.

✦ ───────── ◇ ───────── ✦

## ✦ STEP 05 — CREDENTIAL WRITE

◇ Open the file and let them paste directly — never through chat

By now you know exactly which variables are needed: whatever Step 04 (and Step 04a, if
Discord's involved) settled on. Collect them all in **one** pass, straight into the file
— the human's secrets never have to be typed into this conversation at all.

**🌐 Generic / OpenClaw path:** target file is the project's `.env`.

**⚡ Hermes path:** target file is `<HERMES_HOME>/.env` instead (resolved in Step 01).
Named providers read fixed variable names (`gemini` → `GOOGLE_API_KEY` only); a second
key for the same provider goes through a credential pool (Step 05a), not a second
variable name. Custom endpoints read whatever `key_env` names in `config.yaml`.

**1. Pre-fill the blanks yourself, with a placeholder hint on each line, not a bare
`=`.** A blank line reads as "already handled" at a glance; a placeholder tells the human
exactly what belongs there without them needing to remember Step 04's table:

```
OPENROUTER_API_KEY=<paste your OpenRouter key here>
GOOGLE_API_KEY=<paste your Google AI Studio key here>
GROQ_API_KEY=<paste your Groq key here>
DISCORD_BOT_TOKEN=<paste your Discord bot token here>
```

If the file doesn't exist, create it. If it does, read it first — you're appending, not
replacing — and skip any variable that **already has a real value**: a line is
still-empty (overwrite it with the placeholder) if it's missing entirely, or its value is
blank, or its value already looks like a placeholder itself (`<...>` — a leftover from a
previous run the human never got to). Don't clobber anything that looks like an actual
key. Only list what this session actually needs — don't pre-populate providers the user
never picked. This placeholder convention matters again in step 3 below, when you verify.

On the generic path, confirm `.env` is listed in `.gitignore` first — this should already
be true from Step 01's hard stop. Not applicable on the Hermes path; `<HERMES_HOME>/.env`
lives outside any repo (unless `<HERMES_HOME>` itself resolved to something inside a
tracked repo — see Step 01).

**2. Open it for them — don't ask them to paste into chat, and don't run the editor
yourself.** A GUI editor launched from *your* tool call, not the human's own terminal, is
a common silent failure: it may open on a desktop the human can't see, block your tool
call waiting for a window that never gets closed, or simply do nothing observable — and
either way you can't tell the difference between "it opened and they're looking at it"
and "it went nowhere." Never call `notepad`/`open -e`/`nano`/etc. through your own Bash,
PowerShell, or equivalent tool. Instead, print the literal command as text and have the
human run it themselves, in their own session — in Claude Code, that means giving them
the exact line to type with the `!` prefix (only the human can trigger that prefix; you
printing `!notepad .env` yourself does not run it):

```
› Run this yourself, in your own terminal, to open the file:

    !notepad .env
```

Windows: `notepad`. macOS: `open -e .env`. Linux: whatever they've got —
`nano .env`, `gedit .env`, their default `$EDITOR`. If your environment has no way to
hand control to the user's local terminal at all (fully headless, no `!`-equivalent),
just ask them to open the file in their own editor by hand — don't substitute your own
tool call for their terminal in that case either.

```
📝  PASTE YOUR KEYS DIRECTLY INTO THE FILE

I've filled in the variable names with a
placeholder — replace each placeholder with
the real value, save, and close:

    OPENROUTER_API_KEY=<paste your OpenRouter key here>
    GOOGLE_API_KEY=<paste your Google AI Studio key here>
    DISCORD_BOT_TOKEN=<paste your Discord bot token here>

None of this needs to be typed into this chat.

──────── ◈ ════════ ◈ ────────

⟡ WAITING FOR SAVE ⟡
```

**3. Wait for them to say they've saved and closed it.** Then verify — without pulling
the raw values into your own context if you can help it. Run the discovery/verify script
as a subprocess; it reads the file itself and prints only `LIVE`/`DEAD`, never the key:

```bash
python scripts/discover_free_models.py --base-url <BASE_URL> --key-env <KEY_VAR>
```

If you need to confirm a variable actually got filled in — not whether it's *valid*, the
verify step covers that — check only whether the line is still bare or still holds the
`<...>` placeholder you wrote, never what the real value contains. If one's still
unfilled, name it and ask them to go back and fill in just that one — don't offer
chat-paste as a shortcut, and don't attempt to verify a placeholder as if it were a real
key (it will just fail and read as a bad key rather than an unfilled one).

**Fallback, if you truly can't open an editor** — a fully headless session with no way to
hand control to the user's local environment: ask them to paste the value in chat
instead, but say plainly that it will then sit in the conversation transcript, and that
they may want to rotate it afterward. This is the exception, not the default.

Confirm back to the user by naming the variable, not by re-printing the key: "Saved as
`GROQ_API_KEY`." Never echo a key into the chat once you know it's there.

Keep the names the project already reads. If it reads none, prefer the conventional ones
above — they are what every example and script here expects. Never write a key into code
or a config file that might be committed — see Invariants. 🔑

─────── ◈ ───────

### ✦ STEP 05a — CREDENTIAL POOLS (⚡ Hermes path only)

Skip this on the generic/OpenClaw path — there, key rotation lives inside the chain
implementation itself (Step 06, rule 2).

Unlike Step 05, this command needs the raw key as a CLI argument — there's no file-based
alternative, so read it from `<HERMES_HOME>/.env` yourself to build the command. That's
the one place in this runbook where you unavoidably see the value; don't restate it in
chat once you have it, same rule as everywhere else.

**This is the layer that swaps before the wall.** Pools rotate keys *within* a provider
and fire *before* any model switch, so the session never notices. Only do this when the
user has 2+ keys on **different accounts** for one provider — same-account keys share a
cap and gain nothing.

```bash
<HERMES> auth add openrouter --type api-key --label "acct-A" --api-key sk-or-v1-...
<HERMES> auth add openrouter --type api-key --label "acct-B" --api-key sk-or-v1-...
<HERMES> auth add gemini     --type api-key --label "google-B" --api-key AIza...
<HERMES> auth list        # confirm
```

`<HERMES>` is the CLI path you recorded in Step 01. These flags are non-interactive.
Supported for `openrouter`, `gemini`, `anthropic`, and `custom:` endpoints.

Then set the strategy in `config.yaml` (Step 06). Use `least_used` unless the user asks
otherwise: it balances by request count, halving per-minute pressure on each account.
Per-minute 429s are what actually interrupt an agent firing tool calls in bursts. Daily
capacity is identical across strategies; only burst behavior differs. The default is
`fill_first`, which drains key #1 first and preserves prompt-cache locality.

✦ ───────── ◇ ───────── ✦

## ✦ STEP 06 — CHAIN ASSEMBLY

◇ Implement the chain

**🌐 Generic / OpenClaw path:** if the target has its own config surface, use it. If
you're writing code, and you have the repo, port
[`examples/python/fallback_chain.py`](examples/python/fallback_chain.py) — it is
dependency-light and deliberately small. Whatever the language, it must do all of this:

1. **Try entries top-down on every request.** Starting from the top each time means the
   primary returns by itself once its cooldown expires — no restart, no bookkeeping.
2. **Rotate keys within a provider before switching models.** Least-used rotation
   balances by request count and halves per-minute pressure on each account; per-minute
   429s are what actually interrupt a burst of calls.
3. **Classify each failure** into: model gone (disable for the session), key spent
   (rotate, nap that key), transient (short nap, next entry). Honour `Retry-After`.
   Distinguish a **daily** cap — nap ~30 min — from a per-minute one — nap ~60s.
4. **Treat an empty completion as a failure**, not a result.
5. **Turn off the SDK's own retries** (`max_retries=0`) so they don't fight the chain.
6. **Log every switch once**, not once per request, and log the reason. 🔄
7. **Fail loudly when the whole chain is down**, listing what each entry is waiting on.

Pin secondary work — summarisation, titles, classification — to the smallest usable
model so it never competes with the main path for quota.

**⚡ Hermes path:** write `<HERMES_HOME>/config.yaml` instead — no application code. Fill
placeholders with **verified** models from Steps 02 and 04.

```yaml
model:
  provider: "openrouter"
  base_url: "https://openrouter.ai/api/v1"
  default: "<BEST_VERIFIED_FREE_MODEL>"

fallback_providers:
  # Cheap hops first: same provider, descending model quality.
  - provider: openrouter
    model: <SECOND_BEST>
  - provider: openrouter
    model: <THIRD_BEST>
  # ... remaining verified OpenRouter models

  # Then independent buckets. These survive the account-wide daily cap.
  - provider: custom
    model: <GROQ_MODEL>
    base_url: https://api.groq.com/openai/v1
    key_env: GROQ_API_KEY

  - provider: gemini
    model: <GEMINI_MODEL_A>
  - provider: gemini
    model: <GEMINI_MODEL_B>     # separate per-model quota on the same key

credential_pool_strategies:
  openrouter: least_used
  gemini: least_used

provider_routing:
  sort: "throughput"

openrouter:
  response_cache: true
  response_cache_ttl: 3600

auxiliary:
  compression:
    provider: openrouter
    model: <SMALL_FAST_FREE_MODEL>
    fallback_chain:
      - provider: openrouter
        model: <TINY_FREE_MODEL>
  title_generation:
    provider: openrouter
    model: <TINY_FREE_MODEL>
  web_extract:
    provider: openrouter
    model: <SMALL_FAST_FREE_MODEL>
  skills_hub:
    provider: openrouter
    model: <TINY_FREE_MODEL>
  approval:
    provider: openrouter
    model: <TINY_FREE_MODEL>
  mcp:
    provider: openrouter
    model: <SMALL_FAST_FREE_MODEL>
  vision:
    provider: openrouter
    model: <FREE_VISION_MODEL>

agent:
  api_max_retries: 1
```

**⚡ Ordering rules:**

1. Cheap hops first — same provider, different model, ranked by quality/context.
2. Then independent buckets, ranked by model quality.
3. Models the user dislikes go last. They still catch a total outage without appearing
   in normal operation. **Ask the user about model preferences** — do not assume the
   biggest model is the one they want.
4. Exclude anything that failed Step 02, and add a YAML comment saying why.

`api_max_retries: 1` makes it fail over on the first error rather than burning three
retries against an already-limited model.

✦ ───────── ◇ ───────── ✦

### ✦ STEP 06a — DISCORD GATEWAY WIRING (⚡ Hermes path, Discord only)

◇ Actually turn the bot on — collecting the token in Step 04a is not this step

Skip entirely if Discord isn't in play. **Collecting `DISCORD_BOT_TOKEN` does not make
the bot come online.** A token can be valid and the bot still never connects if the
gateway dependency isn't installed or `config.yaml` never got a `discord:` section — that
failure looks identical to "the agent isn't responding" and is easy to misdiagnose as a
model/fallback problem days later. Do this now, immediately after Step 06, while the
context of what you just configured is still fresh — don't leave it as a manual follow-up
the human has to remember.

**1. Check whether the gateway dependency is actually installed** — name-only, nothing
that reads file contents. Use the venv `<HERMES>` itself lives in, not `<HERMES_HOME>` —
on the standard installer path they're usually the same directory, but on a from-source
layout the venv sits next to the cloned code, separate from the data directory, so derive
the interpreter from `<HERMES>`'s own location rather than assuming:

```bash
# <HERMES> is the CLI path recorded in Step 01, e.g. .../venv/Scripts/hermes.exe —
# the python/pip for that same venv lives right beside it
"$(dirname "<HERMES>")/python" -m pip show discord.py 2>&1 | head -3
```

If it's missing, install it into that same venv — not your own environment, not the
system one:

```bash
"$(dirname "<HERMES>")/python" -m pip install discord.py aiodns
```

**2. Run the setup wizard — don't hand-write the `discord:` section yourself.** It reads
`DISCORD_BOT_TOKEN` out of `<HERMES_HOME>/.env` on its own and writes the matching
section into `config.yaml`; you never need to touch the token to do this:

```bash
<HERMES> gateway setup
```

Let the wizard name its own env vars for anything beyond the bot token (application ID,
etc.) — don't assume it matches whatever name Step 04a suggested; read back what it
actually wrote if you need to confirm, checking presence only, per the invariant above.

**3. Confirm it's wired, without ever printing the token.** `hermes doctor` should stop
flagging the gateway dependency and should show a `discord` section once `config.yaml`
has one:

```bash
<HERMES> doctor 2>&1 | grep -iE 'discord|gateway'
```

If Hermes exposes a status subcommand for the gateway (check `<HERMES> gateway --help`
for what's actually available in the installed version — don't assume a name), use it to
confirm the bot reaches Discord's gateway and reports ready, rather than trusting
"wizard exited 0" as proof.

**4. Remind the human about the three privileged intents from Step 04a if they haven't
confirmed yet.** The gateway can connect successfully and still silently receive empty
message bodies if Message Content Intent is off — that's a Discord-side toggle, not
something this step can set for them.

If you need to validate the token against Discord's API as part of diagnosing a
connection problem, do it the same way the invariant above requires: a subprocess that
reads the token internally and returns only a verdict (valid/invalid, plus non-secret
fields like the bot's username) — never a script whose stdout includes the token itself,
even truncated. A truncated slice is still a leak once it's sitting in a transcript.

✦ ───────── ◇ ───────── ✦

## ✦ STEP 07 — VERIFICATION

◇ Verify — do not skip; do not report success without this 🧪

**🌐 Generic / OpenClaw path:** live-test every entry in the chain you just built, using
the same keys the app will use at runtime. Re-running Step 02's script against the final
chain is enough for most projects.

✓ Every entry must answer. ✕ If one does not, remove it and re-run. Do not hand back a
chain containing a dead entry.

Then exercise the app itself once, end to end, and confirm a real request succeeds.

**⚡ Hermes path:** live-test every entry in the config you just wrote. If you have the
repo, this ships as `verify_chain.py`, which also checks the auxiliary schema. The
inline equivalent:

```python
import yaml, json, urllib.request, os

HERMES_HOME = os.environ.get("HERMES_HOME") or os.path.expanduser("~/.hermes")
cfg = yaml.safe_load(open(os.path.join(HERMES_HOME, "config.yaml")))
env = dict(l.strip().split("=", 1)
           for l in open(os.path.join(HERMES_HOME, ".env"))
           if "=" in l and not l.strip().startswith("#"))

entries = [{"provider": cfg["model"]["provider"],
            "model": cfg["model"]["default"]}] + cfg.get("fallback_providers", [])

for i, e in enumerate(entries):
    p, m = e["provider"], e["model"]
    try:
        if p == "gemini":
            body = json.dumps({"contents": [{"parts": [{"text": "hi"}]}],
                               "generationConfig": {"maxOutputTokens": 5}}).encode()
            url = ("https://generativelanguage.googleapis.com/v1beta/models/"
                   f"{m}:generateContent?key={env['GOOGLE_API_KEY']}")
            urllib.request.urlopen(urllib.request.Request(
                url, body, {"Content-Type": "application/json"}), timeout=90)
        else:
            key = env["OPENROUTER_API_KEY"] if p == "openrouter" else env[e["key_env"]]
            base = ("https://openrouter.ai/api/v1" if p == "openrouter"
                    else e["base_url"].rstrip("/"))
            body = json.dumps({"model": m,
                               "messages": [{"role": "user", "content": "hi"}],
                               "max_tokens": 5}).encode()
            urllib.request.urlopen(urllib.request.Request(
                base + "/chat/completions", body,
                {"Authorization": "Bearer " + key,
                 "Content-Type": "application/json"}), timeout=90)
        print(f"{i:>3} LIVE  {p:<12} {m}")
    except Exception as ex:
        print(f"{i:>3} DEAD  {p:<12} {m:<34} {ex}")
```

Also confirm the YAML parses and no auxiliary chain entry uses an unsupported key:

```python
allowed = {"provider", "model", "base_url", "api_key", "timeout"}
for task, v in (cfg.get("auxiliary") or {}).items():
    for e in (v.get("fallback_chain") or []):
        extra = set(e) - allowed
        assert not extra, f"{task}: unsupported keys {extra}"
```

✓ Every entry must print `LIVE`. ✕ If any prints `DEAD`, remove it from the config and
re-run. Do not hand back a config containing a dead entry.

If Discord is in play, this step verifies the model chain only — it does not confirm the
bot itself is online. That's Step 06a; don't report success here as if it covered both.

✦ ───────── ◇ ───────── ✦

## ✦ STEP 08 — SYSTEM REPORT

◇ Report to the user

```
✦  F A L L B A C K   O N L I N E  ✦

     ◈ ◇ ◈ ◇ ◈

Your AI now has somewhere to go
when the primary model says:

           "nope."  (╥﹏╥)


◇ CHAIN

    01  🧠 Primary
        ↓
    02  ⚡ Fallback
        ↓
    03  ◈ Emergency


◇ VERIFICATION

    ✓ every model live-tested
    ✓ required capabilities verified
    ✓ quota buckets mapped
    ✓ credentials protected
    ✓ runtime request succeeded
    ✓ Discord gateway connected      (only if Discord was in play — Step 06a)

──────── ◈ ════════ ◈ ────────

◎ SYSTEM READY

(ﾉ◕ヮ◕)ﾉ*:･ﾟ✧
```

Decoration doesn't replace the actual result — underneath it, state plainly:

- The final chain, in order, with each entry's provider and quota bucket.
- How many keys rotate per provider — via key rotation (generic path) or registered
  credential pools (⚡ Hermes path) — and whether they're genuinely different accounts.
- Anything excluded and the exact reason.
- **The honest limit:** the chain fires on the error, not before it. Key rotation (or
  credential pools) is the only layer that moves ahead of a wall. If the user has one key
  per provider, the setup is reactive by nature — tell them so rather than implying
  otherwise.
- If keys were pasted into the chat, remind them the keys are in the transcript and can
  be rotated at the provider's dashboard.
- Delete any temporary file containing keys once you are done with it.

═══ ◇ ═════════════ ◇ ═══

## ◇ REFERENCE — things that will waste your time

- **Prompt cache resets on every fallback.** Caches key on model + account. Each switch
  re-reads the full history at full input cost, as does the return to primary.
  Irrelevant on free models; expensive if a paid model is in the chain.
- **A 200 response can still be a failure.** Empty content from an overloaded endpoint,
  or a reasoning model that emitted only its thinking.
- **Reasoning models are the wrong default for anything interactive.** They spend
  seconds on hidden chain-of-thought before the first useful token.
- **(⚡ Hermes path) Fallback is turn-scoped.** The primary is retried at the start of
  each new turn unless its reported rate-limit reset time is still in the future.
- **(⚡ Hermes path) A named provider reads exactly one env var.** A second key for
  `gemini` needs the credential pool (Step 05a), or a `custom` entry against
  `https://generativelanguage.googleapis.com/v1beta/openai/`.
- **(⚡ Hermes path) Auxiliary tasks inherit the top-level chain** when their provider is
  `auto` and they declare no `fallback_chain`.
- **Free tiers change constantly.** Re-run Step 02 every few weeks and prune what died.

```
             ✦  unknown
             │
             ◇  detected
             │
             ◈  scanned
             │
             ◌  verifying
             │
             ◎  configured
             │
             ✓  online
```
