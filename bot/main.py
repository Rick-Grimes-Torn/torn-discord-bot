import discord
from discord import app_commands

from .config import DISCORD_TOKEN
from bot.db import db_init
from .commands import register_all
from .chain_watcher import ChainWatcher



intents = discord.Intents.default()
intents.members = True
intents.presences = True

client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)


@client.event
async def on_ready():
    try:
        await tree.sync()
        print(f"Logged in as {client.user}")
        print("Slash commands synced.")
    except Exception as e:
        print("Error in on_ready / command sync:", repr(e))


def main():
    conn = db_init()
    if conn is None:
        raise RuntimeError("db_init() returned None. Check DB path/config and permissions on the dev VPS.")

    client.db_conn = conn
    ensure_roster_tables(conn)


    from . import torn_api
    from bot.roster_monitor import RosterMonitor
    torn_api.set_db_conn(client.db_conn)

    client.chain_watcher = ChainWatcher(client, conn, poll_seconds=15)


    client.roster_monitor = RosterMonitor(client, client.db_conn)


    register_all(client, tree)
    client.run(DISCORD_TOKEN)


if __name__ == "__main__":
    main()
