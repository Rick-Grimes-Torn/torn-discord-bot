import time
import asyncio
from typing import Optional, List, Tuple, Dict, Any

import aiohttp

from .config import (
    TORN_API_KEY,
    TORN_BASE,
    WAR_START_CACHE_TTL_SECONDS,
    USER_STATS_CACHE_TTL_SECONDS,
    TORN_TIMEOUT_SECONDS,
)
from .utils import extract_to_from_prev_url


_war_start_cache: Dict[str, Any] = {"ts": None, "fetched_at": 0}
_user_stats_cache: Dict[int, Dict[str, Any]] = {}
_inflight_user_scans: Dict[int, asyncio.Task] = {}
_war_window_stats_cache: Dict[int, Dict[str, Any]] = {}
_inflight_war_window_scans: Dict[int, asyncio.Task] = {}


def _raise_torn_error(data) -> None:
    if not isinstance(data, dict) or "error" not in data:
        return
    err = data.get("error")
    if isinstance(err, dict):
        code = err.get("code")
        message = err.get("error") or err.get("message") or str(err)
        raise RuntimeError(f"Torn error{f' {code}' if code else ''}: {message}")
    raise RuntimeError(f"Torn error: {err}")


async def torn_get(path: str, params: Optional[dict] = None, timeout: Optional[float] = None) -> dict:
    headers = {"Authorization": f"ApiKey {TORN_API_KEY}", "User-Agent": "discord-torn-bot"}

    if timeout is None:
        timeout = TORN_TIMEOUT_SECONDS

    try:
        timeout_seconds = float(timeout)
    except (TypeError, ValueError):
        timeout_seconds = 25.0

    timeout_obj = aiohttp.ClientTimeout(total=timeout_seconds)

    # NOTE: This creates a new session each call.
    # It works, but for polling you may later want a shared session in main.py.
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{TORN_BASE}{path}",
            headers=headers,
            params=params,
            timeout=timeout_obj,
        ) as resp:
            data = await resp.json(content_type=None)

    _raise_torn_error(data)
    if not isinstance(data, dict):
        raise RuntimeError("Unexpected Torn API response (not a JSON object).")
    return data

# -----------------------------
# USER STATUS (NEW)
# -----------------------------

async def fetch_user_status(user_id: int) -> Dict[str, Any]:
    """
    Fetch the user's status using v2.
    """
    params = {"id": str(int(user_id)), "selections": "basic"}
    data = await torn_get("/user", params=params)

    # v2 may return status at top-level, or under "basic" depending on endpoint behavior
    status = data.get("status")
    if isinstance(status, dict):
        return status

    basic = data.get("basic")
    if isinstance(basic, dict):
        s2 = basic.get("status")
        if isinstance(s2, dict):
            return s2

    return {}


async def fetch_faction_balance() -> dict:
    return await torn_get("/faction/balance")


async def fetch_faction_wars() -> dict:
    return await torn_get("/faction/wars")


async def fetch_faction_attacks_outgoing(limit: int = 100, to: Optional[int] = None) -> dict:
    params = {"filters": "outgoing", "sort": "DESC", "limit": str(limit)}
    if to is not None:
        params["to"] = str(int(to))
    return await torn_get("/faction/attacks", params=params)


def get_latest_ranked_war_start(wars_payload: dict) -> Optional[int]:
    wars = wars_payload.get("wars") or {}
    ranked = wars.get("ranked") or {}
    start = ranked.get("start")
    if isinstance(start, int) and start > 0:
        return start
    try:
        s = int(start)
        return s if s > 0 else None
    except Exception:
        return None


async def get_cached_ranked_war_start() -> int:
    """
    Cache ranked war start timestamp for WAR_START_CACHE_TTL_SECONDS.
    Clears per-user stats cache if a new war start is detected.
    """
    now = int(time.time())

    cached_ts = _war_start_cache.get("ts")
    fetched_at = int(_war_start_cache.get("fetched_at") or 0)

    if cached_ts and (now - fetched_at) <= WAR_START_CACHE_TTL_SECONDS:
        return int(cached_ts)

    wars = await fetch_faction_wars()
    war_start = get_latest_ranked_war_start(wars)
    if not war_start:
        raise RuntimeError("Could not find latest ranked war start timestamp from /faction/wars.")

    if cached_ts is not None and int(cached_ts) != int(war_start):
        _user_stats_cache.clear()
        _war_window_stats_cache.clear()

    _war_start_cache["ts"] = int(war_start)
    _war_start_cache["fetched_at"] = now
    return int(war_start)


