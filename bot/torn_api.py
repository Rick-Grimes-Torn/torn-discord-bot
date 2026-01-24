# bot/torn_api.py
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

import sqlite3
from .db import war_state_get, war_state_reset, war_state_save, WarScanState

_db_conn: Optional[sqlite3.Connection] = None

def set_db_conn(con: sqlite3.Connection) -> None:
    global _db_conn
    _db_conn = con


# -------------------------------------------------------------------
# Internal caches
# -------------------------------------------------------------------

_war_start_cache: Dict[str, Any] = {"ts": None, "fetched_at": 0}
_user_stats_cache: Dict[int, Dict[str, Any]] = {}
_inflight_user_scans: Dict[int, asyncio.Task] = {}
_war_window_stats_cache: Dict[int, Dict[str, Any]] = {}
_inflight_war_window_scans: Dict[int, asyncio.Task] = {}


# -------------------------------------------------------------------
# Core HTTP helper
# -------------------------------------------------------------------

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
    headers = {
        "Authorization": f"ApiKey {TORN_API_KEY}",
        "User-Agent": "discord-torn-bot",
    }

    if timeout is None:
        timeout = TORN_TIMEOUT_SECONDS

    try:
        timeout_seconds = float(timeout)
    except (TypeError, ValueError):
        timeout_seconds = 25.0

    timeout_obj = aiohttp.ClientTimeout(total=timeout_seconds)

    async with aiohttp.ClientSession(timeout=timeout_obj) as session:
        async with session.get(
            f"{TORN_BASE}{path}",
            headers=headers,
            params=params,
        ) as resp:
            data = await resp.json(content_type=None)

    _raise_torn_error(data)
    if not isinstance(data, dict):
        raise RuntimeError("Unexpected Torn API response (not a JSON object).")
    return data


# -------------------------------------------------------------------
# Faction endpoints
# -------------------------------------------------------------------

async def fetch_faction_members() -> List[dict]:
    data = await torn_get("/faction/members")
    members = data.get("members", [])
    if not isinstance(members, list):
        raise RuntimeError("Unexpected Torn API response: 'members' is not a list")
    return members


async def fetch_faction_balance() -> dict:
    return await torn_get("/faction/balance")


async def fetch_faction_wars() -> dict:
    return await torn_get("/faction/wars")


async def fetch_faction_attacks_outgoing(limit: int = 100, to: Optional[int] = None) -> dict:
    params = {"filters": "outgoing", "sort": "DESC", "limit": str(limit)}
    if to is not None:
        params["to"] = str(int(to))
    return await torn_get("/faction/attacks", params=params)


# -------------------------------------------------------------------
# Ranked war helpers
# -------------------------------------------------------------------

def get_latest_ranked_war_start(wars_payload: dict) -> Optional[int]:
    wars = wars_payload.get("wars") or {}
    ranked = wars.get("ranked") or {}
    start = ranked.get("start")
    try:
        s = int(start)
        return s if s > 0 else None
    except Exception:
        return None


async def get_cached_ranked_war_start() -> int:
    now = int(time.time())

    cached_ts = _war_start_cache.get("ts")
    fetched_at = int(_war_start_cache.get("fetched_at") or 0)

    if cached_ts and (now - fetched_at) <= WAR_START_CACHE_TTL_SECONDS:
        return int(cached_ts)

    wars = await fetch_faction_wars()
    war_start = get_latest_ranked_war_start(wars)
    if not war_start:
        raise RuntimeError("Could not find latest ranked war start timestamp.")

    if cached_ts is not None and int(cached_ts) != int(war_start):
        _user_stats_cache.clear()
        _war_window_stats_cache.clear()

    _war_start_cache["ts"] = int(war_start)
    _war_start_cache["fetched_at"] = now
    return int(war_start)


# -------------------------------------------------------------------
# Ranked war stats (per user)
# -------------------------------------------------------------------

async def _compute_ranked_war_stats_for_user(torn_user_id: int) -> Tuple[int, float, int, int]:
    if _db_conn is None:
        raise RuntimeError("DB connection not set in torn_api. Call torn_api.set_db_conn(client.db_conn).")

    war_start = await get_cached_ranked_war_start()

    # Load or reset state
    st = war_state_get(_db_conn, "ranked", int(torn_user_id))
    if (st is None) or (int(st.war_start) != int(war_start)):
        st = war_state_reset(_db_conn, "ranked", int(torn_user_id), int(war_start))

    to_val: Optional[int] = None
    max_pages = 5  # ✅ small cap; we should usually stop on page 1

    newest_ts = int(st.last_ts)
    newest_id = int(st.last_attack_id)

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

            # Always stop when older than war start
            if started < int(war_start):
                stop = True
                break

            # Cursor: (started, attack_id)
            attack_id = a.get("id")
            try:
                attack_id_i = int(attack_id)
            except Exception:
                attack_id_i = 0

            # If we've already processed this (or older), stop scanning deeper
            if (started < st.last_ts) or (started == st.last_ts and attack_id_i <= st.last_attack_id):
                stop = True
                break

            # Only ranked war hits
            if not a.get("is_ranked_war", False):
                # still update newest cursor (so we don't re-read forever)
                if (started > newest_ts) or (started == newest_ts and attack_id_i > newest_id):
                    newest_ts, newest_id = started, attack_id_i
                continue

            attacker = a.get("attacker") or {}
            try:
                attacker_id = int(attacker.get("id"))
            except Exception:
                continue

            if attacker_id != int(torn_user_id):
                if (started > newest_ts) or (started == newest_ts and attack_id_i > newest_id):
                    newest_ts, newest_id = started, attack_id_i
                continue

            st.total += 1

            modifiers = a.get("modifiers") or {}
            ff = modifiers.get("fair_fight")
            try:
                if ff is not None:
                    st.ff_sum += float(ff)
                    st.ff_count += 1
            except Exception:
                pass

            if (started > newest_ts) or (started == newest_ts and attack_id_i > newest_id):
                newest_ts, newest_id = started, attack_id_i

        if stop:
            break

        prev_url = (((page.get("_metadata") or {}).get("links") or {}).get("prev"))
        to_val = extract_to_from_prev_url(prev_url)
        if to_val is None:
            break

    # Save cursor
    st.last_ts = int(newest_ts)
    st.last_attack_id = int(newest_id)
    war_state_save(_db_conn, st)

    return int(st.total), float(st.ff_sum), int(st.ff_count), int(war_start)


