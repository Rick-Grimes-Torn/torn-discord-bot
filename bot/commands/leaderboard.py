# bot/commands/leaderboard.py
from __future__ import annotations

import asyncio
import time
import traceback
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple, List

import discord
from discord import app_commands

from bot.torn_api import get_cached_ranked_war_start, fetch_faction_attacks_outgoing
from bot.utils import extract_to_from_prev_url


# --- Simple in-memory cache & in-flight dedupe (resets on restart) ---

@dataclass
class CacheEntry:
    expires_at: float
    value: Any


# cache key: (faction_key, top_n)
_LEADERBOARD_CACHE: Dict[Tuple[int, int], CacheEntry] = {}
_INFLIGHT: Dict[Tuple[int, int], asyncio.Future] = {}

CACHE_TTL_SECONDS = 30
DEFAULT_TOP = 10


def _now() -> float:
    return time.time()


def _get_cached(key: Tuple[int, int]) -> Optional[Any]:
    entry = _LEADERBOARD_CACHE.get(key)
    if not entry:
        return None
    if entry.expires_at < _now():
        _LEADERBOARD_CACHE.pop(key, None)
        return None
    return entry.value


def _set_cached(key: Tuple[int, int], value: Any, ttl: int = CACHE_TTL_SECONDS) -> None:
    _LEADERBOARD_CACHE[key] = CacheEntry(expires_at=_now() + ttl, value=value)


def _to_int(v: Any, default: int = 0) -> int:
    if v is None:
        return default
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(v)
    try:
        return int(str(v).strip())
    except Exception:
        return default


def _to_float(v: Any, default: float = 0.0) -> float:
    if v is None:
        return default
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).strip())
    except Exception:
        return default


def _top_avg_ff(stats: Dict[int, Dict[str, Any]], n: int) -> List[Tuple[int, Dict[str, Any]]]:
    # Only include players with at least 1 attack that had a readable fair_fight value
    items = [(pid, s) for pid, s in stats.items() if _to_int(s.get("ff_count"), 0) > 0]
    items.sort(
        key=lambda kv: (_to_float(kv[1].get("avg_ff")), _to_int(kv[1].get("ff_count"))),
        reverse=True,
    )
    return items[:n]


def _extract_attacker(a: Dict[str, Any]) -> Tuple[Optional[int], Optional[str]]:
    attacker = a.get("attacker") or {}
    if not isinstance(attacker, dict):
        return None, None
    attacker_id = _to_int(attacker.get("id"), 0)
    if attacker_id <= 0:
        return None, None
    name = attacker.get("name")
    return attacker_id, (str(name) if name else f"ID {attacker_id}")


def _extract_fair_fight(a: Dict[str, Any]) -> Optional[float]:
    modifiers = a.get("modifiers") or {}
    if not isinstance(modifiers, dict):
        return None
    ff = modifiers.get("fair_fight")
    if ff is None:
        return None
    try:
        return float(ff)
    except (TypeError, ValueError):
        return None


def _extract_respect(a: Dict[str, Any]) -> float:
    for k in ("respect", "respect_gain", "respect_gained"):
        if k in a:
            return _to_float(a.get(k), 0.0)
    return 0.0


async def _scan_ranked_war_attacks_all(war_start: int, max_pages: int = 120) -> List[Dict[str, Any]]:
    """
    Scan outgoing faction attacks backwards until before war_start.
    Uses the same paging logic as your per-user scan (to= extracted from prev link).
    """
    war_start = _to_int(war_start, 0)
    if war_start <= 0:
        return []

    all_ranked: List[Dict[str, Any]] = []
    to_val: Optional[int] = None

    for _ in range(max_pages):
        page = await fetch_faction_attacks_outgoing(limit=100, to=to_val)
        attacks = page.get("attacks", [])
        if not isinstance(attacks, list) or not attacks:
            break

        stop = False
        for a in attacks:
            if not isinstance(a, dict):
                continue

            started = a.get("started")
            if not isinstance(started, int):
                started = _to_int(started, 0)

            if started and started < war_start:
                stop = True
                break

            if not a.get("is_ranked_war", False):
                continue

            all_ranked.append(a)

        if stop:
            break

        prev_url = (((page.get("_metadata") or {}).get("links") or {}).get("prev"))
        next_to = extract_to_from_prev_url(prev_url)
        if next_to is None:
            break
        to_val = next_to

    return all_ranked


