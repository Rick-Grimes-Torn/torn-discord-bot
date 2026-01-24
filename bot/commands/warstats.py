import discord
from discord import app_commands

from ..utils import (
    is_verified_member,
    is_leadership_member,
    get_torn_id_from_member,
    chunk_lines,
)
from ..torn_api import get_user_warstats, get_all_warstats


def register(client, tree: app_commands.CommandTree):
    @tree.command(
        name="warstats",
        description="Your won-hit war stats (ranked vs other + FF averages).",
    )
    async def warstats(interaction: discord.Interaction):
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

            data = await get_user_warstats(int(torn_id))

            ranked_ff = data.get("ranked_ff_avg")
            total_ff = data.get("total_ff_avg")

            ranked_ff_txt = f"{ranked_ff:.2f}" if ranked_ff is not None else "n/a"
            total_ff_txt = f"{total_ff:.2f}" if total_ff is not None else "n/a"

            progress = "✅ backfill complete" if int(data.get("is_initialized") or 0) == 1 else "⏳ still backfilling older pages"

            await interaction.followup.send(
                f"📊 **Your War Stats (won hits only)**\n"
                f"- ⚔️ Ranked-war wins: **{int(data.get('ranked_wins') or 0):,}**\n"
                f"- 🥊 Other wins: **{int(data.get('other_wins') or 0):,}**\n"
                f"- 📈 Ranked FF avg: **{ranked_ff_txt}**\n"
                f"- 📉 Total FF avg: **{total_ff_txt}**\n"
                f"- War start: <t:{int(data.get('war_start') or 0)}:f>\n"
                f"- Status: {progress}"
            )

        except Exception as e:
            await interaction.followup.send(f"⚠️ Could not calculate `/warstats`: {e}")
            print("Error in /warstats:", repr(e))

    @tree.command(
        name="warstats_all",
        description="(Leadership) Won-hit war stats for all members.",
    )
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
            rows = data.get("rows") or []

            header = (
                f"📊 **War Stats — All Members (won hits only)**\n"
                f"War start: <t:{int(data.get('war_start') or 0)}:f>\n"
                f"{'✅ backfill complete' if int(data.get('is_initialized') or 0) == 1 else '⏳ still backfilling older pages'}\n\n"
            )

            if not rows:
                await interaction.followup.send(header + "No stats collected yet.")
                return

            lines = []
            for i, r in enumerate(rows, start=1):
                ranked_ff = r.get("ranked_ff_avg")
                total_ff = r.get("total_ff_avg")
                ranked_ff_txt = f"{ranked_ff:.2f}" if ranked_ff is not None else "n/a"
                total_ff_txt = f"{total_ff:.2f}" if total_ff is not None else "n/a"

                name = r.get("name") or f"[{r.get('torn_id')}]"
                lines.append(
                    f"{i:>3}. {name} — "
                    f"Ranked **{int(r.get('ranked_wins') or 0):,}**, Other **{int(r.get('other_wins') or 0):,}**, "
                    f"FF(ranked) **{ranked_ff_txt}**, FF(total) **{total_ff_txt}**"
                )

            for msg in chunk_lines(header, lines, limit=1900):
                await interaction.followup.send(msg)

        except Exception as e:
            await interaction.followup.send(f"⚠️ Could not calculate `/warstats_all`: {e}")
            print("Error i
