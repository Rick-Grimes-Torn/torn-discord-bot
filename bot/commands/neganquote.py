import random
import discord
from discord import app_commands


QUOTES = [
    "I hope you brought your bravest face… because this is gonna sting a little.",
    "Congratulations. You just won today’s award for ‘bold choices.’",
    "I’m not saying that was a bad idea… but it’s definitely in the running.",
    "If confidence was damage, you’d be a boss fight.",
    "Today’s vibe: chaotic good… with a side of trouble.",
    "You’re doing great. Terrifyingly great.",
    "I’ve seen cleaner work from a squirrel with a clipboard.",
    "That plan has *spirit*. Not accuracy — but spirit.",
    "You’re about to learn the ancient art of: ‘maybe don’t do that.’",
    "Okay, okay… I respect the commitment to nonsense.",
]


def register(tree: app_commands.CommandTree):
    @tree.command(name="neganquote", description="Get a random Negan-ish quote.")
    async def neganquote(interaction: discord.Interaction):
        quote = random.choice(QUOTES)
        await interaction.response.send_message(f"🧟‍♂️ **Negan says:** {quote}")
