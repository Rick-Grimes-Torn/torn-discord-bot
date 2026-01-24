import discord
from discord import app_commands

from ..utils import is_verified_member, is_leadership_member, get_torn_id_from_member, chunk_lines
from ..torn_api import get_user_warstats, get_all_warstats


def register(client, tree: app_commands.CommandTree):
    warstats = app_commands.Group(name="warstats", description="Won-hit war statistics (ranked vs other + FF averages)")

    @warstats.command(name="me", description="Show your won-hit stats for the current war window.")
    async def warstats_me(interaction: discord.Interaction):
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

            data = await get_user_warstats(torn_id)

            ranked_ff = data["ranked_ff_avg"]
            total_ff = data["total_ff_avg"]

            ranked_ff_txt = f"{ranked_ff:.2f}" if ranked_ff is not None else "n/a"
            total_ff_txt = f"{total_ff:.2f}" if total_ff is not None else "n/a"

            progress = "✅ backfill complete" if data["is_initialized"] == 1 else "⏳ still backfilling older pages"

            await interaction.followup.send(
                f"📊 **Your War Stats (won hits only)**\n"
                f"- ⚔️ Ranked-war wins: **{data['ranked_wins']:,}**\n"
                f"- 🥊 Other wins: **{data['other_wins']:,}**\n"
                f"- 📈 Ranked FF avg: **{ranked_ff_txt}**\n"
                f"- 📉 Total FF avg: **{total_ff_txt}**\n"
                f"- War start: <t:{data['war_start']}:f>\n"
                f"- Status: {progress}"
            )

        except Exception as e:
            await interaction.followup.send(f"⚠️ Could not calculate `/warstats me`: {e}")
            print("Error in /warstats me:", repr(e))

    @warstats.command(name="all", description="(Leadership) Show won-hit stats for all members.")
    async def warstats_all(interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            if not is_verified_member(interaction):
                await interaction.followup.send("You must have the **Verified** role to use this command.")
                return
            if not is_leadership_member(interaction):
                await interaction.followup.send("This command is **leadership-only**.")
                return

            data = await get_all_warstats()
            rows = data["rows"]

            if not rows:
                await interaction.followup.send(
                    f"No stats collected yet.\nWar start: <t:{data['war_start']}:f>"
                )
                return

            header = (
                f"📊 **War Stats — All Members (won hits only)**\n"
                f"War start: <t:{data['war_start']}:f>\n"
                f"{'✅ backfill complete' if data['is_initialized']==1 else '⏳ still backfilling older pages'}\n\n"
            )

            lines = []
            for i, r in enumerate(rows, start=1):
                ranked_ff = r["ranked_ff_avg"]
                total_ff = r["total_ff_avg"]
                ranked_ff_txt = f"{ranked_ff:.2f}" if ranked_ff is not None else "n/a"
                total_ff_txt = f"{total_ff:.2f}" if total_ff is not None else "n/a"
                lines.append(
                    f"{i:>3}. {r['name']} — "
                    f"Ranked **{r['ranked_wins']:,}**, Other **{r['other_wins']:,}**, "
                    f"FF(ranked) **{ranked_ff_txt}**, FF(total) **{total_ff_txt}**"
                )

            msgs = chunk_lines(header, lines, limit=1900)
            for idx, msg in enumerate(msgs):
                await interaction.followup.send(msg)

        except Exception as e:
            await interaction.followup.send(f"⚠️ Could not calculate `/warstats all`: {e}")
            print("Error in /warstats all:", repr(e))

    tree.add_command(warstats)
