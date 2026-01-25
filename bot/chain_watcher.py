# bot/chain_watcher.py
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Optional, Set, List

import discord

from . import torn_api
from . import db
from .targets import TargetPicker


# -------------------------------------------------------------------
# CONFIG (change in ONE place)
# -------------------------------------------------------------------

@dataclass(frozen=True)
class ChainAlertConfig:
    # Who can start/stop
    control_roles: Set[str] = frozenset({"Negan Saviors", "Lieutenant Saviors"})

    # Who is eligible to be pinged
    ping_role_name: str = "Savior"

    # Target link lines
    msg_target_line: str = "🎯 Easy target: {url}"
    msg_target_none: str = "🎯 Easy target: *(none available right now)*"

    # When to alert (seconds remaining). Live value from Torn: chain.timeout
    alert_seconds: int = 75

    # Poll interval (seconds)
    poll_seconds: int = 15

    # Message templates (edit here)
    msg_role_missing: str = (
        "⛓️ Chain low: **{timeout}s** left (chain `{chain_id}`)\n"
        "⚠️ Role `{ping_role}` not found — nobody pinged."
    )
    msg_no_eligible: str = (
        "⛓️ Chain low: **{timeout}s** left (chain `{chain_id}`)\n"
        "(No **{ping_role}** members eligible to ping.)"
    )
    msg_alert_header: str = (
        "⛓️ **CHAIN TIMER LOW** — **{timeout}s** left (chain `{chain_id}`)\n"
        "Pinging **{ping_role}** members:"
    )


CFG = ChainAlertConfig()


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------

def is_chain_controller(member: discord.Member) -> bool:
    return any(r.name in CFG.control_roles for r in getattr(member, "roles", []))


def chunk_mentions(user_ids: List[int], max_len: int = 1800) -> List[str]:
    chunks: List[str] = []
    cur = ""
    for uid in user_ids:
        mention = f"<@{uid}> "
        if len(cur) + len(mention) > max_len:
            if cur:
                chunks.append(cur.strip())
            cur = mention
        else:
            cur += mention
    if cur:
        chunks.append(cur.strip())
    return chunks


# -------------------------------------------------------------------
# Watcher
# -------------------------------------------------------------------

@dataclass
class ChainWatcherState:
    running: bool = False
    channel_id: Optional[int] = None
    started_by: Optional[int] = None
    last_chain_id: Optional[int] = None
    alert_armed: bool = True  # re-arms when timeout > CFG.alert_seconds or chain id changes


class ChainWatcher:
    """
    Polls Torn /faction/chain and pings when timeout <= CFG.alert_seconds.

    Pings only members with role CFG.ping_role_name who are:
      - opted-in via /pingme (even if offline)
    """

    def get_status_snapshot(self, guild_id: int) -> dict:
        """
        Returns a small, safe snapshot of watcher state for /chainstatus and /status.
        No API calls; purely internal state + CFG values.
        """
        st = self._state(guild_id)
        return {
            "running": bool(st.running),
            "channel_id": st.channel_id,
            "started_by": st.started_by,
            "last_chain_id": st.last_chain_id,
            "alert_armed": bool(st.alert_armed),
            "poll_seconds": int(self.poll_seconds),
            "ping_role_name": CFG.ping_role_name,
            "alert_seconds": int(CFG.alert_seconds),
            "control_roles": sorted(list(CFG.control_roles)),
        }

    def __init__(self, client: discord.Client, db_conn, poll_seconds: Optional[int] = None):
        self.client = client
        self.db_conn = db_conn
        self.poll_seconds = int(poll_seconds if poll_seconds is not None else CFG.poll_seconds)

        self._state_by_guild: dict[int, ChainWatcherState] = {}
        self._tasks: dict[int, asyncio.Task] = {}

        # Pick “easy target” link for alerts (cached to avoid API spam)
        self.target_picker = TargetPicker(cache_ttl_seconds=60)

    def _state(self, guild_id: int) -> ChainWatcherState:
        return self._state_by_guild.setdefault(guild_id, ChainWatcherState())

    async def start(self, guild: discord.Guild, channel: discord.abc.Messageable, started_by: int) -> None:
        st = self._state(guild.id)
        st.running = True
        st.channel_id = getattr(channel, "id", None)
        st.started_by = int(started_by)
        st.alert_armed = True

        task = self._tasks.get(guild.id)
        if task and not task.done():
            return  # already running

        self._tasks[guild.id] = asyncio.create_task(self._run_loop(guild.id))

    async def stop(self, guild_id: int) -> None:
        st = self._state(guild_id)
        st.running = False

        task = self._tasks.get(guild_id)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def _run_loop(self, guild_id: int) -> None:
        while True:
            st = self._state(guild_id)
            if not st.running:
                return

            try:
                payload = await torn_api.fetch_faction_chain()
                chain = torn_api.parse_active_chain(payload)

                if not chain:
                    st.last_chain_id = None
                    st.alert_armed = True
                    await asyncio.sleep(self.poll_seconds)
                    continue

                chain_id = int(chain["id"])
                timeout = int(chain.get("timeout") or 0)

                # New chain => re-arm
                if st.last_chain_id != chain_id:
                    st.last_chain_id = chain_id
                    st.alert_armed = True

                # New hit resets timer => when it goes back above threshold, re-arm for next drop
                if timeout > CFG.alert_seconds:
                    st.alert_armed = True

                # Fire once per "danger window"
                if timeout <= CFG.alert_seconds and st.alert_armed:
                    st.alert_armed = False
                    await self._send_alert(guild_id, chain_id, timeout)

            except asyncio.CancelledError:
                raise
            except Exception as e:
                print("[chain] watcher error:", repr(e))

            await asyncio.sleep(self.poll_seconds)

    async def _send_alert(self, guild_id: int, chain_id: int, timeout: int) -> None:
        guild = self.client.get_guild(guild_id)
        if not guild:
            return

        st = self._state(guild_id)
        channel = guild.get_channel(st.channel_id) if st.channel_id else None
        if channel is None:
            return

        ping_role = discord.utils.get(guild.roles, name=CFG.ping_role_name)
        if not ping_role:
            await channel.send(
                CFG.msg_role_missing.format(
                    timeout=timeout, chain_id=chain_id, ping_role=CFG.ping_role_name
                )
            )
            return

        opted_in_ids = set(db.chain_optin_list(self.db_conn, guild_id))

        ping_ids: Set[int] = set()
        for member in guild.members:
            if member.bot:
                continue

            # Opt-in ONLY
            if member.id not in opted_in_ids:
                continue

            # Still require the ping role (prevents pinging ex-members / role removals)
            if ping_role not in member.roles:
                continue

            ping_ids.add(member.id)


        if not ping_ids:
            await channel.send(
                CFG.msg_no_eligible.format(
                    timeout=timeout, chain_id=chain_id, ping_role=CFG.ping_role_name
                )
            )
            return

        # Pick first available target (in configured order)
        target = await self.target_picker.pick_first_available()
        if target:
            target_line = CFG.msg_target_line.format(url=target.url)
        else:
            err = getattr(self.target_picker, "last_error", None)
            if err:
                target_line = CFG.msg_target_none + f"\nℹ️ debug: `{err}`"
            else:
                target_line = CFG.msg_target_none

        await channel.send(
            CFG.msg_alert_header.format(
                timeout=timeout, chain_id=chain_id, ping_role=CFG.ping_role_name
            )
            + "\n"
            + target_line
        )

        for chunk in chunk_mentions(sorted(ping_ids)):
            await channel.send(chunk)
