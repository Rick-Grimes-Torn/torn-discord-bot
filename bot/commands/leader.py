from typing import List
import time

import discord
from discord import app_commands

from ..presence import get_active_leaders
from ..utils import chunk_lines


LEADERPING_COOLDOWN_SECONDS = 120  # change to taste
_last_leaderping_by_guild: dict[int, int] = {}


def _check_leaderping_cooldown(guild_id: int) -> int:
    """
    Returns remaining cooldown seconds (0 if not on cooldown) and updates timestamp if allowed.
    """
    now = int(time.time())
    last = int(_last_leaderping_by_guild.get(int(guild_id), 0))
    remaining = (last + int(LEADERPING_COOLDOWN_SECONDS)) - now
    if remaining > 0:
        return int(remaining)
    _last_leaderping_by_guild[int(guild_id)] = now
    return 0


def register(client: discord.Client, tree: app_commands.CommandTree):
    @tree.command(name="leader", description="Show leadership currently active on Discord (online/idle only).")
    async def leader(interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        try:
            if not interaction.guild:
                await interaction.followup.send("This command can only be used in the server.")
                return

            leaders = await get_active_leaders(interaction.guild)
            if not leaders:
                await interaction.followup.send("No leadership are currently **active** on Discord (online/idle).")
                return

            lines = [
                f"- {m.mention} — {', '.join(matched)} (`{str(status)}`)"
                for (m, matched, status) in leaders
            ]

            for msg in chunk_lines("**Active leadership (online/idle):**\n", lines):
                await interaction.followup.send(msg)

        except Exception as e:
            await interaction.followup.send("⚠️ Error while running `/leader`.")
            print("Error in /leader:", repr(e))

    @tree.command(name="leaderping", description="Ping leadership currently active on Discord (online/idle only).")
    async def leaderping(interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        try:
            if not interaction.guild:
                await interaction.followup.send("This command can only be used in the server.")
                return

            # Cooldown (per guild)
            remaining = _check_leaderping_cooldown(interaction.guild.id)
            if remaining > 0:
                await interaction.followup.send(
                    f"⏳ /leaderping is on cooldown. Try again in **{remaining}s**."
                )
                return

            leaders = await get_active_leaders(interaction.guild)
            if not leaders:
                await interaction.followup.send("No leadership are currently **active** on Discord (online/idle).")
                return

            mentions = [m.mention for (m, _matched, _status) in leaders]

            header = "🔔 **Leadership ping (active now):**\n"
            ping_msgs: List[str] = []
            current = header

            for mention in mentions:
                add = mention + " "
                if len(current) + len(add) > 1900:
                    ping_msgs.append(current.rstrip())
                    current = ""
                current += add

            if current.strip():
                ping_msgs.append(current.rstrip())

            for msg in ping_msgs:
                await interaction.followup.send(msg)

            lines = [
                f"- {m.mention} — {', '.join(matched)} (`{str(status)}`)"
                for (m, matched, status) in leaders
            ]
            for msg in chunk_lines("**Active leadership list:**\n", lines):
                await interaction.followup.send(msg)

        except Exception as e:
            await interaction.followup.send("⚠️ Error while running `/leaderping`.")
            print("Error in /leaderping:", repr(e))
