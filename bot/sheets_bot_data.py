from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import datetime
from typing import List

import aiohttp

from bot import config


@dataclass(frozen=True)
class BotDataRow:
    day: str         # YYYY-MM-DD (UTC)
    start_hour: int  # 0-23 (UTC)
    slot: int        # 1-3
    name: str


def _clean_day(s: str) -> str:
    """
    Normalize various possible date representations to YYYY-MM-DD.
    Accepts:
      - "YYYY-MM-DD"
      - "YYYY-MM-DD 00:00:00"
      - "YYYY/MM/DD"
      - "DD/MM/YYYY"
      - "MM/DD/YYYY"
    If parsing fails, returns the stripped string as-is.
    """
    s = (s or "").strip()
    if not s:
        return ""

    # Common: already "YYYY-MM-DD ..." -> take first 10 chars
    if len(s) >= 10 and s[4] in "-/" and s[7] in "-/":
        # Convert YYYY/MM/DD -> YYYY-MM-DD
        head = s[:10].replace("/", "-")
        # Validate shape
        if len(head) == 10 and head[4] == "-" and head[7] == "-":
            return head

    for fmt in ("%Y/%m/%d", "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except Exception:
            pass

    return s


def _parse_hour(s: str) -> int:
    """
    Parse hour from common sheet/export formats:
      - "16"
      - "16.0"
      - "16:00"
      - "16:00-17:00"
      - "16:00:00"
    """
    s = (s or "").strip()
    if not s:
        raise ValueError("empty hour")

    # Take first token if it's a range "16:00-17:00"
    if "-" in s:
        s = s.split("-", 1)[0].strip()

    # Take hour part "16:00" or "16:00:00"
    if ":" in s:
        s = s.split(":", 1)[0].strip()

    # Handle "16.0"
    if "." in s:
        s = s.split(".", 1)[0].strip()

    h = int(s)
    if h < 0 or h > 23:
        raise ValueError(f"hour out of range: {h}")
    return h


async def fetch_bot_data_rows() -> List[BotDataRow]:
    """
    Reads BOT_DATA CSV export with headers:
      date, start_hour, slot, name, day_title, source_cell

    Returns rows normalized to:
      day=YYYY-MM-DD, start_hour=int(0..23), slot=int, name=str
    """
    url = config.SHEET_BOT_DATA_CSV_URL
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
            resp.raise_for_status()
            text = await resp.text()

    f = io.StringIO(text)
    reader = csv.DictReader(f)

    out: List[BotDataRow] = []
    for r in reader:
        if not r:
            continue

        # Your actual headers
        day_raw = r.get("date", "")
        sh_raw = r.get("start_hour", "")
        slot_raw = r.get("slot", "")
        name = (r.get("name", "") or "").strip()

        day = _clean_day(day_raw)
        if not day or not sh_raw or not slot_raw or not name:
            continue

        try:
            start_hour = _parse_hour(sh_raw)
            slot = int(str(slot_raw).strip())
        except Exception:
            continue

        out.append(BotDataRow(day=day, start_hour=start_hour, slot=slot, name=name))

    return out
