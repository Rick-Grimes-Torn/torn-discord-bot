from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from typing import List

import aiohttp

from bot import config

@dataclass(frozen=True)
class BotDataRow:
    day: str         # YYYY-MM-DD
    start_hour: int  # 0-23
    slot: int        # 1-3
    name: str

async def fetch_bot_data_rows() -> List[BotDataRow]:
    url = config.SHEET_BOT_DATA_CSV_URL
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
            resp.raise_for_status()
            text = await resp.text()

    f = io.StringIO(text)
    reader = csv.DictReader(f)

    out: List[BotDataRow] = []
    for r in reader:
        day = (r.get("date") or "").strip()
        sh = (r.get("start_hour") or "").strip()
        slot = (r.get("slot") or "").strip()
        name = (r.get("name") or "").strip()

        if not day or not sh or not slot or not name:
            continue

        try:
            out.append(BotDataRow(day=day, start_hour=int(sh), slot=int(slot), name=name))
        except Exception:
            continue

    return out
