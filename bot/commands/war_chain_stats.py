import discord
from discord import app_commands

from ..torn_api import scan_war_window_stats_for_user
from ..utils import is_verified_member, get_torn_id_from_member


def register(tree: app_commands.CommandTree):
    @tree.command(name="allhits", description="All your outgoing attacks during a termed war where we are chaining.")
    async def warhits(interaction: discord.Interaction):
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

            total, in_war, out_war, _ff_sum, _ff_count, war_start = await scan_war_window_stats_for_user(torn_id)

            await interaction.followup.send(
                f"⚔️ **Your outgoing attacks during this war window:** **{total:,}**\n"
                f"- 🗡️ In war: **{in_war:,}**\n"
                f"- 🚪 Outside war: **{out_war:,}**\n"
                f"- War start: <t:{war_start}:f>"
            )

        except Exception as e:
            await interaction.followup.send(f"⚠️ Could not calculate `/warhits`: {e}")
            print("Error in /warhits:", repr(e))

    @tree.command(name="allff", description="Your average Fair Fight (FF) across ALL hits during the active war window.")
    async def warffall(interaction: discord.Interaction):
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

            total, in_war, out_war, ff_sum, ff_count, war_start = await scan_war_window_stats_for_user(torn_id)

            if total == 0:
                await interaction.followup.send(
                    f"No outgoing attacks found for you since <t:{war_start}:f>."
                )
                return

            if ff_count == 0:
                await interaction.followup.send(
                    f"Found **{total:,}** outgoing attacks since <t:{war_start}:f> "
                    f"(in war **{in_war:,}**, outside war **{out_war:,}**), "
                    "but none had a readable `fair_fight` modifier."
                )
                return

            avg_ff = ff_sum / ff_count

            await interaction.followup.send(
                f"📈 **Your average Fair Fight (FF) across ALL war-window hits:** **{avg_ff:.2f}**\n"
                f"- Attacks counted: **{total:,}** (FF present on **{ff_count:,}**)\n"
                f"- Split: in war **{in_war:,}**, outside war **{out_war:,}**\n"
                f"- War start: <t:{war_start}:f>"
            )

        except Exception as e:
            await interaction.followup.send(f"⚠️ Could not calculate `/warffall`: {e}")
            print("Error in /warffall:", repr(e))
