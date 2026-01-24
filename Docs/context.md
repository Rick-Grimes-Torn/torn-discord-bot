\## Existing Torn API Helpers



\- get\_cached\_ranked\_war\_start()

\- scan\_ranked\_war\_stats\_for\_user(user\_id)

\- scan\_war\_window\_stats\_for\_user(user\_id)

\- fetch\_faction\_chain()

\- parse\_active\_chain()



\## Command Groups



/war

\- attacks

\- ff

\- hits

\- ff\_all

\- leaderboard



/chain

\- start

\- stop

\- status

\- pingme

\- noping



/market

\- restocks

\- travel

\- find

\- top



\## Persistent Data (SQLite)



\- user\_keys

  - discord\_user\_id

  - api\_key\_enc (encrypted)

\- chain\_ping\_optin

  - guild\_id

  - user\_id



No attack, war, or chain data is stored.



\## In-Memory Only



\- ranked war caches

\- war-window caches

\- chain watcher state

\- leaderping cooldowns



\## Constraints



\- Slash commands only

\- One bot-owned Torn API key

\- Defensive parsing everywhere

\- No long-term combat data



**Tables**

**user\_keys**



**Encrypted personal API keys**



**chain\_ping\_optin**



**/chain pingme opt-ins**



**war\_scan\_state**



**Scan checkpoints**



**Rolling aggregates**



**Keyed by (mode, torn\_id)**



**❌ No raw attack storage**

**❌ No long-term war history**



**Command Registration**



**Supports mixed signatures:**



**register(tree)**



**register(client, tree)**



**Registrar inspects function signature.**



**Running the Bot**

**python -m bot.main**





**❌ Do NOT run python bot/main.py**



**Environment Variables**



**Required:**



**DISCORD\_TOKEN**

**TORN\_API\_KEY**

**BOT\_MASTER\_KEY**

**FACTION\_ID**





**Optional:**



**TORN\_TIMEOUT\_SECONDS**



**Git Workflow**



**Develop on Windows**



**Commit \& push feature branch**



**Pull into VPS dev**



**Test**



**Merge to main**



**Pull \& restart prod**



**Restart Loop**



**Bot auto-restarts on crash**



**Stop requires two Ctrl+C**



**Common Pitfalls**



**❌ Registering removed command modules**

**❌ Breaking imports during refactor**

**❌ Testing directly in prod**

**❌ Committing SQLite WAL/SHM files**



**ChatGPT Context Restore Block**



**Paste into a new chat if UI becomes laggy:**



**Context reset:**

**We are working on a Torn Discord bot on my PC (Windows).**

**Branch: feature/chain-easy-target.**

**Goal: refactor war commands into /warstats and /warstats\_all.**

**Old /war commands should be removed.**

**Scanner function: scan\_faction\_attacks\_progress().**

**We edit locally then push to Git; VPS only pulls.**

**Continue step-by-step on my PC only.**





**---**



**# 📄 `context.md`**



**```md**

**## Torn API Helpers**



**### Current (Authoritative)**

**- scan\_faction\_attacks\_progress(torn\_id)**

**- get\_cached\_ranked\_war\_start()**



**### Chain**

**- fetch\_faction\_chain()**

**- parse\_active\_chain()**



**### Legacy (Deprecated)**

**- scan\_ranked\_war\_stats\_for\_user()**

**- scan\_war\_window\_stats\_for\_user()**



**Legacy helpers may still exist temporarily for compatibility but should not be used.**



**---**



**## Command Groups**



**### War (canonical)**

**- /warstats**

**- /warstats\_all**



**### War (deprecated)**

**- /war attacks**

**- /war hits**

**- /war ff**

**- /war ff\_all**

**- /war leaderboard**



**### Chain**

**- /chain start**

**- /chain stop**

**- /chain status**

**- /chain pingme**

**- /chain noping**



**### Market**

**- /market restocks**

**- /market travel**

**- /market find**

**- /market top**



**---**



**## Persistent SQLite Data**



**- user\_keys**

**- chain\_ping\_optin**

**- war\_scan\_state**



**No raw attack history stored.**



**---**



**## In-Memory Only**



**- short-lived caches**

**- chain watcher state**

**- cooldowns**



**---**



**## Constraints**



**- Slash commands only**

**- Single bot-owned API key**

**- Defensive parsing everywhere**

**- Avoid long pagination scans**



