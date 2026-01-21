from datetime import datetime, timezone
import discord
from discord import app_commands

from .. import torn_api


def fmt_ts(ts: int | None) -> str:
    if not ts:
        return "Unknown"
    try:
        dt = datetime.fromtimestamp(int(ts), tz=timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M TCT")
    except Exception:
        return str(ts)


def register(client: discord.Client, tree: app_commands.CommandTree):

    @tree.command(name="status", description="Shows a quick bot status dashboard (chain + war basics).")
    async def status(interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("Guild-only command.", ephemeral=True)

        await interaction.response.defer(thinking=True)

        snap = client.chain_watcher.get_status_snapshot(interaction.guild.id)

        chain_desc = "No data"
        try:
            payload = await torn_api.fetch_faction_chain()
            chain = torn_api.parse_active_chain(payload)
            if not chain:
                chain_desc = "No active chain"
            else:
                chain_desc = f"Active (id `{chain.get('id')}`, timeout **{chain.get('timeout')}s**)"
        except Exception as e:
            chain_desc = f"⚠️ chain read error ({type(e).__name__})"

        war_desc = "No data"
        try:
            war_start = await torn_api.get_cached_ranked_war_start()
            war_desc = f"Ranked war start: **{fmt_ts(war_start)}**"
        except Exception:
            war_desc = "Ranked war start: (not found / no active ranked war?)"

        msg = (
            "⛓️ **Chain**\n"
            f"- Watcher running: **{snap['running']}**\n"
            f"- Threshold: **{snap['alert_seconds']}s**\n"
            f"- Ping role: **{snap['ping_role_name']}**\n"
            f"- Live chain: **{chain_desc}**\n"
            "\n"
            "⚔️ **Ranked War**\n"
            f"- {war_desc}\n"
        )

        await interaction.followup.send(msg)
