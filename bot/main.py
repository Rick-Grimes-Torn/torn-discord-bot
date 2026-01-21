import discord
from discord import app_commands

from .config import DISCORD_TOKEN
from .db import db_init
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
    client.db_conn = conn
    client.chain_watcher = ChainWatcher(client, conn, poll_seconds=15)

    register_all(client, tree)
    client.run(DISCORD_TOKEN)


if __name__ == "__main__":
    main()