async def _compute_ranked_war_stats_for_user(torn_user_id: int) -> Tuple[int, float, int, int]:
    war_start = await get_cached_ranked_war_start()

    total_attacks = 0
    ff_sum = 0.0
    ff_count = 0

    to_val: Optional[int] = None
    max_pages = 60

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
                continue

            if started < war_start:
                stop = True
                break

            if not a.get("is_ranked_war", False):
                continue

            attacker = a.get("attacker") or {}
            attacker_id = attacker.get("id")
            try:
                attacker_id = int(attacker_id)
            except Exception:
                continue

            if attacker_id != int(torn_user_id):
                continue

            total_attacks += 1

            modifiers = a.get("modifiers") or {}
            ff = modifiers.get("fair_fight")
            try:
                if ff is not None:
                    ff_sum += float(ff)
                    ff_count += 1
            except (TypeError, ValueError):
                pass

        if stop:
            break

        prev_url = (((page.get("_metadata") or {}).get("links") or {}).get("prev"))
        next_to = extract_to_from_prev_url(prev_url)
        if next_to is None:
            break
        to_val = next_to

    return total_attacks, ff_sum, ff_count, war_start


async def scan_ranked_war_stats_for_user(torn_user_id: int) -> Tuple[int, float, int, int]:
    """
    Cached wrapper:
    - per-user TTL cache
    - dedupe concurrent scans per user
    """
    now = int(time.time())
    war_start = await get_cached_ranked_war_start()

    cached = _user_stats_cache.get(int(torn_user_id))
    if cached:
        if int(cached.get("war_start")) == int(war_start) and (now - int(cached.get("computed_at", 0))) <= USER_STATS_CACHE_TTL_SECONDS:
            return int(cached["attacks"]), float(cached["ff_sum"]), int(cached["ff_count"]), int(war_start)

    inflight = _inflight_user_scans.get(int(torn_user_id))
    if inflight and not inflight.done():
        return await inflight

    async def _runner():
        try:
            result = await _compute_ranked_war_stats_for_user(int(torn_user_id))
            a_count, ff_sum, ff_count, ws = result
            _user_stats_cache[int(torn_user_id)] = {
                "war_start": int(ws),
                "computed_at": int(time.time()),
                "attacks": int(a_count),
                "ff_sum": float(ff_sum),
                "ff_count": int(ff_count),
            }
            return result
        finally:
            _inflight_user_scans.pop(int(torn_user_id), None)

    task = asyncio.create_task(_runner())
    _inflight_user_scans[int(torn_user_id)] = task
    return await task

async def _compute_war_window_stats_for_user(torn_user_id: int) -> Tuple[int, int, int, float, int, int]:
    """
    War window = [war_start, now], where war_start is from /faction/wars ranked.start

    Returns:
      total_attacks, in_war_attacks, out_of_war_attacks, ff_sum_all, ff_count_all, war_start

    Notes:
    - Counts ALL outgoing attacks by the user in the window
    - "in_war" is based on is_ranked_war == True (same as your ranked-war logic)
    - FF is averaged across ALL counted attacks where modifiers.fair_fight is readable
    """
    war_start = await get_cached_ranked_war_start()

    total_attacks = 0
    in_war_attacks = 0
    out_of_war_attacks = 0

    ff_sum = 0.0
    ff_count = 0

    to_val: Optional[int] = None
    max_pages = 60  # keep consistent with existing scan

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
                continue

            if started < war_start:
                stop = True
                break

            attacker = a.get("attacker") or {}
            attacker_id = attacker.get("id")
            try:
                attacker_id = int(attacker_id)
            except Exception:
                continue

            if attacker_id != int(torn_user_id):
                continue

            # Count ALL attacks in the war window
            total_attacks += 1

            # Split in-war vs outside-war (using the same flag your ranked logic trusts)
            if a.get("is_ranked_war", False) is True:
                in_war_attacks += 1
            else:
                out_of_war_attacks += 1

            # FF across ALL attacks with readable fair_fight
            modifiers = a.get("modifiers") or {}
            ff = modifiers.get("fair_fight")
            try:
                if ff is not None:
                    ff_sum += float(ff)
                    ff_count += 1
            except (TypeError, ValueError):
                pass

        if stop:
            break

        prev_url = (((page.get("_metadata") or {}).get("links") or {}).get("prev"))
        next_to = extract_to_from_prev_url(prev_url)
        if next_to is None:
            break
        to_val = next_to

    return total_attacks, in_war_attacks, out_of_war_attacks, ff_sum, ff_count, war_start


