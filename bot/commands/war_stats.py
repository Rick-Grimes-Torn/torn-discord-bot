import discord
from discord import app_commands

from ..torn_api import scan_ranked_war_stats_for_user
from ..utils import is_verified_member, get_torn_id_from_member


def register(tree: app_commands.CommandTree):
    @tree.command(name="warhit", description="Current war attack count (only war hits counted)")
    async def attack(interaction: discord.Interaction):
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

            count, _ff_sum, _ff_count, war_start = await scan_ranked_war_stats_for_user(torn_id)

            await interaction.followup.send(
                f"⚔️ **Your ranked-war outgoing attacks:** **{count:,}**\n"
                f"- Ranked war start: <t:{war_start}:f>"
            )

        except Exception as e:
            await interaction.followup.send(f"⚠️ Could not calculate `/attack`: {e}")
            print("Error in /attack:", repr(e))

    @tree.command(name="warff", description="Shows your average Fair Fight (FF) in current war (only war hits counted).")
    async def ff(interaction: discord.Interaction):
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

            count, ff_sum, ff_count, war_start = await scan_ranked_war_stats_for_user(torn_id)

            if count == 0:
                await interaction.followup.send(
                    f"No ranked-war outgoing attacks found for you since <t:{war_start}:f>."
                )
                return

            if ff_count == 0:
                await interaction.followup.send(
                    f"Found **{count:,}** Ranked War attacks since <t:{war_start}:f>, "
                    "but none had a readable `fair_fight` modifier."
                )
                return

            avg_ff = ff_sum / ff_count

            await interaction.followup.send(
                f"📈 **Your average Fair Fight (FF):** **{avg_ff:.2f}**\n"
                f"- Attacks counted: **{count:,}** (FF present on **{ff_count:,}**)\n"
                f"- Ranked war start: <t:{war_start}:f>"
            )

        except Exception as e:
            await interaction.followup.send(f"⚠️ Could not calculate `/ff`: {e}")
            print("Error in /ff:", repr(e))
