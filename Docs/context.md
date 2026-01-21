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

&nbsp; - discord\_user\_id

&nbsp; - api\_key\_enc (encrypted)

\- chain\_ping\_optin

&nbsp; - guild\_id

&nbsp; - user\_id



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



