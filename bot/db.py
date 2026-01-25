import sqlite3
import time
from typing import Optional, Dict, Any, List
from dataclasses import dataclass

from cryptography.fernet import Fernet
from .config import DB_PATH, BOT_MASTER_KEY

fernet = Fernet(BOT_MASTER_KEY.encode("utf-8"))


# -----------------------------
# INIT / CONNECTION
# -----------------------------

def db_init() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)

    try:
        con.execute("PRAGMA journal_mode=WAL;")
    except Exception:
        pass

    cur = con.cursor()

    # Encrypted user keys table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_keys (
            discord_user_id INTEGER PRIMARY KEY,
            api_key_enc BLOB NOT NULL,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        )
    """)

    # Chain ping opt-in table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS chain_ping_optin (
            guild_id INTEGER NOT NULL,
            user_id  INTEGER NOT NULL,
            PRIMARY KEY (guild_id, user_id)
        )
    """)
    con.commit()
    return con

def ensure_roster_tables(conn):
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS roster_hour (
      guild_id INTEGER NOT NULL,
      day TEXT NOT NULL,            -- YYYY-MM-DD (UTC)
      start_hour INTEGER NOT NULL,  -- 0-23 (UTC)
      slot INTEGER NOT NULL,        -- 1-3
      name TEXT NOT NULL,

      state TEXT NOT NULL DEFAULT 'pending',  -- pending|online|late|missed|unknown
      first_seen_ts INTEGER,                  -- epoch seconds (UTC) when they first appeared online/idle
      late_minutes INTEGER NOT NULL DEFAULT 0,

      PRIMARY KEY (guild_id, day, start_hour, slot, name)
    );
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_roster_hour_lookup ON roster_hour(guild_id, day, start_hour);")
    conn.commit()


    # Global faction scan state (one cursor per war_start)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS war_scan_global (
            war_start INTEGER PRIMARY KEY,

            last_ts INTEGER NOT NULL DEFAULT 0,
            last_attack_id INTEGER NOT NULL DEFAULT 0,

            backfill_to INTEGER,
            is_initialized INTEGER NOT NULL DEFAULT 0,

            updated_at INTEGER NOT NULL
        )
    """)

    # Per-user rolling aggregates (won-only)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS war_user_agg (
            war_start INTEGER NOT NULL,
            torn_id INTEGER NOT NULL,

            ranked_wins INTEGER NOT NULL DEFAULT 0,
            other_wins INTEGER NOT NULL DEFAULT 0,

            ranked_ff_sum REAL NOT NULL DEFAULT 0,
            ranked_ff_count INTEGER NOT NULL DEFAULT 0,

            total_ff_sum REAL NOT NULL DEFAULT 0,
            total_ff_count INTEGER NOT NULL DEFAULT 0,

            updated_at INTEGER NOT NULL,
            PRIMARY KEY (war_start, torn_id)
        )
    """)

    con.commit()
    return con


# -----------------------------
# ENCRYPTION HELPERS
# -----------------------------

def encrypt_key(api_key: str) -> bytes:
    return fernet.encrypt(api_key.encode("utf-8"))


def decrypt_key(enc: bytes) -> str:
    return fernet.decrypt(enc).decode("utf-8")

def roster_upsert_expected(conn, guild_id: int, day: str, start_hour: int, expected: list[tuple[int, str]]):
    """
    expected: list of (slot, name)
    Inserts pending rows for this hour. Does not delete existing rows (keeps history).
    """
    cur = conn.cursor()
    for slot, name in expected:
        cur.execute("""
        INSERT OR IGNORE INTO roster_hour(guild_id, day, start_hour, slot, name)
        VALUES(?,?,?,?,?)
        """, (guild_id, day, start_hour, slot, name))
    conn.commit()

