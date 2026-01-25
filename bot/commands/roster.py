from __future__ import annotations

import time
from datetime import datetime, timezone, timedelta

import discord
from discord import app_commands

from bot import db, torn_api
from bot.sheets_bot_data import fetch_bot_data_rows
from bot.utils import is_leadership_member  # you already use this for warstats_all, etc.

def _utc_day_hour():
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%d"), now.hour

def _norm(s: str) -> str:
    return str(s or "").strip().lower()

def register(client: discord.Client, tree: app_commands.CommandTree):
    roster = app_commands.Group(name="roster", description="Chain roster commands")

    @roster.command(name="now", description="Show who is scheduled this hour and their Torn status (UTC).")
    async def roster_now(interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)

        if not interaction.guild:
            return await interaction.followup.send("Guild-only command.")

        day, hour = _utc_day_hour()
        rows = await fetch_bot_data_rows()
        expected = [(r.slot, r.name) for r in rows if r.day == day and r.start_hour == hour]
        expected.sort(key=lambda x: (x[0], _norm(x[1])))

        if not expected:
            return await interaction.followup.send(f"🗓️ **Roster now (UTC):** {day} {hour:02d}:00\nNo signups for this hour.")

        members = await torn_api.fetch_faction_members()
        if not isinstance(members, list):
            members = []


        status_by_name = {}
        rel_by_name = {}
        for m in members:
            name = m.get("name")
            la = (m.get("last_action") or {})
            status_by_name[_norm(name)] = la.get("status")
            rel_by_name[_norm(name)] = la.get("relative")

        lines = []
        for slot, name in expected:
            st = status_by_name.get(_norm(name))
            rel = rel_by_name.get(_norm(name))
            if st is None:
                lines.append(f"- **#{slot}** {name} — ❓ not found in faction list")
            else:
                rel_txt = f" ({rel})" if rel else ""
                lines.append(f"- **#{slot}** {name} — **{st}**{rel_txt}")

        msg = f"🗓️ **Roster now (UTC):** {day} {hour:02d}:00–{(hour+1)%24:02d}:00\n" + "\n".join(lines)
        await interaction.followup.send(msg)

    @roster.command(name="report", description="Show late/missed totals so far (leadership).")
    @app_commands.describe(days="Optional: only include last N days (default all in DB)")
    async def roster_report(interaction: discord.Interaction, days: int | None = None):
        await interaction.response.defer(thinking=True)

        if not interaction.guild:
            return await interaction.followup.send("Guild-only command.")

        if not is_leadership_member(interaction):
            return await interaction.followup.send("This command is **leadership-only**.")

        day_from = None
        if days and days > 0:
            # crude day range based on epoch days; good enough
            now = datetime.now(timezone.utc)
            start = now - timedelta(days=int(days))
            day_from = start.strftime("%Y-%m-%d")

        rows = db.roster_report(client.db_conn, interaction.guild.id, day_from=day_from)

        if not rows:
            return await interaction.followup.send("✅ No missed/late roster entries recorded yet.")

        lines = []
        for r in rows[:60]:
            late = int(r["late"])
            missed = int(r["missed"])
            late_m = int(r["late_minutes"])
            extra = []
            if missed:
                extra.append(f"missed **{missed}**")
            if late:
                extra.append(f"late **{late}** (total **{late_m}m**)")
            lines.append(f"- **{r['name']}** — " + ", ".join(extra))

        await interaction.followup.send("📋 **Roster report (late/missed):**\n" + "\n".join(lines))

    tree.add_command(roster)
