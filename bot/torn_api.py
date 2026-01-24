import time
import asyncio
from typing import Optional, List, Tuple, Dict, Any

import aiohttp
import sqlite3

from .config import (
    TORN_API_KEY,
    TORN_BASE,
    WAR_START_CACHE_TTL_SECONDS,
    TORN_TIMEOUT_SECONDS,
)
from .utils import extract_to_from_prev_url
from .db import (
    war_global_get, war_global_reset, war_global_save,
    war_agg_apply, war_agg_get, war_agg_list_all
)


# ----------------------------
# DB connection injected from main.py
# ----------------------------
_db_conn: Optional[sqlite3.Connection] = None

def set_db_conn(con: sqlite3.Connection) -> None:
    global _db_conn
    _db_conn = con


# -------------------------------------------------------------------
# Internal caches
# -------------------------------------------------------------------
_war_start_cache: Dict[str, Any] = {"ts": None, "fetched_at": 0}

# Optional tiny cache for faction members -> names (used in leadership list)
_member_name_cache: Dict[str, Any] = {"fetched_at": 0, "map": {}}


# -------------------------------------------------------------------
# Small helpers
# -------------------------------------------------------------------
def _safe_int0(v) -> int:
    try:
        return int(v)
    except Exception:
        return 0


def _safe_float(v) -> Optional[float]:
    try:
        return float(v)
    except Exception:
        return None


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
async def fetch_faction_wars() -> dict:
    return await torn_get("/faction/wars")


async def fetch_faction_members() -> List[dict]:
    data = await torn_get("/faction/members")
    members = data.get("members", [])
    if not isinstance(members, list):
        return []
    return members


async def fetch_faction_attacks_outgoing(limit: int = 100, to: Optional[int] = None) -> dict:
    params = {"filters": "outgoing", "sort": "DESC", "limit": str(limit)}
    if to is not None:
        params["to"] = str(int(to))
    return await torn_get("/faction/attacks", params=params)


# -------------------------------------------------------------------
# Ranked war start helpers
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

    _war_start_cache["ts"] = int(war_start)
    _war_start_cache["fetched_at"] = now
    return int(war_start)


# -------------------------------------------------------------------
# Member name lookup (leadership list prettiness)
# -------------------------------------------------------------------
async def get_member_name_map(ttl_seconds: int = 300) -> Dict[int, str]:
    now = int(time.time())
    if (now - int(_member_name_cache.get("fetched_at") or 0)) <= ttl_seconds:
        mp = _member_name_cache.get("map") or {}
        return {int(k): str(v) for k, v in mp.items()}

    members = await fetch_faction_members()
    mp2: Dict[int, str] = {}
    for m in members:
        if not isinstance(m, dict):
            continue
        mid = _safe_int0(m.get("id"))
        name = m.get("name")
        if mid > 0 and isinstance(name, str) and name:
            mp2[mid] = name

    _member_name_cache["fetched_at"] = now
    _member_name_cache["map"] = dict(mp2)
    return mp2


# -------------------------------------------------------------------
# Global scan engine (one scan updates everyone)
# -------------------------------------------------------------------
async def scan_faction_attacks_progress(
    pages_head: int = 1,
    pages_backfill: int = 3,
) -> Tuple[int, int]:
    """
    Progress the global scan.
    Returns: (is_initialized, pages_scanned_estimate)
    """
    if _db_conn is None:
        raise RuntimeError("DB connection not set in torn_api (set_db_conn not called).")

    war_start = await get_cached_ranked_war_start()

    st = war_global_get(_db_conn, war_start)
    if st is None:
        st = war_global_reset(_db_conn, war_start)

    pages_scanned = 0

    # -------------------------
    # HEAD SCAN (newest hits)
    # -------------------------
    to_val: Optional[int] = None
    new_cursor_ts = int(st.last_ts)
    new_cursor_id = int(st.last_attack_id)

    for _ in range(pages_head):
        page = await fetch_faction_attacks_outgoing(limit=100, to=to_val)
        pages_scanned += 1
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

            # stop when we reach already processed boundary
            if (started < st.last_ts) or (started == st.last_ts and attack_id_i <= st.last_attack_id):
                stop = True
                break

            if started < war_start:
                # shouldn't happen in head scan, but safe
                continue

            # update cursor to newest seen
            if (started > new_cursor_ts) or (started == new_cursor_ts and attack_id_i > new_cursor_id):
                new_cursor_ts, new_cursor_id = started, attack_id_i

            # won-only: respect_gain > 0
            rg = a.get("respect_gain")
            try:
                rgf = float(rg)
            except Exception:
                rgf = 0.0
            if rgf <= 0:
                continue

            attacker = a.get("attacker") or {}
            attacker_id = _safe_int0(attacker.get("id"))
            if attacker_id <= 0:
                continue

            modifiers = a.get("modifiers") or {}
            war_mod = _safe_int0(modifiers.get("war"))
            is_ranked = (war_mod == 2) or bool(a.get("is_ranked_war", False))

            ff = _safe_float(modifiers.get("fair_fight"))

            war_agg_apply(_db_conn, war_start, attacker_id, is_ranked, ff)

        if stop:
            break

        prev_url = (((page.get("_metadata") or {}).get("links") or {}).get("prev"))
        to_val = extract_to_from_prev_url(prev_url)
        if to_val is None:
            break

    st.last_ts = int(new_cursor_ts)
    st.last_attack_id = int(new_cursor_id)

    # initialize backfill cursor once so we don't keep re-reading newest pages
    if st.is_initialized == 0 and st.backfill_to is None:
        st.backfill_to = int(to_val) if to_val is not None else None

    # -------------------------
    # BACKFILL (older pages)
    # -------------------------
    if st.is_initialized == 0:
        to_val = st.backfill_to

        for _ in range(pages_backfill):
            page = await fetch_faction_attacks_outgoing(limit=100, to=to_val)
            pages_scanned += 1
            attacks = page.get("attacks", [])
            if not isinstance(attacks, list) or not attacks:
                st.is_initialized = 1
                st.backfill_to = None
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

                # won-only
                try:
                    rgf = float(a.get("respect_gain") or 0)
                except Exception:
                    rgf = 0.0
                if rgf <= 0:
                    continue

                attacker = a.get("attacker") or {}
                attacker_id = _safe_int0(attacker.get("id"))
                if attacker_id <= 0:
                    continue

                modifiers = a.get("modifiers") or {}
                war_mod = _safe_int0(modifiers.get("war"))
                is_ranked = (war_mod == 2) or bool(a.get("is_ranked_war", False))
                ff = _safe_float(modifiers.get("fair_fight"))

                war_agg_apply(_db_conn, war_start, attacker_id, is_ranked, ff)

            if stop:
                st.is_initialized = 1
                st.backfill_to = None
                break

            prev_url = (((page.get("_metadata") or {}).get("links") or {}).get("prev"))
            next_to = extract_to_from_prev_url(prev_url)
            if next_to is None:
                st.is_initialized = 1
                st.backfill_to = None
                break

            st.backfill_to = int(next_to)
            to_val = int(next_to)

    war_global_save(_db_conn, st)
    return int(st.is_initialized), int(pages_scanned)