def roster_mark_online(conn, guild_id: int, day: str, start_hour: int, slot: int, name: str, first_seen_ts: int, late_minutes: int):
    cur = conn.cursor()
    cur.execute("""
    UPDATE roster_hour
       SET state = CASE WHEN ? > 0 THEN 'late' ELSE 'online' END,
           first_seen_ts = COALESCE(first_seen_ts, ?),
           late_minutes = CASE WHEN late_minutes = 0 THEN ? ELSE late_minutes END
     WHERE guild_id=? AND day=? AND start_hour=? AND slot=? AND name=?
       AND state IN ('pending','unknown')
    """, (late_minutes, first_seen_ts, late_minutes, guild_id, day, start_hour, slot, name))
    conn.commit()

def roster_mark_missed(conn, guild_id: int, day: str, start_hour: int):
    cur = conn.cursor()
    cur.execute("""
    UPDATE roster_hour
       SET state = 'missed'
     WHERE guild_id=? AND day=? AND start_hour=?
       AND state = 'pending'
    """, (guild_id, day, start_hour))
    conn.commit()

def roster_mark_unknown(conn, guild_id: int, day: str, start_hour: int, slot: int, name: str):
    cur = conn.cursor()
    cur.execute("""
    UPDATE roster_hour
       SET state = 'unknown'
     WHERE guild_id=? AND day=? AND start_hour=? AND slot=? AND name=?
       AND state = 'pending'
    """, (guild_id, day, start_hour, slot, name))
    conn.commit()

def roster_get_hour(conn, guild_id: int, day: str, start_hour: int):
    cur = conn.cursor()
    cur.execute("""
    SELECT slot, name, state, late_minutes, first_seen_ts
      FROM roster_hour
     WHERE guild_id=? AND day=? AND start_hour=?
     ORDER BY slot ASC, name COLLATE NOCASE ASC
    """, (guild_id, day, start_hour))
    rows = cur.fetchall()
    return [
        {"slot": r[0], "name": r[1], "state": r[2], "late_minutes": r[3], "first_seen_ts": r[4]}
        for r in rows
    ]

def roster_report(conn, guild_id: int, day_from: str | None = None, day_to: str | None = None):
    """
    Returns per-name totals: missed_count, late_count, total_late_minutes
    Optional day range.
    """
    params = [guild_id]
    where = "WHERE guild_id=?"
    if day_from:
        where += " AND day >= ?"
        params.append(day_from)
    if day_to:
        where += " AND day <= ?"
        params.append(day_to)

    cur = conn.cursor()
    cur.execute(f"""
    SELECT name,
           SUM(CASE WHEN state='missed' THEN 1 ELSE 0 END) AS missed,
           SUM(CASE WHEN state='late' THEN 1 ELSE 0 END)   AS late,
           SUM(CASE WHEN state='late' THEN late_minutes ELSE 0 END) AS late_minutes
      FROM roster_hour
      {where}
     GROUP BY name
     HAVING missed > 0 OR late > 0
     ORDER BY missed DESC, late_minutes DESC, late DESC, name COLLATE NOCASE ASC
    """, params)
    rows = cur.fetchall()
    return [
        {"name": r[0], "missed": int(r[1] or 0), "late": int(r[2] or 0), "late_minutes": int(r[3] or 0)}
        for r in rows
    ]


# -----------------------------
# USER API KEY STORAGE
# -----------------------------

def upsert_user_key(con: sqlite3.Connection, discord_user_id: int, api_key_plain: str) -> None:
    enc = encrypt_key(api_key_plain)
    now = int(time.time())

    cur = con.cursor()
    cur.execute("""
        INSERT INTO user_keys (discord_user_id, api_key_enc, created_at, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(discord_user_id) DO UPDATE SET
            api_key_enc=excluded.api_key_enc,
            updated_at=excluded.updated_at
    """, (int(discord_user_id), enc, now, now))
    con.commit()


def get_user_key(con: sqlite3.Connection, discord_user_id: int) -> Optional[str]:
    cur = con.cursor()
    cur.execute("SELECT api_key_enc FROM user_keys WHERE discord_user_id=?", (int(discord_user_id),))
    row = cur.fetchone()
    if not row:
        return None
    return decrypt_key(row[0])


