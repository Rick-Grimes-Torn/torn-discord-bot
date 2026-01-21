import discord
from discord import app_commands

from ..torn_api import fetch_faction_balance
from ..utils import is_verified_member, get_torn_id_from_member


def register(tree: app_commands.CommandTree):
    @tree.command(name="balance", description="Shows your faction vault balance.")
    async def balance(interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            if not is_verified_member(interaction):
                await interaction.followup.send("You must have the **Verified** role to use this command.")
                return

            if not isinstance(interaction.user, discord.Member):
                await interaction.followup.send("This command must be used in the server.")
                return

            torn_id = get_torn_id_from_member(interaction.user)
            if not torn_id:
                await interaction.followup.send(
                    "I couldn't find your Torn ID in your nickname.\n"
                    "YATA should set it like: `Name [123456]`."
                )
                return

            data = await fetch_faction_balance()
            balance_obj = data.get("balance") or {}
            members = balance_obj.get("members") or []

            me = next((m for m in members if int(m.get("id", -1)) == int(torn_id)), None)
            if not me:
                await interaction.followup.send("I couldn’t find your Torn ID in the faction balance list.")
                return

            username = me.get("username", "Unknown")
            money = int(me.get("money", 0))
            points = int(me.get("points", 0))

            await interaction.followup.send(
                f"Vault balance for **{username}** (`{torn_id}`):\n"
                f"- Money: **${money:,}**\n"
                f"- Points: **{points:,}**"
            )

        except Exception as e:
            await interaction.followup.send(f"⚠️ Could not fetch your vault balance: {e}")
            print("Error in /balance:", repr(e))
