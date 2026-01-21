import re
import time
from dataclasses import dataclass
from typing import Iterable, Optional

from . import torn_api
from .config import EASY_TARGET_ATTACK_LINKS, DISALLOWED_TARGET_STATES


# Supports:
# - attack.php?XID=123
# - profiles.php?XID=123
# - anything with ?id=123 / ?userid=123 / ?user=123 / ?xid=123
_ID_RE = re.compile(r"(?:[?&](?:XID|xid|user|userid|id)=)(\d+)")


def extract_user_id(url: str) -> Optional[int]:
    m = _ID_RE.search(url)
    if not m:
        return None
    try:
        uid = int(m.group(1))
        return uid if uid > 0 else None
    except Exception:
        return None


@dataclass(frozen=True)
class TargetCandidate:
    user_id: int
    url: str


def iter_candidates(links: Iterable[str]) -> list[TargetCandidate]:
    out: list[TargetCandidate] = []
    for url in links:
        uid = extract_user_id(url)
        if uid:
            out.append(TargetCandidate(user_id=uid, url=url))
    return out


def is_blocked_state(state: Optional[str]) -> bool:
    if not state:
        return True
    return state in DISALLOWED_TARGET_STATES


class TargetPicker:
    """
    Picks the first target (in configured order) who is not in a blocked status state.
    Caches result briefly to avoid hammering the API during repeated alerts.
    """

    def __init__(self, cache_ttl_seconds: int = 60):
        self.cache_ttl_seconds = int(cache_ttl_seconds)
        self._cached: Optional[TargetCandidate] = None
        self._cached_at: int = 0

    async def pick_first_available(self) -> Optional[TargetCandidate]:
        now = int(time.time())

        # Serve cached selection
        if self._cached and (now - self._cached_at) <= self.cache_ttl_seconds:
            return self._cached

        # Walk in order and return first available
        for c in iter_candidates(EASY_TARGET_ATTACK_LINKS):
            try:
                status = await torn_api.fetch_user_status(c.user_id)
                state = status.get("state")
                if not is_blocked_state(state):
                    self._cached = c
                    self._cached_at = now
                    return c
            except Exception:
                # Treat failure as "unavailable"
                continue

        # Cache miss briefly too (prevents rapid re-check loops)
        self._cached = None
        self._cached_at = now
        return None
