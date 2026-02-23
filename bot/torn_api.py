import asyncio
import time
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
    war_global_get,
    war_global_reset,
    war_global_save,
    war_outcome_apply,
    war_bucket_apply,
    war_bucket_get,
    war_bucket_list_all,
    war_outcome_get_user,
    war_outcome_list_all,
    war_processed_try_mark,
)

# ----------------------------
# DB connection injected from main.py
# ----------------------------
_db_conn: Optional[sqlite3.Connection] = None
_scan_lock = asyncio.Lock()


def set_db_conn(con: sqlite3.Connection) -> None:
    global _db_conn
    _db_conn = con


# ----------------------------
# Outcome model
# ----------------------------

KNOWN_OUTCOMES = {
    "attacked",
    "lost",
    "mugged",
    "interrupted",
    "assist",
    "stalemate",
    "hospitalized",
    "special",
}

COUNTED_ATTACK_OUTCOMES = {
    "attacked",
    "mugged",
    "hospitalized",
    "special",
}


def _norm_outcome(v) -> str:
    if not isinstance(v, str) or not v.strip():
        return "unknown"
    o = v.strip().lower()
    return o if o in KNOWN_OUTCOMES else "other"


# -------------------------------------------------------------------
# Internal caches
# -------------------------------------------------------------------
_war_start_cache: Dict[str, Any] = {"ts": None, "fetched_at": 0}
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

    war_start = None
    try:
        wars = await fetch_faction_wars()
        war_start = get_latest_ranked_war_start(wars)
    except Exception:
        war_start = None

    if war_start:
        _war_start_cache["ts"] = int(war_start)
        _war_start_cache["fetched_at"] = now
        return int(war_start)

    # fallback 1: stale cache
    if cached_ts:
        return int(cached_ts)

    # fallback 2: last known in DB
    if _db_conn is not None:
        try:
            cur = _db_conn.cursor()
            cur.execute("SELECT MAX(war_start) FROM war_scan_global")
            row = cur.fetchone()
            if row and row[0]:
                ws = int(row[0])
                _war_start_cache["ts"] = ws
                _war_start_cache["fetched_at"] = now
                return ws
        except Exception:
            pass

    raise RuntimeError(
        "Could not find latest ranked war start timestamp (no active ranked war and no previous war cached)."
    )


# -------------------------------------------------------------------
# Member name lookup (leaderboard prettiness)
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
# Scan mode (fast-fill until initialized, then normal)
# -------------------------------------------------------------------
def _scan_params_for_state(st) -> Tuple[int, int]:
    if st is not None and int(getattr(st, "is_initialized", 0)) == 0:
        return 10, 25
    return 10, 2


def _process_attack(
    a: dict,
    war_start: int,
    cursor_ts: int,
    cursor_id: int,
    seen_attack_ids: set,
    db_conn,
) -> Tuple[bool, bool, int, int]:
    """
    Process a single attack dict.

    Returns: (hit_cursor_boundary, counted, new_cursor_ts, new_cursor_id)

    hit_cursor_boundary=True means we've reached attacks we've already processed —
    the caller should stop fetching more pages in this direction.

    CRITICAL ordering:
      1. Check cursor boundary FIRST (before try_mark) so we don't permanently
         mark an attack as processed when we're only skipping it due to the boundary.
      2. Check per-invocation dedupe (seen_attack_ids) second.
      3. Only then call war_processed_try_mark (persistent dedupe).
    """
    if not isinstance(a, dict):
        return False, False, cursor_ts, cursor_id

    started = a.get("started")
    if not isinstance(started, int):
        return False, False, cursor_ts, cursor_id

    attack_id_i = _safe_int0(a.get("id"))
    if attack_id_i <= 0:
        return False, False, cursor_ts, cursor_id

    # --- Step 1: Cursor boundary check BEFORE any marking ---
    # If this attack is at or before our saved cursor, we've already processed
    # everything up to and including this point. Signal the caller to stop.
    if started < cursor_ts or (started == cursor_ts and attack_id_i <= cursor_id):
        return True, False, cursor_ts, cursor_id

    # --- Step 2: Must be within the war window ---
    if started < war_start:
        return True, False, cursor_ts, cursor_id  # past war start, stop scanning

    # --- Step 3: Per-invocation dedupe (page boundary overlap) ---
    if attack_id_i in seen_attack_ids:
        return False, False, cursor_ts, cursor_id
    seen_attack_ids.add(attack_id_i)

    # --- Step 4: Persistent dedupe (across bot restarts / multiple callers) ---
    if not war_processed_try_mark(db_conn, war_start, attack_id_i):
        # Already counted in a previous scan run — update cursor and move on
        new_ts = started if started > cursor_ts or (started == cursor_ts and attack_id_i > cursor_id) else cursor_ts
        new_id = attack_id_i if started >= new_ts else cursor_id
        return False, False, max(started, cursor_ts), attack_id_i if started == max(started, cursor_ts) else cursor_id

    # --- Step 5: Count the attack ---
    outcome = _norm_outcome(a.get("result"))

    attacker = a.get("attacker") or {}
    attacker_id = _safe_int0(attacker.get("id"))
    if attacker_id <= 0:
        return False, False, cursor_ts, cursor_id

    is_ranked = bool(a.get("is_ranked_war", False))
    bucket = "ranked" if is_ranked else "outside"

    war_outcome_apply(db_conn, war_start, attacker_id, bucket, outcome)

    if outcome in COUNTED_ATTACK_OUTCOMES:
        modifiers = a.get("modifiers") or {}
        ff = _safe_float(modifiers.get("fair_fight"))

        try:
            respect_gain = float(a.get("respect_gain") or 0)
        except Exception:
            respect_gain = 0.0

        try:
            respect_loss = float(a.get("respect_loss") or 0)
        except Exception:
            respect_loss = 0.0

        war_bucket_apply(
            db_conn,
            war_start,
            attacker_id,
            bucket,
            ff,
            respect_gain,
            respect_loss,
        )

    return False, True, cursor_ts, cursor_id


