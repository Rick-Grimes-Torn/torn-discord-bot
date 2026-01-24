# bot/torn_api.py
import time
import asyncio
from typing import Optional, List, Tuple, Dict, Any

import aiohttp
import sqlite3

from .config import (
    TORN_API_KEY,
    TORN_BASE,
    WAR_START_CACHE_TTL_SECONDS,
    USER_STATS_CACHE_TTL_SECONDS,
    TORN_TIMEOUT_SECONDS,
)
from .utils import extract_to_from_prev_url
from .db import war_state_get, war_state_reset, war_state_save


# -------------------------------------------------------------------
# Internal caches
# -------------------------------------------------------------------

_war_start_cache: Dict[str, Any] = {"ts": None, "fetched_at": 0}
_user_stats_cache: Dict[int, Dict[str, Any]] = {}
_inflight_user_scans: Dict[int, asyncio.Task] = {}
_war_window_stats_cache: Dict[int, Dict[str, Any]] = {}
_inflight_war_window_scans: Dict[int, asyncio.Task] = {}

# DB connection injected from main.py
_db_conn: Optional[sqlite3.Connection] = None


def set_db_conn(con: sqlite3.Connection) -> None:
    global _db_conn
    _db_conn = con


# -------------------------------------------------------------------
# Small helpers
# -------------------------------------------------------------------

def _safe_int0(v) -> int:
    try:
        return int(v)
    except Exception:
        return 0


def _raise_torn_error(data) -> None:
    if not isinstance(data, dict) or "error" not in data:
        return
    err = data.get("error")
    if isinstance(err, dict):
        code = err.get("code")
        message = err.get("error") or err.get("message") or str(err)
        raise RuntimeError(f"Torn error{f' {code}' if code else ''}: {message}")
    raise RuntimeError(f"Torn error: {err}")


# -------------------------------------------------------------------
# Core HTTP helper
# -------------------------------------------------------------------

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

    # war changed -> clear in-memory caches (DB state resets per-user anyway)
    if cached_ts is not None and int(cached_ts) != int(war_start):
        _user_stats_cache.clear()
        _war_window_stats_cache.clear()

    _war_start_cache["ts"] = int(war_start)
    _war_start_cache["fetched_at"] = now
    return int(war_start)


# -------------------------------------------------------------------
# Shared scanning engine pieces
# -------------------------------------------------------------------

async def _head_scan_update_state(
    *,
    torn_user_id: int,
    mode: str,
    st,
    war_start: int,
    count_ranked_only: bool,
    split_in_out: bool,
    head_pages: int = 2,
) -> Tuple[int, int]:
    """
    Scan newest pages and STOP once we hit last_ts/last_attack_id.
    Updates:
      - st aggregates (only for this user)
      - st.last_ts / st.last_attack_id to newest seen in head scan
    Returns: (next_to_after_head_scan, pages_scanned_flag_cursor_set)
    """
    to_val: Optional[int] = None

    new_cursor_ts = int(st.last_ts)
    new_cursor_id = int(st.last_attack_id)

    for _ in range(head_pages):
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

            attack_id_i = _safe_int0(a.get("id"))

            # Stop when we reach already-processed region (prevents infinite rescan)
            if (started < st.last_ts) or (started == st.last_ts and attack_id_i <= st.last_attack_id):
                stop = True
                break

            # Track newest cursor across faction feed
            if (started > new_cursor_ts) or (started == new_cursor_ts and attack_id_i > new_cursor_id):
                new_cursor_ts, new_cursor_id = started, attack_id_i

            # Filter to this user
            attacker = a.get("attacker") or {}
            if _safe_int0(attacker.get("id")) != int(torn_user_id):
                continue

            # For ranked-only mode, only count ranked war hits
            is_ranked = bool(a.get("is_ranked_war", False))
            if count_ranked_only and not is_ranked:
                continue

            # War start guard (just in case)
            if started < int(war_start):
                continue

            st.total += 1

            if split_in_out:
                if is_ranked:
                    st.in_war += 1
                else:
                    st.out_war += 1

            modifiers = a.get("modifiers") or {}
            ff = (modifiers or {}).get("fair_fight")
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

    st.last_ts = int(new_cursor_ts)
    st.last_attack_id = int(new_cursor_id)

    # After head scan, to_val is the "next older" cursor
    return (int(to_val) if to_val is not None else None)