async def scan_ranked_war_stats_for_user(torn_user_id: int) -> Tuple[int, float, int, int]:
    now = int(time.time())
    war_start = await get_cached_ranked_war_start()

    cached = _user_stats_cache.get(int(torn_user_id))
    if cached:
        if (
            int(cached.get("war_start")) == int(war_start)
            and (now - int(cached.get("computed_at", 0))) <= USER_STATS_CACHE_TTL_SECONDS
        ):
            return (
                int(cached["attacks"]),
                float(cached["ff_sum"]),
                int(cached["ff_count"]),
                int(war_start),
            )

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


# -------------------------------------------------------------------
# War window stats (per user)
# -------------------------------------------------------------------

async def _compute_war_window_stats_for_user(torn_user_id: int) -> Tuple[int, int, int, float, int, int]:
    if _db_conn is None:
        raise RuntimeError("DB connection not set in torn_api. Call torn_api.set_db_conn(client.db_conn).")

    war_start = await get_cached_ranked_war_start()

    st = war_state_get(_db_conn, "window", int(torn_user_id))
    if (st is None) or (int(st.war_start) != int(war_start)):
        st = war_state_reset(_db_conn, "window", int(torn_user_id), int(war_start))

    to_val: Optional[int] = None
    max_pages = 5

    newest_ts = int(st.last_ts)
    newest_id = int(st.last_attack_id)

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

            if started < int(war_start):
                stop = True
                break

            attack_id = a.get("id")
            try:
                attack_id_i = int(attack_id)
            except Exception:
                attack_id_i = 0

            if (started < st.last_ts) or (started == st.last_ts and attack_id_i <= st.last_attack_id):
                stop = True
                break

            attacker = a.get("attacker") or {}
            try:
                attacker_id = int(attacker.get("id"))
            except Exception:
                continue

            # advance newest cursor even if it's not this user (prevents rescanning)
            if (started > newest_ts) or (started == newest_ts and attack_id_i > newest_id):
                newest_ts, newest_id = started, attack_id_i

            if attacker_id != int(torn_user_id):
                continue

            st.total += 1

            if a.get("is_ranked_war", False):
                st.in_war += 1
            else:
                st.out_war += 1

            modifiers = a.get("modifiers") or {}
            ff = modifiers.get("fair_fight")
            try:
                if ff is not None:
                    st.ff_sum += float(ff)
                    st.ff_count += 1
            except Exception:
                pass

        if stop:
            break

        prev_url = (((page.get("_metadata") or {}).get("links") or {}).get("prev"))
        to_val = extract_to_from_prev_url(prev_url)
        if to_val is None:
            break

    st.last_ts = int(newest_ts)
    st.last_attack_id = int(newest_id)
    war_state_save(_db_conn, st)

    return int(st.total), int(st.in_war), int(st.out_war), float(st.ff_sum), int(st.ff_count), int(war_start)


async def scan_war_window_stats_for_user(torn_user_id: int) -> Tuple[int, int, int, float, int, int]:
    now = int(time.time())
    war_start = await get_cached_ranked_war_start()

    cached = _war_window_stats_cache.get(int(torn_user_id))
    if cached:
        if (
            int(cached.get("war_start")) == int(war_start)
            and (now - int(cached.get("computed_at", 0))) <= USER_STATS_CACHE_TTL_SECONDS
        ):
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


# -------------------------------------------------------------------
# Chain (v2)
# -------------------------------------------------------------------

def _safe_int(v, default: Optional[int] = None) -> Optional[int]:
    try:
        return int(v)
    except Exception:
        return default


async def fetch_faction_chain() -> Dict[str, Any]:
    data = await torn_get("/faction/chain")
    return data if isinstance(data, dict) else {}


def parse_active_chain(payload: dict) -> Optional[dict]:
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

    try:
        if chain.get("modifier") is not None:
            out["modifier"] = float(chain.get("modifier"))
    except Exception:
        pass

    return out


# -------------------------------------------------------------------
# USER STATUS (NEW)
# -------------------------------------------------------------------

async def fetch_user_status(user_id: int) -> Dict[str, Any]:
    """
    Fetch user status via v2. Returns status dict or {}.
    """
    params = {"id": str(int(user_id)), "selections": "basic"}
    data = await torn_get("/user", params=params)

    status = data.get("status")
    if isinstance(status, dict):
        return status

    basic = data.get("basic")
    if isinstance(basic, dict):
        s2 = basic.get("status")
        if isinstance(s2, dict):
            return s2

    return {}
