# Torn x Discord Bot — Project Notes

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

## Key Design Decisions

### Package-based structure (`bot/`)

Enables clean imports, easier scaling, and safer refactoring.

### Slash commands only

No legacy prefix commands are used.

### Single Torn API key (bot-owned)

* Bot uses **one faction-level Torn API key**
* User API keys (if enabled) are optional, encrypted, and used only for personal commands
* **Ranked war, war-window, and chain features rely only on the bot key**

### No long-term attack or chain storage

* Ranked-war stats, war-window stats, and chain state are **computed live** from Torn API
* Optional **short-lived in-memory caching** is used for performance
* **No attack or chain data is persisted to the database**

### Defensive API handling

* Torn API responses are treated as **untrusted**
* Strings vs ints are normalized
* Missing or malformed fields are handled gracefully
* Pagination is bounded to avoid runaway scans

---

## Directory Structure

```
bot/
├─ main.py              # Bot startup, Discord client, background services
├─ config.py            # Environment variables & constants
├─ db.py                # SQLite + encrypted user API keys + chain ping opt-ins
├─ torn_api.py          # Torn API calls, pagination, caching helpers
├─ chain_watcher.py     # Faction chain polling & alert logic
├─ presence.py          # Discord presence / leader activity helpers
├─ utils.py             # Shared helpers (parsing, paging, safety)
├─ commands/
│  ├─ __init__.py       # register_all() (supports mixed register signatures)
│  ├─ faction.py        # /revive /offline /online
│  ├─ api_keys.py       # /apireg /apikey_status /apikey_remove
│  ├─ balance.py        # /balance
│  ├─ leader.py         # /leader /leaderping (with cooldown)
│  ├─ war.py            # /war … (ranked-war + war-window stats)
│  ├─ market.py         # /market … (travel & stock tools)
│  ├─ chain.py          # /chain … (chain watcher + opt-ins)
│  ├─ status_cmd.py     # /status (bot dashboard)
│  ├─ negan.py          # /negan (fun insult command)
│  ├─ help_cmd.py       # /help
```

bot/
├─ main.py              # Bot startup, Discord client, background services
├─ config.py            # Environment variables & constants
├─ db.py                # SQLite + encrypted user API keys + chain ping opt-ins
├─ torn_api.py          # Torn API calls, pagination, caching helpers
├─ chain_watcher.py     # Faction chain polling & alert logic
├─ presence.py          # Discord presence / leader activity helpers
├─ utils.py             # Shared helpers (parsing, paging, safety)
├─ commands/
│  ├─ **init**.py       # register_all() (supports mixed register signatures)
│  ├─ faction.py        # /revive /offline /online
│  ├─ api_keys.py       # /apireg /apikey_status /apikey_remove
│  ├─ balance.py        # /balance
│  ├─ leader.py         # /leader /leaderping (with cooldown)
│  ├─ war_stats.py      # /attack /ff (ranked-war only stats)
│  ├─ war_chain_stats.py# /warhits /warffall (war-window stats)
│  ├─ leaderboard.py   # /leaderboard (faction-wide ranked war stats)
│  ├─ chain_timer.py    # /chainstart /chainstop /chainstatus /pingme /noping
│  ├─ status_cmd.py     # /status (bot dashboard)
│  ├─ negan.py          # /negan (fun insult command)
│  ├─ help_cmd.py       # /help

````

---

## Database Architecture

SQLite is initialized **once at startup**.

