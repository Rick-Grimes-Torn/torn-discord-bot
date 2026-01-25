from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import discord

from bot import config, db, torn_api
from bot.sheets_bot_data import fetch_bot_data_rows

def _utc_day_hour(ts: int | None = None) -> tuple[str, int]:
    now = datetime.fromtimestamp(ts or time.time(), tz=timezone.utc)
    return now.strftime("%Y-%m-%d"), now.hour

def _hour_start_ts(day: str, hour: int) -> int:
    dt = datetime.strptime(f"{day} {hour:02d}:00:00", "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    return int(dt.timestamp())

def _is_online_like(last_action_status: str | None) -> bool:
    if not last_action_status:
        return False
    s = str(last_action_status).strip().lower()
    return s in {"online", "idle"}

def _norm_name(s: str) -> str:
    return str(s or "").strip().lower()

@dataclass
class HourState:
    day: str
    hour: int
    expected: list[tuple[int, str]]  # (slot, name)
    alerted: bool = False

class RosterMonitor:
    def __init__(self, client: discord.Client, db_conn):
        self.client = client
        self.db_conn = db_conn
        self._task: asyncio.Task | None = None
        self._stop_evt = asyncio.Event()
        self._hour_state_by_guild: dict[int, HourState] = {}
        self._last_alert_by_guild: dict[int, int] = {}

    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self):
        if self.running():
            return
        self._stop_evt = asyncio.Event()
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self):
        if not self.running():
            return
        self._stop_evt.set()
        try:
            await asyncio.wait_for(self._task, timeout=10)
        except Exception:
            pass
        self._task = None
        self._hour_state_by_guild.clear()

    async def _run_loop(self):
        # loop forever until stop, but only acts for guilds where chain watcher is running
        while not self._stop_evt.is_set():
            try:
                await self._tick()
            except Exception as e:
                print("RosterMonitor tick error:", repr(e))
            await asyncio.sleep(int(config.ROSTER_CHECK_INTERVAL_SECONDS))

    async def _tick(self):
        # Only process guilds where chain watcher says it's running.
        for guild in self.client.guilds:
            snap = self.client.chain_watcher.get_status_snapshot(guild.id)
            if not snap.get("running"):
                # clear per-guild hour state if watcher stopped
                self._hour_state_by_guild.pop(guild.id, None)
                continue

            day, hour = _utc_day_hour()
            hs = self._hour_state_by_guild.get(guild.id)
            if not hs or hs.day != day or hs.hour != hour:
                # New hour: load BOT_DATA and seed expected list
                expected = await self._get_expected_for_hour(day, hour)
                self._hour_state_by_guild[guild.id] = HourState(day=day, hour=hour, expected=expected, alerted=False)

                # write expected to DB
                db.roster_upsert_expected(self.db_conn, guild.id, day, hour, expected)

                # also mark last hour missed (pending -> missed) if any
                # (only if we had a previous hour state)
                if hs:
                    db.roster_mark_missed(self.db_conn, guild.id, hs.day, hs.hour)

            # Evaluate current hour
            await self._evaluate_hour(guild, self._hour_state_by_guild[guild.id])

    async def _get_expected_for_hour(self, day: str, hour: int) -> list[tuple[int, str]]:
        rows = await fetch_bot_data_rows()
        exp = [(r.slot, r.name) for r in rows if r.day == day and r.start_hour == hour]
        # Keep stable order: slot then name
        exp.sort(key=lambda x: (x[0], _norm_name(x[1])))
        return exp

    async def _evaluate_hour(self, guild: discord.Guild, hs: HourState):
        if not hs.expected:
            return  # no signups this hour => no alert

        # Fetch faction members once, build name->last_action.status
        members_payload = await torn_api.fetch_faction_members()
        members = (members_payload or {}).get("members") or {}

        status_by_name = {}
        for _mid, m in members.items():
            name = m.get("name")
            la = (m.get("last_action") or {})
            status_by_name[_norm_name(name)] = la.get("status")

        # Determine who is online-like
        online_like = []
        offline_like = []

        now_ts = int(time.time())
        hour_start = _hour_start_ts(hs.day, hs.hour)

        for slot, name in hs.expected:
            key = _norm_name(name)
            st = status_by_name.get(key)

            if st is None:
                # Unknown mapping; track it but don’t treat as offline alert
                db.roster_mark_unknown(self.db_conn, guild.id, hs.day, hs.hour, slot, name)
                continue

            if _is_online_like(st):
                online_like.append((slot, name))
                late_minutes = max(0, int((now_ts - hour_start) // 60))
                grace = int(config.ROSTER_GRACE_MINUTES)
                late_minutes = max(0, late_minutes - grace)
                db.roster_mark_online(self.db_conn, guild.id, hs.day, hs.hour, slot, name, now_ts, late_minutes)
            else:
                offline_like.append((slot, name))

        # Alert once on the hour ONLY if none of the signed-up are online/idle
        if not online_like and offline_like and not hs.alerted:
            # Only allow one alert per hour per guild (extra safety)
            last_alert = int(self._last_alert_by_guild.get(guild.id, 0))
            if (now_ts - last_alert) >= int(config.ROSTER_ALERT_MIN_INTERVAL_SECONDS):
                hs.alerted = True
                self._last_alert_by_guild[guild.id] = now_ts
                await self._send_hour_alert(guild, hs)

    async def _send_hour_alert(self, guild: discord.Guild, hs: HourState):
        snap = self.client.chain_watcher.get_status_snapshot(guild.id)
        chan_id = snap.get("channel_id")
        if not chan_id:
            return
        channel = guild.get_channel(int(chan_id))
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return

        # message: names scheduled this hour, none online
        names = [n for (_slot, n) in hs.expected]
        names_txt = ", ".join(names) if names else "(none)"
        await channel.send(
            f"⚠️ **Roster alert ({hs.day} {hs.hour:02d}:00 UTC):** "
            f"Nobody signed up appears **online/idle in Torn** right now.\n"
            f"Scheduled: {names_txt}\n"
            f"Use `/roster now` to check statuses."
        )
