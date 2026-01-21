import sqlite3
import time
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

    IMPORTANT:
    - This connection is used by command handlers and the chain watcher.
    - If you ever move to multiple processes, revisit this pattern.
    """
    con = sqlite3.connect(DB_PATH)

    # Optional but recommended for better concurrency characteristics
    # (readers don't block writers as much)
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


# -----------------------------
# ENCRYPTION HELPERS
# -----------------------------

def encrypt_key(api_key: str) -> bytes:
    return fernet.encrypt(api_key.encode("utf-8"))


def decrypt_key(enc: bytes) -> str:
    return fernet.decrypt(enc).decode("utf-8")


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

def chain_optin_clear_guild(con: sqlite3.Connection, guild_id: int) -> int:
    """
    Removes ALL /pingme opt-ins for a guild.
    Returns number of rows deleted.
    """
    cur = con.cursor()
    cur.execute(
        "DELETE FROM chain_ping_optin WHERE guild_id = ?",
        (int(guild_id),),
    )
    con.commit()
    return int(cur.rowcount or 0)


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


def chain_optin_list(con: sqlite3.Connection, guild_id: int) -> list[int]:
    cur = con.cursor()
    cur.execute(
        "SELECT user_id FROM chain_ping_optin WHERE guild_id = ?",
        (int(guild_id),),
    )
    return [int(row[0]) for row in cur.fetchall()]
