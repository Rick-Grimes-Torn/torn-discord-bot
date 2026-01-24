import discord
from discord import app_commands

from ..utils import (
    is_verified_member,
    is_leadership_member,
    get_torn_id_from_member,
    chunk_lines,
)
from ..torn_api import get_user_warstats, get_all_warstats


def _fmt_ff(v) -> str:
    return f"{v:.2f}" if v is not None else "n/a"


def register(client, tree: app_commands.CommandTree):

    @tree.command(
        name="warstats",
        description="Your won-hit war stats (ranked vs other + FF averages).",
    )
    async def warstats(interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)

        try:
            if not is_verified_member(interaction):
                await interaction.followup.send(
                    "You must have the **Verified** role to use this command."
                )
                return

            if not isinstance(interaction.user, discord.Member):
                await interaction.followup.send(
                    "This command must be used in the server."
                )
                return

            torn_id = get_torn_id_from_member(interaction.user)
            if not torn_id:
                await interaction.followup.send(
                    "I couldn't find your Torn ID in your nickname.\n"
                    "YATA should set it like: `Name [123456]`."
                )
                return

            data = await get_user_warstats(int(torn_id))

            ranked_ff_txt = _fmt_ff(data.get("ranked_ff_avg"))
            other_ff_txt = _fmt_ff(data.get("other_ff_avg"))
            total_ff_txt = _fmt_ff(data.get("total_ff_avg"))

            progress = (
                "✅ backfill complete"
                if int(data.get("is_initialized") or 0) == 1
                else "⏳ still backfilling older pages, run command again"
            )

            await interaction.followup.send(
                f"📊 **Your War Stats:**\n"
                f"- ⚔️ Total RW Hits: **{int(data.get('ranked_wins') or 0):,}**\n"
                f"- 🥊 Total Outside Hits: **{int(data.get('other_wins') or 0):,}**\n"
                f"- 📈 RW FF avg: **{ranked_ff_txt}**\n"
                f"- 📊 Outside FF avg: **{other_ff_txt}**\n"
                f"- 📉 Total FF avg: **{total_ff_txt}**\n"
                f"- War start: <t:{int(data.get('war_start') or 0)}:f>\n"
                f"- Status: {progress}"
            )

        except Exception as e:
            await interaction.followup.send(
                f"⚠️ Could not calculate `/warstats`: {e}"
            )
            print("Error in /warstats:", repr(e))

    @tree.command(
        name="warstats_all",
        description="(Leadership) War stats for all members.",
    )
    async def warstats_all(interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)

        try:
            if not is_verified_member(interaction):
                await interaction.followup.send(
                    "You must have the **Verified** role to use this command."
                )
                return

            if not is_leadership_member(interaction):
                await interaction.followup.send(
                    "This command is **leadership-only**."
                )
                return

            data = await get_all_warstats()
            rows = data.get("rows") or []

            header = (
                f"📊 **War Stats — All Members**\n"
                f"War start: <t:{int(data.get('war_start') or 0)}:f>\n"
                f"{'✅ backfill complete' if int(data.get('is_initialized') or 0) == 1 else '⏳ still backfilling, run command again'}\n"
            )

            if not rows:
                await interaction.followup.send(header + "\nNo stats collected yet.")
                return

            # --- aligned monospace table ---
            NAME_W = 22

            table_lines = []
            table_lines.append(
                f"{'#':>3}  {'Name':<{NAME_W}}  {'RW':>5}  {'OUT':>5}  {'FF-RW':>6}  {'FF-OUT':>6}  {'FF-TOT':>6}"
            )
            table_lines.append(
                f"{'-'*3}  {'-'*NAME_W}  {'-'*5}  {'-'*5}  {'-'*6}  {'-'*6}  {'-'*6}"
            )

            for i, r in enumerate(rows, start=1):
                name = (r.get("name") or f"[{r.get('torn_id')}]").strip()
                if len(name) > NAME_W:
                    name = name[:NAME_W - 1] + "…"

                rw = int(r.get("ranked_wins") or 0)
                ow = int(r.get("other_wins") or 0)

                ff_rw = _fmt_ff(r.get("ranked_ff_avg"))
                ff_out = _fmt_ff(r.get("other_ff_avg"))
                ff_tot = _fmt_ff(r.get("total_ff_avg"))

                table_lines.append(
                    f"{i:>3}  {name:<{NAME_W}}  {rw:>5}  {ow:>5}  {ff_rw:>6}  {ff_out:>6}  {ff_tot:>6}"
                )

            # chunk while preserving code blocks
            chunks = chunk_lines("", table_lines, limit=1800)
            for idx, chunk in enumerate(chunks):
                if idx == 0:
                    await interaction.followup.send(header + "\n```text\n" + chunk + "\n```")
                else:
                    await interaction.followup.send("```text\n" + chunk + "\n```")

        except Exception as e:
            await interaction.followup.send(
                f"⚠️ Could not calculate `/warstats_all`: {e}"
            )
            print("Error in /warstats_all:", repr(e))