# -------------------------------------------------------------------
# Global scan engine (one scan updates everyone)
# -------------------------------------------------------------------
async def scan_faction_attacks_progress(
    pages_head: int = 10,
    pages_backfill: int = 3,
) -> Tuple[int, int]:
    """
    Progress the global scan.
    Returns: (is_initialized, pages_scanned_estimate)

    Safety:
      - global async lock prevents concurrent overlapping scans
      - per-scan seen_attack_ids prevents boundary duplicates within an invocation
      - persistent war_processed_attack prevents duplicates across runs/restarts
      - cursor boundary check happens BEFORE try_mark so attacks are never lost

    Head scan:
      - Fetches newest pages until it hits the known cursor (already-processed boundary)
      - pages_head caps the maximum pages per call to avoid runaway API usage
      - This ensures ALL new attacks since the last scan are captured, not just 100

    Backfill:
      - Only runs while is_initialized == 0
      - Works backwards from where the head scan ended
      - Marks is_initialized = 1 when war_start boundary is reached
    """
    async with _scan_lock:
        if _db_conn is None:
            raise RuntimeError("DB connection not set in torn_api (set_db_conn not called).")

        war_start = await get_cached_ranked_war_start()

        st = war_global_get(_db_conn, war_start)
        if st is None:
            st = war_global_reset(_db_conn, war_start)

        pages_scanned = 0
        seen_attack_ids: set[int] = set()

        # Snapshot the cursor at the start of this scan run.
        # We use this fixed snapshot for boundary checks throughout the head scan
        # so that cursor updates within this run don't affect our stop condition.
        cursor_ts = int(st.last_ts)
        cursor_id = int(st.last_attack_id)

        # Track the highest (newest) attack seen this run for cursor advancement
        new_cursor_ts = cursor_ts
        new_cursor_id = cursor_id

        # -------------------------
        # HEAD SCAN (newest hits)
        # -------------------------
        # Fetch pages newest-first until we hit attacks we've already processed.
        # pages_head caps API calls per invocation; any remaining new attacks will
        # be caught on the next command invocation.
        to_val: Optional[int] = None
        reached_cursor = False

        for _ in range(pages_head):
            page = await fetch_faction_attacks_outgoing(limit=100, to=to_val)
            pages_scanned += 1

            attacks = page.get("attacks", [])
            if not isinstance(attacks, list) or not attacks:
                reached_cursor = True
                break

            for a in attacks:
                hit_boundary, _counted, _new_ts, _new_id = _process_attack(
                    a, war_start, cursor_ts, cursor_id, seen_attack_ids, _db_conn
                )

                if hit_boundary:
                    reached_cursor = True
                    break

                # Track newest attack for cursor advancement
                started = a.get("started")
                aid = _safe_int0(a.get("id"))
                if isinstance(started, int) and aid > 0:
                    if started > new_cursor_ts or (started == new_cursor_ts and aid > new_cursor_id):
                        new_cursor_ts = started
                        new_cursor_id = aid

            if reached_cursor:
                break

            prev_url = (((page.get("_metadata") or {}).get("links") or {}).get("prev"))
            to_next = extract_to_from_prev_url(prev_url)
            if to_next is None:
                reached_cursor = True
                break

            to_val = int(to_next)

        # Advance the cursor to the newest attack we saw
        st.last_ts = int(new_cursor_ts)
        st.last_attack_id = int(new_cursor_id)

        # Initialize backfill cursor once (points to the oldest page the head scan reached)
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

                    # Past the war window — backfill complete
                    if started < war_start:
                        stop = True
                        break

                    attack_id_i = _safe_int0(a.get("id"))
                    if attack_id_i <= 0:
                        continue

                    # Per-invocation dedupe
                    if attack_id_i in seen_attack_ids:
                        continue
                    seen_attack_ids.add(attack_id_i)

                    # Persistent dedupe
                    if not war_processed_try_mark(_db_conn, war_start, attack_id_i):
                        continue

                    outcome = _norm_outcome(a.get("result"))

                    attacker = a.get("attacker") or {}
                    attacker_id = _safe_int0(attacker.get("id"))
                    if attacker_id <= 0:
                        continue

                    is_ranked = bool(a.get("is_ranked_war", False))
                    bucket = "ranked" if is_ranked else "outside"

                    war_outcome_apply(_db_conn, war_start, attacker_id, bucket, outcome)

                    if outcome in COUNTED_ATTACK_OUTCOMES:
                        modifiers = a.get("modifiers") or {}
                        ff = _safe_float(modifiers.get("fair_fight"))

                        try:
                            respect_gain = float(a.get("respect_gain") or 0)
                        except Exception:
                            respect_gain = 0.0

                        try:
                            respect_loss = float(a.get("respect_loss") or 0)
                        except Exception:
                            respect_loss = 0.0

                        war_bucket_apply(
                            _db_conn,
                            war_start,
                            attacker_id,
                            bucket,
                            ff,
                            respect_gain,
                            respect_loss,
                        )

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
    if _db_conn is None:
        raise RuntimeError("DB connection not set in torn_api (set_db_conn not called).")

    war_start = await get_cached_ranked_war_start()

    st = war_global_get(_db_conn, war_start)
    ph, pb = _scan_params_for_state(st)
    await scan_faction_attacks_progress(pages_head=ph, pages_backfill=pb)

    ranked = war_bucket_get(_db_conn, war_start, int(torn_user_id), "ranked")
    outside = war_bucket_get(_db_conn, war_start, int(torn_user_id), "outside")

    ranked_hits = int(ranked.get("hits_total", 0))
    outside_hits = int(outside.get("hits_total", 0))

    ranked_ff_sum = float(ranked.get("ff_sum", 0.0))
    ranked_ff_count = int(ranked.get("ff_count", 0))
    ranked_ff_avg = (ranked_ff_sum / ranked_ff_count) if ranked_ff_count > 0 else None

    outside_ff_sum = float(outside.get("ff_sum", 0.0))
    outside_ff_count = int(outside.get("ff_count", 0))
    outside_ff_avg = (outside_ff_sum / outside_ff_count) if outside_ff_count > 0 else None

    total_ff_sum = ranked_ff_sum + outside_ff_sum
    total_ff_count = ranked_ff_count + outside_ff_count
    total_ff_avg = (total_ff_sum / total_ff_count) if total_ff_count > 0 else None

    st2 = war_global_get(_db_conn, war_start)

    return {
        "war_start": int(war_start),
        "ranked_wins": ranked_hits,
        "other_wins": outside_hits,
        "ranked_ff_avg": ranked_ff_avg,
        "other_ff_avg": outside_ff_avg,
        "total_ff_avg": total_ff_avg,
        "is_initialized": int(st2.is_initialized) if st2 else 0,
        "backfill_to": int(st2.backfill_to) if (st2 and st2.backfill_to is not None) else None,
    }


