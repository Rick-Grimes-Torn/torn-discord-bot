from typing import List, Tuple
import discord

from .config import LEADERSHIP_ROLES


def is_discord_active_no_dnd(status: discord.Status) -> bool:
    """Active = online or idle only (exclude dnd + offline)."""
    return status in (discord.Status.online, discord.Status.idle)


async def get_active_leaders(guild: discord.Guild) -> List[Tuple[discord.Member, List[str], discord.Status]]:
    """
    Return (member, matched_roles, status) for leaders currently active (online/idle).
    Requires intents.members + intents.presences (and toggles in Discord Dev Portal).
    """
    members = guild.members
    if not members:
        members = [m async for m in guild.fetch_members(limit=None)]

    results: List[Tuple[discord.Member, List[str], discord.Status]] = []

    for m in members:
        if m.bot:
            continue

        role_names = {r.name for r in m.roles}
        matched = sorted(role_names.intersection(LEADERSHIP_ROLES))
        if not matched:
            continue

        status = getattr(m, "status", discord.Status.offline)
        if not is_discord_active_no_dnd(status):
            continue

        results.append((m, matched, status))

    results.sort(key=lambda t: (t[0].display_name or "").lower())
    return results