def delete_user_key(con: sqlite3.Connection, discord_user_id: int) -> bool:
    cur = con.cursor()
    cur.execute("DELETE FROM user_keys WHERE discord_user_id=?", (int(discord_user_id),))
    con.commit()
    return cur.rowcount > 0


# -----------------------------
# CHAIN PING OPT-IN
# -----------------------------

def chain_optin_add(con: sqlite3.Connection, guild_id: int, user_id: int) -> None:
    cur = con.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO chain_ping_optin (guild_id, user_id) VALUES (?, ?)",
        (int(guild_id), int(user_id)),
    )
    con.commit()


def chain_optin_remove(con: sqlite3.Connection, guild_id: int, user_id: int) -> None:
    cur = con.cursor()
    cur.execute(
        "DELETE FROM chain_ping_optin WHERE guild_id = ? AND user_id = ?",
        (int(guild_id), int(user_id)),
    )
    con.commit()


def chain_optin_clear_guild(con: sqlite3.Connection, guild_id: int) -> int:
    cur = con.cursor()
    cur.execute("DELETE FROM chain_ping_optin WHERE guild_id = ?", (int(guild_id),))
    con.commit()
    return int(cur.rowcount or 0)


def chain_optin_list(con: sqlite3.Connection, guild_id: int) -> list[int]:
    cur = con.cursor()
    cur.execute(
        "SELECT user_id FROM chain_ping_optin WHERE guild_id = ?",
        (int(guild_id),),
    )
    return [int(row[0]) for row in cur.fetchall()]


# -----------------------------
# WAR SCAN GLOBAL + AGGREGATES
# -----------------------------

@dataclass
class WarScanGlobalState:
    war_start: int
    last_ts: int
    last_attack_id: int
    backfill_to: Optional[int]
    is_initialized: int
    updated_at: int


def war_global_get(con: sqlite3.Connection, war_start: int) -> Optional[WarScanGlobalState]:
    cur = con.cursor()
    cur.execute("""
        SELECT war_start, last_ts, last_attack_id, backfill_to, is_initialized, updated_at
        FROM war_scan_global
        WHERE war_start = ?
    """, (int(war_start),))
    row = cur.fetchone()
    if not row:
        return None
    return WarScanGlobalState(
        war_start=int(row[0]),
        last_ts=int(row[1]),
        last_attack_id=int(row[2]),
        backfill_to=(int(row[3]) if row[3] is not None else None),
        is_initialized=int(row[4]),
        updated_at=int(row[5]),
    )


def war_global_reset(con: sqlite3.Connection, war_start: int) -> WarScanGlobalState:
    now = int(time.time())
    st = WarScanGlobalState(
        war_start=int(war_start),
        last_ts=int(war_start),          # start cursor at war start
        last_attack_id=0,
        backfill_to=None,
        is_initialized=0,
        updated_at=now,
    )
    cur = con.cursor()
    cur.execute("""
        INSERT INTO war_scan_global (war_start, last_ts, last_attack_id, backfill_to, is_initialized, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(war_start) DO UPDATE SET
            last_ts=excluded.last_ts,
            last_attack_id=excluded.last_attack_id,
            backfill_to=excluded.backfill_to,
            is_initialized=excluded.is_initialized,
            updated_at=excluded.updated_at
    """, (st.war_start, st.last_ts, st.last_attack_id, st.backfill_to, st.is_initialized, st.updated_at))
    con.commit()
    return st


def war_global_save(con: sqlite3.Connection, st: WarScanGlobalState) -> None:
    st.updated_at = int(time.time())
    cur = con.cursor()
    cur.execute("""
        INSERT INTO war_scan_global (war_start, last_ts, last_attack_id, backfill_to, is_initialized, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(war_start) DO UPDATE SET
            last_ts=excluded.last_ts,
            last_attack_id=excluded.last_attack_id,
            backfill_to=excluded.backfill_to,
            is_initialized=excluded.is_initialized,
            updated_at=excluded.updated_at
    """, (st.war_start, st.last_ts, st.last_attack_id, st.backfill_to, st.is_initialized, st.updated_at))
    con.commit()