async def get_user_war_outcomes(torn_user_id: int) -> Dict[str, Any]:
    if _db_conn is None:
        raise RuntimeError("DB connection not set in torn_api (set_db_conn not called).")

    war_start = await get_cached_ranked_war_start()

    st = war_global_get(_db_conn, war_start)
    ph, pb = _scan_params_for_state(st)
    await scan_faction_attacks_progress(pages_head=ph, pages_backfill=pb)

    return {
        "war_start": int(war_start),
        "outcomes": war_outcome_get_user(_db_conn, war_start, int(torn_user_id)),
    }


async def get_all_warstats() -> Dict[str, Any]:
    if _db_conn is None:
        raise RuntimeError("DB connection not set in torn_api (set_db_conn not called).")

    war_start = await get_cached_ranked_war_start()

    st = war_global_get(_db_conn, war_start)
    ph, pb = _scan_params_for_state(st)
    await scan_faction_attacks_progress(pages_head=ph, pages_backfill=pb)

    rows = war_bucket_list_all(_db_conn, war_start)
    st2 = war_global_get(_db_conn, war_start)
    name_map = await get_member_name_map()

    by_user: Dict[int, Dict[str, Any]] = {}

    for r in rows:
        tid = int(r.get("torn_id", 0))
        if tid <= 0:
            continue
        bucket = str(r.get("bucket") or "")

        if tid not in by_user:
            by_user[tid] = {
                "ranked_hits": 0,
                "outside_hits": 0,
                "ranked_ff_sum": 0.0,
                "ranked_ff_count": 0,
                "outside_ff_sum": 0.0,
                "outside_ff_count": 0,
            }

        if bucket == "ranked":
            by_user[tid]["ranked_hits"] = int(r.get("hits_total", 0))
            by_user[tid]["ranked_ff_sum"] = float(r.get("ff_sum", 0.0))
            by_user[tid]["ranked_ff_count"] = int(r.get("ff_count", 0))
        else:
            by_user[tid]["outside_hits"] = int(r.get("hits_total", 0))
            by_user[tid]["outside_ff_sum"] = float(r.get("ff_sum", 0.0))
            by_user[tid]["outside_ff_count"] = int(r.get("ff_count", 0))

    out_rows: List[Dict[str, Any]] = []

    for tid, data in by_user.items():
        ranked_ff_avg = (
            (data["ranked_ff_sum"] / data["ranked_ff_count"]) if data["ranked_ff_count"] > 0 else None
        )
        outside_ff_avg = (
            (data["outside_ff_sum"] / data["outside_ff_count"]) if data["outside_ff_count"] > 0 else None
        )

        total_ff_sum = data["ranked_ff_sum"] + data["outside_ff_sum"]
        total_ff_count = data["ranked_ff_count"] + data["outside_ff_count"]
        total_ff_avg = (total_ff_sum / total_ff_count) if total_ff_count > 0 else None

        out_rows.append(
            {
                "torn_id": tid,
                "name": name_map.get(tid, f"[{tid}]"),
                "ranked_wins": int(data["ranked_hits"]),
                "other_wins": int(data["outside_hits"]),
                "ranked_ff_avg": ranked_ff_avg,
                "other_ff_avg": outside_ff_avg,
                "total_ff_avg": total_ff_avg,
            }
        )

    out_rows.sort(
        key=lambda r: (
            int(r.get("ranked_wins", 0)),
            int(r.get("other_wins", 0)),
        ),
        reverse=True,
    )

    return {
        "war_start": int(war_start),
        "rows": out_rows,
        "is_initialized": int(st2.is_initialized) if st2 else 0,
    }


