from typing import Optional, List
import time

import discord
from discord import app_commands

from ..torn_api import fetch_faction_members
from ..utils import chunk_lines, revive_enabled


def register(tree: app_commands.CommandTree):
    @tree.command(name="revive", description="List faction members with revives active")
    async def revive(interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        try:
            members = await fetch_faction_members()

            enabled: List[str] = []
            for member in members:
                user_id = member.get("id")
                name = member.get("name", "Unknown")
                setting = str(member.get("revive_setting", ""))
                if revive_enabled(setting):
                    enabled.append(f"- **{name}** ({user_id}) — `{setting}`")

            if not enabled:
                await interaction.followup.send("No faction members have revives active.")
                return

            enabled.sort(key=lambda s: s.lower())
            for msg in chunk_lines("**Revives active:**\n", enabled):
                await interaction.followup.send(msg)

        except Exception as e:
            await interaction.followup.send("⚠️ Error while running `/revive`.")
            print("Error in /revive:", repr(e))

    @tree.command(name="offline", description="List faction members who are offline longer than a specified")
    @app_commands.describe(minutes="Only show members offline longer than this many minutes",
                           hours="Only show members offline longer than this many hours")
    async def offline(interaction: discord.Interaction, minutes: Optional[int] = None, hours: Optional[int] = None):
        await interaction.response.defer(thinking=True)
        try:
            if minutes is not None and hours is not None:
                await interaction.followup.send("Please provide **either** minutes **or** hours, not both.")
                return

            if minutes is not None:
                if minutes < 0:
                    await interaction.followup.send("Minutes must be 0 or more.")
                    return
                threshold_seconds = minutes * 60
                label = f"{minutes} minute(s)"
            elif hours is not None:
                if hours < 0:
                    await interaction.followup.send("Hours must be 0 or more.")
                    return
                threshold_seconds = hours * 3600
                label = f"{hours} hour(s)"
            else:
                threshold_seconds = 0
                label = "0 minutes"

            members = await fetch_faction_members()
            now = int(time.time())
            lines: List[str] = []

            for member in members:
                last_action = member.get("last_action") or {}
                status = str(last_action.get("status", "")).strip().lower()
                if status != "offline":
                    continue

                last_ts = last_action.get("timestamp")
                if isinstance(last_ts, int) and (now - last_ts) < threshold_seconds:
                    continue

                name = member.get("name", "Unknown")
                user_id = member.get("id")
                relative = str(last_action.get("relative", "unknown"))
                profile_url = f"https://www.torn.com/profiles.php?XID={user_id}"
                lines.append(f"- **[{name}]({profile_url})** — `{relative}`")

            if not lines:
                await interaction.followup.send(f"No one is **Offline** longer than `{label}`.")
                return

            lines.sort(key=lambda s: s.lower())
            for msg in chunk_lines(f"**Offline longer than {label}:**\n", lines):
                await interaction.followup.send(msg)

        except Exception as e:
            await interaction.followup.send("⚠️ Error while running `/offline`.")
            print("Error in /offline:", repr(e))

    @tree.command(name="online", description="List faction members who are currently online in Torn")
    async def online(interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        try:
            members = await fetch_faction_members()

            online_names: List[str] = []
            for member in members:
                last_action = member.get("last_action") or {}
                status = str(last_action.get("status", "")).strip().lower()
                if status == "online":
                    online_names.append(member.get("name", "Unknown"))

            if not online_names:
                await interaction.followup.send("No one is currently **Online** in Torn.")
                return

            online_names.sort(key=lambda s: s.lower())
            lines = [f"- {n}" for n in online_names]
            for msg in chunk_lines("**Online now in Torn:**\n", lines):
                await interaction.followup.send(msg)

        except Exception as e:
            await interaction.followup.send("⚠️ Error while running `/online`.")
            print("Error in /online:", repr(e))
