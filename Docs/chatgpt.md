# Torn x Discord Bot — Project Notes (Authoritative)

## Overview

This is a Python Discord bot for **Torn.com**, built using **discord.py** with **application (slash) commands only**.

The bot is structured as a proper Python package and is run using:

```
python -m bot.main
```

It focuses on:

* Faction utilities
* Leadership visibility
* Torn API integrations
* **Live ranked-war statistics**
* **Live war-window (chain war) statistics**
* **Live faction chain timer monitoring**
* Lightweight fun / culture commands

---

## Environments & Naming (Critical)

There are **three distinct environments**. Keeping them separate is essential.

### Local (Windows) — Development Workspace

* Path: `C:\Users\zsolt\torn-discord-bot`
* Purpose: write code, create branches, commit & push
* Safe sandbox — does not affect live bots

### VPS — Dev Bot (Testing)

* Path: `~/discord-bot-dev`
* tmux session: `tornbot-dev`
* Used to test all features before production

### VPS — Prod Bot (Live)

* Path: `~/discord-bot`
* tmux session: `tornbot`
* Only runs code merged into `main`

**Golden rule:**

> Windows writes → VPS dev proves → VPS prod serves

---

## Key Design Decisions

### Package-based structure (`bot/`)

Enables clean imports, easier scaling, and safer refactoring.

### Slash commands only

No legacy prefix commands are used.

### Single Torn API key (bot-owned)

* One faction-level Torn API key
* User API keys optional, encrypted, limited to personal commands
* Ranked war, war-window, and chain features rely **only** on the bot key

### No long-term data retention

* Ranked-war stats, war-window stats, and chain state are computed **live**
* Optional short-lived in-memory caching
* **No attack or chain history is persisted**

### Defensive API handling

* Torn API responses treated as untrusted
* Strings vs ints normalized
* Missing fields handled gracefully
* Pagination is bounded

---

## Directory Structure (Current)

```
bot/
├─ main.py              # Bot startup & command sync
├─ config.py            # Environment variables & constants
├─ db.py                # SQLite + encrypted user API keys + chain opt-ins
├─ torn_api.py          # Torn API helpers & pagination
├─ chain_watcher.py     # Chain polling & alert logic
├─ presence.py          # Leadership presence helpers
├─ utils.py             # Shared utilities
├─ commands/
│  ├─ __init__.py       # register_all() (mixed signatures)
│  ├─ faction.py        # /revive /offline /online
│  ├─ api_keys.py       # /apireg /apikey_status /apikey_remove
│  ├─ balance.py        # /balance
│  ├─ leader.py         # /leader /leaderping
│  ├─ war.py            # /war … (ranked + war-window)
│  ├─ chain.py          # /chain … (watcher + opt-ins)
│  ├─ market.py         # /market … (travel / stock tools)
│  ├─ negan.py          # /negan
│  ├─ neganquote.py     # /neganquote (fun example command)
│  ├─ status_cmd.py     # /status
│  ├─ help_cmd.py       # /help
```

---

## Database Architecture (Minimal & Intentional)

SQLite is initialized **once at startup**.

* `db_init()` creates tables and returns a persistent connection
* Stored on the client as:

```python
client.db_conn
```

### Tables Used

#### `user_keys`

* Encrypted personal Torn API keys (optional)
* Used **only** by API-key commands

#### `chain_ping_optin`

* `/chain pingme` opt-ins
* `(guild_id, user_id)`
* **Cleared automatically when `/chain stop` is run**

❌ No ranked-war data
❌ No war-window data
❌ No chain hit history

---

## Command Registration

Supports **mixed register signatures**:

* Legacy: `register(tree)`
* New: `register(client, tree)`

The registrar inspects the signature and calls the correct form.

---

## Command Grouping Strategy

To keep UX clean:

* `/war …` — all war-related stats
* `/chain …` — chain watcher & pings
* `/market …` — market & travel tools

Very few top-level commands remain.

---

## Running the Bot

From the project root:

```bash
python -m bot.main
```

❌ Do **not** run `python bot/main.py`

---

## Environment Variables

Required:

```
DISCORD_TOKEN
TORN_API_KEY
BOT_MASTER_KEY
FACTION_ID
```

Optional:

```
TORN_TIMEOUT_SECONDS
```

---

## Git & Deployment Workflow

### Branching

* `main` → production
* `feature/<name>` → all development

### Feature Lifecycle

1. Create feature branch (Windows)
2. Commit & push
3. Pull branch into `~/discord-bot-dev`
4. Test on dev bot
5. Merge into `main`
6. Pull & restart prod bot

---

## Restart Loop (`run.sh`)

* Bot runs inside a restart loop
* Crash → auto restart
* Clean stop requires **two Ctrl+C**

This is expected behavior.

---

## Discord Requirements

Enabled in **code and Developer Portal**:

* Server Members Intent
* Presence Intent

---

## Common Pitfalls

❌ Running without `python -m`
❌ Smart quotes breaking strings
❌ Forgetting to restart tmux
❌ Committing SQLite WAL/SHM files
❌ Invalid discord.py types (e.g. `discord.faction`)
❌ Testing directly in prod

---

## Suggested Companion Docs (Optional)

### `ARCHITECTURE.md`

* Request flow
* Caching vs live calls
* What is never persisted

### `COMMAND_MAP.md`

* One-page command list
* Leadership-only markers

### `DEPLOY_CHECKLIST.md`

* Feature tested on dev
* No DB/secrets committed
* Merged to main
* Prod restarted

---

## Notes

This file is intended to be pasted into a **new ChatGPT session** to instantly restore full project context **without pasting large code blocks**.
