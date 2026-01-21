import random
import discord
from discord import app_commands


QUOTES = [
    "Hi. You're Rick, right? I'm Negan. And I do not appreciate you killing my men.",
    "I'm gonna kill you. That's what I'm gonna do. I'm gonna kill you, and then I'm gonna kill your friends, and I'm gonna kill everyone you've ever met!",
    "Eeny, meeny, miny, moe.",
    "You're not the shit, Rick. You're the shit-stain on the shit-stained sheets of shit.",
    "Suck my balls.",
    "I'm Negan.",
    "I Thought We Were Having A Moment, You Little Asshole!",
    "Lucille Is Thirsty... She Is A Vampire Bat!",
    "Welcome To A Brand New Beginning, You Sorry Shits!",
    "I Wear A Leather Jacket, I Have Lucille, And My Nut Sack Is Made Of Steel.",
    "I've Got My Fingers Crossed For A Little Freaky Deaky!",
    "Pissing Our Pants Yet? It’s Gonna' Be Pee-Pee Pants City Here Real Soon!",
    "Is That You, Rick? Under All That Man-Bush?",
    "I Am About 50% Percent More Into You Now... Just Sayin'!",
    "I'm A God Damn Cat!",
    "You Are Adorable! Did You Pick That Gun Because It Looks Cool? You Totally Did!",
    "I Could Never Do This With Rick. He Would Just Be Standing There, Scowling, Giving Me That Annoying Side-Eye He Gives Me.”,

]


def register(tree: app_commands.CommandTree):
    @tree.command(name="neganquote", description="Get a random Negan-ish quote.")
    async def neganquote(interaction: discord.Interaction):
        quote = random.choice(QUOTES)
        await interaction.response.send_message(f"**Negan says:** {quote}")