- `db_init()` creates tables and returns a persistent SQLite connection
- The connection is stored on the Discord client as:
  ```python
  client.db_conn
````

* All DB helpers accept the connection explicitly
* The connection remains open for the lifetime of the bot

This avoids repeated open/close cycles and supports background services.

### Tables Used

#### `user_keys`

* Stores encrypted personal Torn API keys (optional)
* Used **only** by API-key-related commands

#### `chain_ping_optin`

* Stores `/pingme` opt-ins
* Schema: `(guild_id, user_id)`
* Persists across restarts
* Used exclusively by the chain watcher

**No ranked-war, war-window, or chain attack data is persisted.**

---

## Command Registration (Important Detail)

The command registrar supports **mixed register signatures**:

* Legacy commands: `register(tree)`
* New commands: `register(client, tree)`

The registrar inspects the function signature and calls the correct form.
This avoids refactoring all existing command modules.

### Command Grouping Strategy

To reduce top-level command clutter, commands are grouped by domain using **application command groups**:

* `/war …` — all war-related statistics (ranked-war and war-window)
* `/chain …` — chain watcher controls and ping opt-ins
* `/market …` — market / travel / stock data

Only a small number of top-level commands remain, improving discoverability and UX.

---

## Running the Bot

From the project root:

```
python -m bot.main
```

❌ Do **not** run `python bot/main.py` directly — relative imports will fail.

---

## Environment Variables (.env)

### Required

```
DISCORD_TOKEN
TORN_API_KEY
BOT_MASTER_KEY   # Fernet encryption key
FACTION_ID       # numeric Torn faction ID
```

### Optional

```
TORN_TIMEOUT_SECONDS
```

---

## Discord Requirements

The following intents must be enabled **both in code and in the Discord Developer Portal**:

* Server Members Intent
* Presence Intent

Presence intent is required for:

* Leadership visibility
* Determining who is online for chain alerts

---

## War Command Group

All war-related commands are grouped under `/war`.

### Ranked War Logic (Core Concept)

Ranked-war stats are always calculated **live**.

#### Algorithm

1. Fetch ranked war start timestamp from `/faction/wars`
2. Page backwards through `/faction/attacks?filters=outgoing`
3. Stop once `attack.started < war_start`
4. Only include attacks where:

```python
is_ranked_war == True
```

No ranked-war attack data is persisted.

### `/war attacks`

* Shows **outgoing ranked-war attack count** for the current war
* Torn ID parsed from nickname: `Name [123456]`
* Live scan with per-user caching

### `/war ff`

* Shows **average Fair Fight (FF)** for ranked-war attacks
* Based on `modifiers.fair_fight`
* Attacks without FF data are ignored

### `/war leaderboard`

* Public (non-ephemeral) faction leaderboard for the **current ranked war**

### Ranked War Metrics

* ⚔️ Top Attacks
* ✨ Top Respect
* 📈 Highest Average Fair Fight

### Ranked War Notes

* Finishing hits are **not** used
* Torn does not reliably expose them
* `Avg FF = sum(fair_fight) / count(fair_fight)`
* Players with no FF data are excluded from FF leaderboards

---

### War-Window (Chain War) Statistics

These commands are designed for **wars with an active chain**, where leadership wants visibility into **all activity during the war window**, not just ranked-war hits.

#### War Window Definition

```
war window = [ranked war start → now]
```

The ranked war start timestamp is still authoritative and sourced from `/faction/wars`.

#### Key Differences vs Ranked-War Stats

| Ranked War                   | War Window                              |
| ---------------------------- | --------------------------------------- |
| Only `is_ranked_war == true` | **All outgoing attacks**                |
| Counts war hits only         | Counts **everything during war window** |
| FF avg = ranked-war hits     | **FF avg = all hits**                   |

### `/war hits`

Shows **all outgoing attacks during the war window**, split into:

* ⚔️ **In-war hits** (`is_ranked_war == true`)
* 🚪 **Outside-war hits** (everything else)

Includes:

* Total hits
* Split counts
* War start timestamp

### `/war ff_all`

Shows **average Fair Fight (FF) across ALL hits during the war window**.

Rules:

* FF is averaged across **both in-war and outside-war hits**
* Only attacks with readable `modifiers.fair_fight` are counted

#### Implementation Notes

* Uses the **same pagination, cutoff, and caching logic** as ranked-war scans
* Pages backwards using `_metadata.links.prev` → `to` parameter
* Stops immediately when attack timestamps fall before war start
* Uses bounded paging (`max_pages`) to protect against excessive API usage

----------|------------|
| Only `is_ranked_war == true` | **All outgoing attacks** |
| Counts war hits only | Counts **everything during war window** |
| FF avg = ranked-war hits | **FF avg = all hits** |

### Commands — War Window

#### `/warhits`

Shows **all outgoing attacks during the war window**, split into:

* ⚔️ **In-war hits** (`is_ranked_war == true`)
* 🚪 **Outside-war hits** (everything else)

Includes:

* Total hits
* Split counts
* War start timestamp

#### `/warffall`

Shows **average Fair Fight (FF) across ALL hits during the war window**.

Rules:

* FF is averaged across **both in-war and outside-war hits**
* Only attacks with readable `modifiers.fair_fight` are counted

### War-Window Implementation Notes

* Uses the **same pagination, cutoff, and caching logic** as ranked-war scans
* Pages backwards using `_metadata.links.prev` → `to` parameter
* Stops immediately when attack timestamps fall before war start
* Uses bounded paging (`max_pages`) to protect against excessive API usage

---

## Faction Chain Watcher (Core System)

### Purpose

Monitors the faction chain timer live and alerts members **before the chain expires**.

### Torn API Used

```
GET /v2/faction/chain
```

* The `timeout` field (seconds remaining) is authoritative
* Each hit resets the timer upward (~300s)

No chain data is persisted.

---

## Chain Watcher Behavior

* Background asyncio task per guild
* Poll interval configurable (default 15s)
* **Single alert per danger window**
* Automatic re-arming after each hit reset

### Alert Threshold

Controlled by **one value**:

```
alert_seconds
```

Examples:

* `60`  → 1-minute alert
* `75`  → 1m15s alert
* `290` → testing (4m50s)

---

## Single-Source Chain Configuration

All chain behavior is controlled from **one config block** in `chain_watcher.py`:

* Leadership control roles
* Ping role name
* Alert threshold (seconds)
* Poll interval
* Discord message templates

Changing alert behavior requires editing **one place only**.

---

## Alert Logic (Important)

```
Alert fires when:
  timeout <= alert_seconds AND alert_armed == True