async def get_all_war_outcomes() -> Dict[str, Any]:
    if _db_conn is None:
        raise RuntimeError("DB connection not set in torn_api (set_db_conn not called).")

    war_start = await get_cached_ranked_war_start()

    st = war_global_get(_db_conn, war_start)
    ph, pb = _scan_params_for_state(st)
    await scan_faction_attacks_progress(pages_head=ph, pages_backfill=pb)

    rows = war_outcome_list_all(_db_conn, war_start)
    name_map = await get_member_name_map()

    out: Dict[int, Dict[str, Dict[str, int]]] = {}
    for r in rows:
        tid = int(r["torn_id"])
        b = str(r["bucket"])
        o = str(r["outcome"])
        c = int(r["count"] or 0)
        out.setdefault(tid, {}).setdefault(b, {})[o] = c

    return {
        "war_start": int(war_start),
        "rows": [
            {"torn_id": tid, "name": name_map.get(tid, f"[{tid}]"), "outcomes": buckets}
            for tid, buckets in out.items()
        ],
    }


# -------------------------------------------------------------------
# Other endpoints used by the bot
# -------------------------------------------------------------------
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

    out2: Dict[str, Any] = {
        "id": int(chain_id),
        "timeout": int(timeout),
    }

    for k in ("current", "max", "cooldown", "start", "end"):
        vi = _safe_int(chain.get(k))
        if vi is not None:
            out2[k] = int(vi)

    try:
        if chain.get("modifier") is not None:
            out2["modifier"] = float(chain.get("modifier"))
    except Exception:
        pass

    return out2


# Backwards-compatible aliases
scan_ranked_war_stats_for_user = scan_faction_attacks_progress
scan_war_window_stats_for_user = scan_faction_attacks_progress