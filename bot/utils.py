import re
from typing import Optional, List
from urllib.parse import urlparse, parse_qs

import discord
from .config import VERIFIED_ROLE_NAME, LEADERSHIP_ROLE_NAMES

_TORN_ID_RE = re.compile(r"\[(\d{1,10})\]\s*$")


def chunk_lines(header: str, lines: List[str], limit: int = 1900) -> List[str]:
    messages: List[str] = []
    current = header
    for line in lines:
        if len(current) + len(line) + 1 > limit:
            messages.append(current.rstrip())
            current = ""
        current += line + "\n"
    if current.strip():
        messages.append(current.rstrip())
    return messages


def is_verified_member(interaction: discord.Interaction) -> bool:
    member = interaction.user
    if not isinstance(member, discord.Member):
        return False
    return any(role.name == VERIFIED_ROLE_NAME for role in member.roles)


def is_leadership_member(interaction: discord.Interaction) -> bool:
    member = interaction.user
    if not isinstance(member, discord.Member):
        return False
    role_names = {r.name for r in member.roles}
    return any(rn in role_names for rn in (LEADERSHIP_ROLE_NAMES or []))


def revive_enabled(setting: str) -> bool:
    if not setting:
        return False
    return setting.strip().lower() != "no one"


def get_torn_id_from_member(member: discord.Member) -> Optional[int]:
    text = member.display_name or ""
    m = _TORN_ID_RE.search(text)
    if not m:
        return None
    try:
        tid = int(m.group(1))
        return tid if tid > 0 else None
    except ValueError:
        return None


def extract_to_from_prev_url(prev_url: Optional[str]) -> Optional[int]:
    if not prev_url:
        return None
    try:
        q = parse_qs(urlparse(prev_url).query)
        val = q.get("to", [None])[0]
        if val is None:
            return None
        return int(val)
    except Exception:
        return None