After firing:
  alert_armed = False

When timeout rises above alert_seconds:
  alert_armed = True  (re-arm)
```

This prevents spam while still catching every timer reset.

---

## Chain Command Group

All chain-related commands are grouped under `/chain`.

### Leadership Controls

Only these roles can start/stop monitoring:

* Negan Saviors
* Lieutenant Saviors

#### Commands

* `/chain start` (public)
* `/chain stop`  (public)

Everyone sees when monitoring starts/stops, but only leadership can execute.

---

## Who Gets Pinged (Chain Alerts)

Only members who:

1. Have the **Savior** role
2. AND are either:

   * Online on Discord
   * OR opted-in via `/pingme` (even if offline)

**Important behavior:**

* `/pingme` opt-ins are **session-scoped to an active chain**
* All opt-ins are cleared automatically when leadership runs `/chainstop`

Bots are never pinged.

---

### Member Commands

#### `/chain pingme`

* Opt-in to chain pings while offline
* Stored persistently in SQLite
* **Automatically cleared when `/chain stop` is run**

#### `/chain noping`

* Remove opt-in

---

## Status & Visibility Commands

### `/chainstatus` (public)

Shows:

* Chain watcher state
* Channel being monitored
* Alert threshold & poll interval
* Whether watcher is armed
* Live chain ID + timeout (if active)

### `/status` (public)

Bot dashboard:

* Chain watcher summary
* Live chain state
* Ranked war start time

### Time Display

* Torn timestamps are shown in **TCT (Torn City Time)**
* TCT is equivalent to UTC
* Format: `YYYY-MM-DD HH:MM TCT`

---

## Leadership Visibility

### `/leader`

Shows leadership currently online or idle on Discord.

### `/leaderping`

* Pings currently active leadership
* Includes a **per-guild in-memory cooldown**
* Cooldown resets on bot restart

---

## Fun / Culture Commands

### `/negan`

* Public command
* Outputs a random hard-coded “Negan-style” insult
* No DB access
* No Torn API usage
* Intended for faction culture / humor

---

## Channel Permissions (Common Pitfall)

The bot must have:

* View Channel
* Send Messages

Starting the chain watcher in threads or restricted channels without permissions will:

* Cause Discord 403 errors
* Prevent alerts from being sent

---

## Caching Strategy (In-Memory)

* Ranked war start timestamp cached briefly
* Per-user ranked-war stats cached briefly
* Per-user war-window stats cached briefly
* Chain watcher state stored in memory only
* Leaderping cooldown stored in memory only

All caches reset automatically on bot restart.

---

## Common Pitfalls

❌ Running without `python -m`
❌ Missing `__init__.py` files
❌ Using absolute imports inside the package
❌ Assuming Torn API field types are consistent
❌ Trusting finishing-hit flags from Torn
❌ Starting chain watcher in inaccessible channels
❌ Presence intent not enabled in Discord portal
❌ Using `zoneinfo` on Windows (tzdata not installed)
❌ **Using invalid Discord.py type hints (e.g. `discord.faction`) — use `discord.Guild` instead**

---

## Future Ideas

* Leaderboard subcommands (`/leaderboard attacks | respect | ff`)
* Cooldowns for heavy commands
* Admin/debug commands
* Metrics & structured logging
* Auto-generated help from command tree
* Chain config via slash commands (`/chainconfig`)
* Relative time displays (e.g. “started 2h ago”)

---

## Suggested Extra Docs for a New Chat

If you want to restore *everything* quickly in a fresh ChatGPT session, consider keeping these short companion docs:

### 1. `ARCHITECTURE.md`

High-level system view:

* Request flow (Discord → command → Torn API → response)
* Where caching happens vs live calls
* What is **never** persisted

### 2. `API_BEHAVIOR.md`

Edge cases and lessons learned:

* Torn API field inconsistencies (strings vs ints)
* Missing `fair_fight`
* Ranked-war flags not being reliable for finishing hits

### 3. `COMMAND_MAP.md`

One-page list:

* `/war …`
* `/chain …`
* `/market …`
* Which are leadership-only

This is extremely useful when adding new contributors or returning after a break.

---

## Notes

This file is intended to be pasted into a new ChatGPT session to restore full project context, architecture, and design intent **without pasting large code blocks**.