def war_agg_apply(
    con: sqlite3.Connection,
    war_start: int,
    torn_id: int,
    is_ranked: bool,
    ff_value: Optional[float],
) -> None:
    """
    Apply ONE won hit into aggregates.
    """
    now = int(time.time())
    ranked_inc = 1 if is_ranked else 0
    other_inc = 0 if is_ranked else 1

    total_ff_sum_inc = float(ff_value) if ff_value is not None else 0.0
    total_ff_count_inc = 1 if ff_value is not None else 0

    ranked_ff_sum_inc = float(ff_value) if (is_ranked and ff_value is not None) else 0.0
    ranked_ff_count_inc = 1 if (is_ranked and ff_value is not None) else 0

    cur = con.cursor()
    cur.execute("""
        INSERT INTO war_user_agg (
            war_start, torn_id,
            ranked_wins, other_wins,
            ranked_ff_sum, ranked_ff_count,
            total_ff_sum, total_ff_count,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(war_start, torn_id) DO UPDATE SET
            ranked_wins = ranked_wins + excluded.ranked_wins,
            other_wins  = other_wins  + excluded.other_wins,
            ranked_ff_sum   = ranked_ff_sum   + excluded.ranked_ff_sum,
            ranked_ff_count = ranked_ff_count + excluded.ranked_ff_count,
            total_ff_sum    = total_ff_sum    + excluded.total_ff_sum,
            total_ff_count  = total_ff_count  + excluded.total_ff_count,
            updated_at = excluded.updated_at
    """, (
        int(war_start), int(torn_id),
        ranked_inc, other_inc,
        ranked_ff_sum_inc, ranked_ff_count_inc,
        total_ff_sum_inc, total_ff_count_inc,
        now
    ))
    con.commit()


def war_agg_get(con: sqlite3.Connection, war_start: int, torn_id: int) -> Dict[str, Any]:
    cur = con.cursor()
    cur.execute("""
        SELECT ranked_wins, other_wins,
               ranked_ff_sum, ranked_ff_count,
               total_ff_sum, total_ff_count
        FROM war_user_agg
        WHERE war_start = ? AND torn_id = ?
    """, (int(war_start), int(torn_id)))
    row = cur.fetchone()
    if not row:
        return {
            "ranked_wins": 0,
            "other_wins": 0,
            "ranked_ff_sum": 0.0,
            "ranked_ff_count": 0,
            "total_ff_sum": 0.0,
            "total_ff_count": 0,
        }
    return {
        "ranked_wins": int(row[0]),
        "other_wins": int(row[1]),
        "ranked_ff_sum": float(row[2]),
        "ranked_ff_count": int(row[3]),
        "total_ff_sum": float(row[4]),
        "total_ff_count": int(row[5]),
    }


def war_agg_list_all(con: sqlite3.Connection, war_start: int) -> List[Dict[str, Any]]:
    cur = con.cursor()
    cur.execute("""
        SELECT torn_id, ranked_wins, other_wins,
               ranked_ff_sum, ranked_ff_count,
               total_ff_sum, total_ff_count
        FROM war_user_agg
        WHERE war_start = ?
        ORDER BY ranked_wins DESC, other_wins DESC, torn_id ASC
    """, (int(war_start),))
    out: List[Dict[str, Any]] = []
    for row in cur.fetchall():
        out.append({
            "torn_id": int(row[0]),
            "ranked_wins": int(row[1]),
            "other_wins": int(row[2]),
            "ranked_ff_sum": float(row[3]),
            "ranked_ff_count": int(row[4]),
            "total_ff_sum": float(row[5]),
            "total_ff_count": int(row[6]),
        })
    return out