# -------------------------------------------------------------------
# Public stats accessors for commands
# -------------------------------------------------------------------
async def get_user_warstats(torn_user_id: int) -> Dict[str, Any]:
    """
    Returns dict containing wins + ff sums/counts for current war_start.
    Also triggers a small scan burst to keep progress moving.
    """
    if _db_conn is None:
        raise RuntimeError("DB connection not set in torn_api (set_db_conn not called).")

    war_start = await get_cached_ranked_war_start()

    # kick scan a little to keep data fresh
    await scan_faction_attacks_progress(pages_head=1, pages_backfill=2)

    agg = war_agg_get(_db_conn, war_start, int(torn_user_id))
    ranked_wins = int(agg["ranked_wins"])
    other_wins = int(agg["other_wins"])

    ranked_ff_count = int(agg["ranked_ff_count"])
    ranked_ff_avg = (float(agg["ranked_ff_sum"]) / ranked_ff_count) if ranked_ff_count > 0 else None

    total_ff_count = int(agg["total_ff_count"])
    total_ff_avg = (float(agg["total_ff_sum"]) / total_ff_count) if total_ff_count > 0 else None

    st = war_global_get(_db_conn, war_start)

    return {
        "war_start": int(war_start),
        "ranked_wins": ranked_wins,
        "other_wins": other_wins,
        "ranked_ff_avg": ranked_ff_avg,
        "total_ff_avg": total_ff_avg,
        "is_initialized": int(st.is_initialized) if st else 0,
        "backfill_to": int(st.backfill_to) if (st and st.backfill_to is not None) else None,
    }

async def fetch_faction_balance() -> dict:
    return await torn_get("/faction/balance")
def _safe_int(v, default: Optional[int] = None) -> Optional[int]:
    try:
        return int(v)
    except Exception:
        return default


async def fetch_faction_chain() -> Dict[str, Any]:
    data = await torn_get("/faction/chain")
    return data if isinstance(data, dict) else {}

async def fetch_user_status(user_id: int) -> Dict[str, Any]:
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


async def get_all_warstats() -> Dict[str, Any]:
    """
    Leadership list: returns all aggregates for current war_start.
    Also triggers a scan burst.
    """
    if _db_conn is None:
        raise RuntimeError("DB connection not set in torn_api (set_db_conn not called).")

    war_start = await get_cached_ranked_war_start()
    await scan_faction_attacks_progress(pages_head=1, pages_backfill=3)

    rows = war_agg_list_all(_db_conn, war_start)
    st = war_global_get(_db_conn, war_start)

    name_map = await get_member_name_map()

    # decorate rows with name + averages
    out_rows: List[Dict[str, Any]] = []
    for r in rows:
        ranked_ff_avg = (r["ranked_ff_sum"] / r["ranked_ff_count"]) if r["ranked_ff_count"] > 0 else None
        total_ff_avg = (r["total_ff_sum"] / r["total_ff_count"]) if r["total_ff_count"] > 0 else None
        tid = int(r["torn_id"])
        out_rows.append({
            "torn_id": tid,
            "name": name_map.get(tid, f"[{tid}]"),
            "ranked_wins": int(r["ranked_wins"]),
            "other_wins": int(r["other_wins"]),
            "ranked_ff_avg": ranked_ff_avg,
            "total_ff_avg": total_ff_avg,
        })

    return {
        "war_start": int(war_start),
        "rows": out_rows,
        "is_initialized": int(st.is_initialized) if st else 0,
    }
