# bot/db.py
import sqlite3
import time
from dataclasses import dataclass
from typing import Optional

from cryptography.fernet import Fernet

from .config import DB_PATH, BOT_MASTER_KEY

fernet = Fernet(BOT_MASTER_KEY.encode("utf-8"))


# -----------------------------
# INIT / CONNECTION
# -----------------------------

def db_init() -> sqlite3.Connection:
    """
    Open (and initialize) the SQLite database and return a connection
    intended to stay open for the bot's lifetime.
    """
    # check_same_thread=False avoids occasional issues when tasks/callbacks
    # touch the same connection from different execution contexts.
    con = sqlite3.connect(DB_PATH, check_same_thread=False)

    # Better concurrency characteristics
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

    # War scan state table (checkpoint + rolling aggregates)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS war_scan_state (
            mode TEXT NOT NULL,              -- 'ranked' or 'window'
            torn_id INTEGER NOT NULL,
            war_start INTEGER NOT NULL,

            last_ts INTEGER NOT NULL,         -- last processed attack.started
            last_attack_id INTEGER NOT NULL,  -- tie-breaker for identical timestamps

            total INTEGER NOT NULL DEFAULT 0,
            in_war INTEGER NOT NULL DEFAULT 0,
            out_war INTEGER NOT NULL DEFAULT 0,

            ff_sum REAL NOT NULL DEFAULT 0,
            ff_count INTEGER NOT NULL DEFAULT 0,

            updated_at INTEGER NOT NULL,
            PRIMARY KEY (mode, torn_id)
        )
    """)

    # One-time migration for older DBs that had war_scan_state without last_attack_id
    try:
        cur.execute("ALTER TABLE war_scan_state ADD COLUMN last_attack_id INTEGER NOT NULL DEFAULT 0;")
    except sqlite3.OperationalError:
        # Column already exists (or table created with it)
        pass

    con.commit()
    return con


# -----------------------------
# ENCRYPTION HELPERS
# -----------------------------

def encrypt_key(api_key: str) -> bytes:
    return fernet.encrypt(api_key.encode("utf-8"))


def decrypt_key(enc: bytes) -> str:
    return fernet.decrypt(enc).decode("utf-8")


# -----------------------------
# WAR SCAN STATE (CHECKPOINTS)
# -----------------------------

@dataclass
class WarScanState:
    mode: str
    torn_id: int
    war_start: int
    last_ts: int
    last_attack_id: int
    total: int
    in_war: int
    out_war: int
    ff_sum: float
    ff_count: int
    updated_at: int


def war_state_get(con: sqlite3.Connection, mode: str, torn_id: int) -> Optional[WarScanState]:
    cur = con.cursor()
    cur.execute("""
        SELECT mode, torn_id, war_start, last_ts, last_attack_id,
               total, in_war, out_war, ff_sum, ff_count, updated_at
        FROM war_scan_state
        WHERE mode = ? AND torn_id = ?
    """, (str(mode), int(torn_id)))
    row = cur.fetchone()
    if not row:
        return None

    return WarScanState(
        mode=str(row[0]),
        torn_id=int(row[1]),
        war_start=int(row[2]),
        last_ts=int(row[3]),
        last_attack_id=int(row[4]),
        total=int(row[5]),
        in_war=int(row[6]),
        out_war=int(row[7]),
        ff_sum=float(row[8]),
        ff_count=int(row[9]),
        updated_at=int(row[10]),
    )


def war_state_reset(con: sqlite3.Connection, mode: str, torn_id: int, war_start: int) -> WarScanState:
    now = int(time.time())
    st = WarScanState(
        mode=str(mode),
        torn_id=int(torn_id),
        war_start=int(war_start),
        last_ts=int(war_start),
        last_attack_id=0,
        total=0,
        in_war=0,
        out_war=0,
        ff_sum=0.0,
        ff_count=0,
        updated_at=now,
    )
    _war_state_upsert(con, st)
    return st


def war_state_save(con: sqlite3.Connection, st: WarScanState) -> None:
    st.updated_at = int(time.time())
    _war_state_upsert(con, st)


def _war_state_upsert(con: sqlite3.Connection, st: WarScanState) -> None:
    cur = con.cursor()
    cur.execute("""
        INSERT INTO war_scan_state (
            mode, torn_id, war_start, last_ts, last_attack_id,
            total, in_war, out_war, ff_sum, ff_count, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(mode, torn_id) DO UPDATE SET
            war_start=excluded.war_start,
            last_ts=excluded.last_ts,
            last_attack_id=excluded.last_attack_id,
            total=excluded.total,
            in_war=excluded.in_war,
            out_war=excluded.out_war,
            ff_sum=excluded.ff_sum,
            ff_count=excluded.ff_count,
            updated_at=excluded.updated_at
    """, (
        st.mode, int(st.torn_id), int(st.war_start), int(st.last_ts), int(st.last_attack_id),
        int(st.total), int(st.in_war), int(st.out_war), float(st.ff_sum), int(st.ff_count), int(st.updated_at),
    ))
    con.commit()


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
    return (cur.rowcount or 0) > 0


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


def chain_optin_list(con: sqlite3.Connection, guild_id: int) -> list[int]:
    cur = con.cursor()
    cur.execute(
        "SELECT user_id FROM chain_ping_optin WHERE guild_id = ?",
        (int(guild_id),),
    )
    return [int(row[0]) for row in cur.fetchall()]


def chain_optin_clear_guild(con: sqlite3.Connection, guild_id: int) -> int:
    """
    Removes ALL /pingme opt-ins for a guild.
    Returns number of rows deleted.
    """
    cur = con.cursor()
    cur.execute("DELETE FROM chain_ping_optin WHERE guild_id = ?", (int(guild_id),))
    con.commit()
    return int(cur.rowcount or 0)
