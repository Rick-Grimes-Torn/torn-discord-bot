import random
import discord
from discord import app_commands


NEGANS_INSULTS = [
    "Negan, you walking scrotum tattoo",
    "Negan the human participation trophy",
    "Negan, budget version of a failure",
    "Negan, you sentient yeast infection",
    "Negan the discount disappointment",
    "Negan, you look like a Reddit thread came to life",
    "Negan, living proof condoms can fail",
    "Negan the human 404 error",
    "Negan, you’re what happens when natural selection takes a sick day",
    "Negan, you greasy thumbprint on God’s screen",
    "Negan the walking L",
    "Negan, you’re basically expired milk with feelings",
    "Negan, you catastrophic typo of a person",
    "Negan the human “are you still there?” message",
    "Negan, you smell like regret and Axe body spray",
    "Negan, you’re the human equivalent of Comic Sans",
    "Negan the budget Jared Leto Joker",
    "Negan, you disappointing PowerPoint presentation",
    "Negan, you’re what happens when two NPCs have a baby",
    "Negan the human read receipt",
    "Negan, you look like you peak at 3:17 pm on a Tuesday",
    "Negan, you wet sock of a man",
    "Negan the human “seen at 9:42”",
    "Negan, you’re basically a Twitter ratio personified",
    "Negan, you unseasoned chicken breast of a human",
    "Negan the discount side character",
    "Negan, you’re what happens when the loading bar gives up",
    "Negan, you human CAPTCHA fail",
    "Negan the sentient participation ribbon",
    "Negan, you look like you were conceived during a power cut",
    "Negan, you lukewarm fart of a personality",
    "Negan the human “your call is important to us”",
    "Negan, you’re basically a walking spoiler warning",
    "Negan, you disappointing DLC",
    "Negan the human “terms and conditions apply”",
    "Negan, you smell like broken dreams and Lynx Africa",
    "Negan, you’re the before picture in every transformation",
    "Negan the human blue screen of death",
    "Negan, you budget grim reaper",
    "Negan, you’re what happens when natural selection hits snooze",
    "Negan the human “read 14:37” energy",
    "Negan, you look like main character syndrome on easy mode",
    "Negan, you’re basically expired motivation",
    "Negan the human “your subscription has ended”",
    "Negan, you walking mid-life crisis at 24",
    "Negan, you human “low battery” warning",
    "Negan the discount background character",
    "Negan, you’re what happens when charisma takes a permanent vacation",
    "Negan, you sentient loading wheel",
    "Negan… my brother in Christ, you are the final boss of disappointment",
]


def register(client: discord.Client, tree: app_commands.CommandTree):

    @tree.command(name="negan", description="I wonder what this do?")
    async def negan(interaction: discord.Interaction):
        line = random.choice(NEGANS_INSULTS)
        await interaction.response.send_message(f"{line}")