async def _backfill_progress(
    *,
    torn_user_id: int,
    mode: str,
    st,
    war_start: int,
    count_ranked_only: bool,
    split_in_out: bool,
    backfill_pages: int = 3,
) -> None:
    """
    Progressive backfill:
    - continues from st.backfill_to (None means start from newest page)
    - scans a few pages per call
    - stops when started < war_start and marks initialized
    """
    to_val = st.backfill_to  # may be None

    for _ in range(backfill_pages):
        page = await fetch_faction_attacks_outgoing(limit=100, to=to_val)
        attacks = page.get("attacks", [])
        if not isinstance(attacks, list) or not attacks:
            st.is_initialized = 1
            st.backfill_to = None
            return

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

            # Filter to this user
            attacker = a.get("attacker") or {}
            if _safe_int0(attacker.get("id")) != int(torn_user_id):
                continue

            is_ranked = bool(a.get("is_ranked_war", False))
            if count_ranked_only and not is_ranked:
                continue

            st.total += 1

            if split_in_out:
                if is_ranked:
                    st.in_war += 1
                else:
                    st.out_war += 1

            modifiers = a.get("modifiers") or {}
            ff = (modifiers or {}).get("fair_fight")
            try:
                if ff is not None:
                    st.ff_sum += float(ff)
                    st.ff_count += 1
            except Exception:
                pass

        if stop:
            st.is_initialized = 1
            st.backfill_to = None
            return

        prev_url = (((page.get("_metadata") or {}).get("links") or {}).get("prev"))
        next_to = extract_to_from_prev_url(prev_url)
        if next_to is None:
            st.is_initialized = 1
            st.backfill_to = None
            return

        st.backfill_to = int(next_to)
        to_val = int(next_to)


# -------------------------------------------------------------------
# Ranked war stats (per user)
# -------------------------------------------------------------------

async def _compute_ranked_war_stats_for_user(torn_user_id: int) -> Tuple[int, float, int, int]:
    war_start = await get_cached_ranked_war_start()

    if _db_conn is None:
        # Fall back to old behavior if DB not wired (shouldn't happen in your bot)
        raise RuntimeError("DB connection not set in torn_api (set_db_conn not called).")

    st = war_state_get(_db_conn, "ranked", int(torn_user_id))
    if (st is None) or (int(st.war_start) != int(war_start)):
        st = war_state_reset(_db_conn, "ranked", int(torn_user_id), int(war_start))

    # 1) Head scan to pick up newest hits (and advance last_ts/last_attack_id)
    next_to_after_head = await _head_scan_update_state(
        torn_user_id=int(torn_user_id),
        mode="ranked",
        st=st,
        war_start=int(war_start),
        count_ranked_only=True,
        split_in_out=False,
        head_pages=2,
    )

    # Initialize backfill cursor once so we don't keep re-scanning the newest pages
    if st.is_initialized == 0 and st.backfill_to is None:
        st.backfill_to = next_to_after_head

    # 2) Progressive backfill until war_start reached
    if st.is_initialized == 0:
        await _backfill_progress(
            torn_user_id=int(torn_user_id),
            mode="ranked",
            st=st,
            war_start=int(war_start),
            count_ranked_only=True,
            split_in_out=False,
            backfill_pages=3,
        )

    war_state_save(_db_conn, st)
    return int(st.total), float(st.ff_sum), int(st.ff_count), int(war_start)


async def scan_ranked_war_stats_for_user(torn_user_id: int) -> Tuple[int, float, int, int]:
    now = int(time.time())
    war_start = await get_cached_ranked_war_start()

    cached = _user_stats_cache.get(int(torn_user_id))

    # If DB state exists and we're still backfilling, force recompute so each call makes progress.
    if _db_conn is not None:
        st = war_state_get(_db_conn, "ranked", int(torn_user_id))
        if st is not None and int(st.is_initialized) == 0:
            cached = None

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
    war_start = await get_cached_ranked_war_start()

    if _db_conn is None:
        raise RuntimeError("DB connection not set in torn_api (set_db_conn not called).")

    st = war_state_get(_db_conn, "window", int(torn_user_id))
    if (st is None) or (int(st.war_start) != int(war_start)):
        st = war_state_reset(_db_conn, "window", int(torn_user_id), int(war_start))

    # 1) Head scan (newest)
    next_to_after_head = await _head_scan_update_state(
        torn_user_id=int(torn_user_id),
        mode="window",
        st=st,
        war_start=int(war_start),
        count_ranked_only=False,
        split_in_out=True,
        head_pages=2,
    )

    if st.is_initialized == 0 and st.backfill_to is None:
        st.backfill_to = next_to_after_head

    # 2) Backfill
    if st.is_initialized == 0:
        await _backfill_progress(
            torn_user_id=int(torn_user_id),
            mode="window",
            st=st,
            war_start=int(war_start),
            count_ranked_only=False,
            split_in_out=True,
            backfill_pages=3,
        )

    war_state_save(_db_conn, st)

    return (
        int(st.total),
        int(st.in_war),
        int(st.out_war),
        float(st.ff_sum),
        int(st.ff_count),
        int(war_start),
    )


async def scan_war_window_stats_for_user(torn_user_id: int) -> Tuple[int, int, int, float, int, int]:
    now = int(time.time())
    war_start = await get_cached_ranked_war_start()

    cached = _war_window_stats_cache.get(int(torn_user_id))

    # If still backfilling, disable TTL cache so repeated calls progress the cursor.
    if _db_conn is not None:
        st = war_state_get(_db_conn, "window", int(torn_user_id))
        if st is not None and int(st.is_initialized) == 0:
            cached = None

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