def _build_leaderboard(attacks: List[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    stats: Dict[int, Dict[str, Any]] = {}

    for a in attacks:
        attacker_id, attacker_name = _extract_attacker(a)
        if not attacker_id:
            continue

        entry = stats.setdefault(
            attacker_id,
            {
                "name": attacker_name or f"ID {attacker_id}",
                "attacks": 0,
                "respect": 0.0,
                "ff_sum": 0.0,
                "ff_count": 0,
            },
        )

        if attacker_name:
            entry["name"] = attacker_name

        entry["attacks"] = _to_int(entry.get("attacks"), 0) + 1
        entry["respect"] = _to_float(entry.get("respect"), 0.0) + _extract_respect(a)

        ff = _extract_fair_fight(a)
        if ff is not None:
            entry["ff_sum"] = _to_float(entry.get("ff_sum"), 0.0) + float(ff)
            entry["ff_count"] = _to_int(entry.get("ff_count"), 0) + 1

    # compute avg_ff once
    for _pid, e in stats.items():
        c = _to_int(e.get("ff_count"), 0)
        s = _to_float(e.get("ff_sum"), 0.0)
        e["avg_ff"] = (s / c) if c > 0 else 0.0

    return stats


def _top_n(stats: Dict[int, Dict[str, Any]], field: str, n: int) -> List[Tuple[int, Dict[str, Any]]]:
    items = list(stats.items())
    items.sort(
        key=lambda kv: (_to_float(kv[1].get(field)), _to_float(kv[1].get("attacks"))),
        reverse=True,
    )
    return items[:n]


def _fmt_rows(items: List[Tuple[int, Dict[str, Any]]], field: str) -> str:
    lines: List[str] = []
    for i, (_, s) in enumerate(items, start=1):
        if field == "respect":
            val_str = f"{_to_float(s.get(field), 0.0):.2f}"
        elif field == "avg_ff":
            avg = _to_float(s.get("avg_ff"), 0.0)
            cnt = _to_int(s.get("ff_count"), 0)
            val_str = f"{avg:.2f}"
        else:
            val_str = f"{_to_int(s.get(field), 0):,}"
        lines.append(f"**{i}.** {s.get('name', 'Unknown')} — **{val_str}**")
    return "\n".join(lines) if lines else "_No data yet._"


async def _compute_leaderboard(top: int) -> Dict[str, Any]:
    war_start = await get_cached_ranked_war_start()
    attacks = await _scan_ranked_war_attacks_all(war_start)
    stats = _build_leaderboard(attacks)

    return {
        "war_start": int(war_start),
        "total_attacks": len(attacks),
        "stats": stats,
        "top": top,
    }


# --- Command registration ---


def register(client: discord.Client, tree: app_commands.CommandTree):
    @tree.command(name="leaderboard", description="Show current ranked war leaderboard.")
    @app_commands.describe(top="How many players to show (default 10, max 25)")
    async def leaderboard(interaction: discord.Interaction, top: Optional[int] = DEFAULT_TOP):
        await interaction.response.defer(thinking=True)

        try:
            if top is None:
                top = DEFAULT_TOP
            top = max(5, min(int(top), 25))

            # Single-faction bot: key just needs to vary by 'top'.
            cache_key = (1, top)

            cached = _get_cached(cache_key)
            if cached:
                result = cached
            else:
                fut = _INFLIGHT.get(cache_key)
                if fut and not fut.done():
                    result = await fut
                else:
                    loop = asyncio.get_running_loop()
                    fut = loop.create_future()
                    _INFLIGHT[cache_key] = fut
                    try:
                        result = await _compute_leaderboard(top)
                        _set_cached(cache_key, result)
                        fut.set_result(result)
                    except Exception as e:
                        print("Leaderboard compute failed:", repr(e))
                        print(traceback.format_exc())
                        err = {"error": f"Leaderboard scan failed: {e!s}"}
                        if not fut.done():
                            fut.set_result(err)
                        result = err
                    finally:
                        _INFLIGHT.pop(cache_key, None)

            if not isinstance(result, dict) or "error" in result:
                msg = result.get("error") if isinstance(result, dict) else "Unknown error"
                await interaction.followup.send(f"⚠️ Could not calculate `/leaderboard`: {msg}")
                return

            stats = result.get("stats") or {}
            war_start = _to_int(result.get("war_start"), 0)

            if not stats:
                await interaction.followup.send(
                    f"No ranked-war outgoing attacks found since <t:{war_start}:f>."
                )
                return

            top_attacks = _top_n(stats, "attacks", top)
            top_respect = _top_n(stats, "respect", top)
            top_avg_ff = _top_avg_ff(stats, top)

            embed = discord.Embed(
                title="🏆 Ranked War Leaderboard",
                description=(
                    "Live stats from current ranked war\n"
                    f"Total counted attacks: **{_to_int(result.get('total_attacks'), 0):,}**\n"
                    f"Ranked war start: <t:{war_start}:f>"
                ),
            )
            embed.add_field(name="⚔️ Top Attacks", value=_fmt_rows(top_attacks, "attacks"), inline=False)
            embed.add_field(name="✨ Top Respect", value=_fmt_rows(top_respect, "respect"), inline=False)
            embed.add_field(name="📈 Highest Avg FF", value=_fmt_rows(top_avg_ff, "avg_ff"), inline=False)
            await interaction.followup.send(embed=embed)

        except Exception as e:
            await interaction.followup.send(f"⚠️ Could not calculate `/leaderboard`: {e}")
            print("Error in /leaderboard:", repr(e))
            print(traceback.format_exc())
