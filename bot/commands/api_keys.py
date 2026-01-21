import discord
from discord import app_commands

from ..db import upsert_user_key, get_user_key, delete_user_key
from ..utils import is_verified_member


def register(client: discord.Client, tree: app_commands.CommandTree):
    @tree.command(name="apireg", description="Register (or replace) your personal Torn API key (stored encrypted).")
    @app_commands.describe(key="Your Torn API key (keep this private)")
    async def apireg(interaction: discord.Interaction, key: str):
        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            if not is_verified_member(interaction):
                await interaction.followup.send("You must have the **Verified** role to use this command.")
                return

            if not key or len(key.strip()) < 10:
                await interaction.followup.send("That doesn’t look like a valid API key.")
                return

            upsert_user_key(client.db_conn, interaction.user.id, key.strip())
            await interaction.followup.send("✅ Saved your key.")

        except Exception as e:
            await interaction.followup.send("⚠️ Something went wrong while saving your key.")
            print("Error in /apireg:", repr(e))

    @tree.command(name="apikey_status", description="Check if you have a Torn API key stored.")
    async def apikey_status(interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            if not is_verified_member(interaction):
                await interaction.followup.send("You must have the **Verified** role to use this command.")
                return

            key = get_user_key(client.db_conn, interaction.user.id)
            if not key:
                await interaction.followup.send("No key stored. Use `/apireg`.")
                return

            masked = "****" + key[-4:]
            await interaction.followup.send(f"Key stored: `{masked}`")

        except Exception as e:
            await interaction.followup.send("⚠️ Could not read your stored key.")
            print("Error in /apikey_status:", repr(e))

    @tree.command(name="apikey_remove", description="Delete your stored Torn API key.")
    async def apikey_remove(interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            if not is_verified_member(interaction):
                await interaction.followup.send("You must have the **Verified** role to use this command.")
                return

            removed = delete_user_key(client.db_conn, interaction.user.id)
            if removed:
                await interaction.followup.send("✅ Your stored key has been deleted.")
            else:
                await interaction.followup.send("No key was stored.")

        except Exception as e:
            await interaction.followup.send("⚠️ Could not delete your key.")
            print("Error in /apikey_remove:", repr(e))