async def scan_war_window_stats_for_user(torn_user_id: int) -> Tuple[int, int, int, float, int, int]:
    """
    Cached wrapper (mirrors scan_ranked_war_stats_for_user):
    - per-user TTL cache
    - dedupe concurrent scans per user
    - invalidated automatically when war_start changes (via get_cached_ranked_war_start clearing ranked cache;
      we also validate war_start in this cache key)
    """
    now = int(time.time())
    war_start = await get_cached_ranked_war_start()

    cached = _war_window_stats_cache.get(int(torn_user_id))
    if cached:
        if int(cached.get("war_start")) == int(war_start) and (now - int(cached.get("computed_at", 0))) <= USER_STATS_CACHE_TTL_SECONDS:
            return (
                int(cached["total"]),
                int(cached["in_war"]),
                int(cached["out_war"]),
                float(cached["ff_sum"]),
                int(cached["ff_count"]),
                int(war_start),
            )

    inflight = _inflight_war_window_scans.get(int(torn_user_id))
    if inflight and not inflight.done():
        return await inflight

    async def _runner():
        try:
            result = await _compute_war_window_stats_for_user(int(torn_user_id))
            total, in_war, out_war, ff_sum, ff_count, ws = result
            _war_window_stats_cache[int(torn_user_id)] = {
                "war_start": int(ws),
                "computed_at": int(time.time()),
                "total": int(total),
                "in_war": int(in_war),
                "out_war": int(out_war),
                "ff_sum": float(ff_sum),
                "ff_count": int(ff_count),
            }
            return result
        finally:
            _inflight_war_window_scans.pop(int(torn_user_id), None)

    task = asyncio.create_task(_runner())
    _inflight_war_window_scans[int(torn_user_id)] = task
    return await task


# -----------------------------
# CHAIN (NEW)
# -----------------------------

def _safe_int(v, default: Optional[int] = None) -> Optional[int]:
    try:
        i = int(v)
        return i
    except Exception:
        return default


async def fetch_faction_chain() -> Dict[str, Any]:
    """
    Fetch chain status (v2). Uses Authorization header via torn_get().
    """
    data = await torn_get("/faction/chain")
    return data if isinstance(data, dict) else {}


def parse_active_chain(payload: dict) -> Optional[dict]:
    """
    Returns normalized chain dict if active, else None.
    Normalizes Torn's inconsistent typing (strings vs ints).
    """
    if not isinstance(payload, dict):
        return None

    chain = payload.get("chain")
    if not isinstance(chain, dict):
        return None

    chain_id = _safe_int(chain.get("id"))
    if not chain_id or chain_id <= 0:
        return None

    timeout = _safe_int(chain.get("timeout"), 0) or 0

    out: Dict[str, Any] = {
        "id": int(chain_id),
        "timeout": int(timeout),
    }

    for k in ("current", "max", "cooldown", "start", "end"):
        vi = _safe_int(chain.get(k))
        if vi is not None:
            out[k] = int(vi)

    # modifier can be float/int/string
    try:
        if chain.get("modifier") is not None:
            out["modifier"] = float(chain.get("modifier"))
    except Exception:
        pass

    return out
