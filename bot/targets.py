import re
import time
from dataclasses import dataclass
from typing import Iterable, Optional

from . import torn_api
from .config import EASY_TARGET_ATTACK_LINKS, DISALLOWED_TARGET_STATES


# Supports:
# - loader.php?sid=attack&user2ID=123
# - profiles.php?XID=123
# - attack.php?XID=123
# - and common variants
_ID_RE = re.compile(
    r"(?:[?&])"
    r"(?:XID|xid|user2ID|user2id|userID|userid|user|id|target|targetID|targetId)"
    r"=(\d+)"
)


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
    Caches briefly to avoid hammering the API.
    Stores last_error for debugging.
    """

    def __init__(self, cache_ttl_seconds: int = 60):
        self.cache_ttl_seconds = int(cache_ttl_seconds)
        self._cached: Optional[TargetCandidate] = None
        self._cached_at: int = 0
        self.last_error: Optional[str] = None

    async def pick_first_available(self) -> Optional[TargetCandidate]:
        now = int(time.time())

        if self._cached and (now - self._cached_at) <= self.cache_ttl_seconds:
            return self._cached

        self.last_error = None
        candidates = iter_candidates(EASY_TARGET_ATTACK_LINKS)

        if not candidates:
            self.last_error = "No IDs extracted from EASY_TARGET_ATTACK_LINKS (check link formats)."
            self._cached = None
            self._cached_at = now
            return None

        for c in candidates:
            try:
                status = await torn_api.fetch_user_status(c.user_id)
                state = status.get("state")
                if not is_blocked_state(state):
                    self._cached = c
                    self._cached_at = now
                    return c
            except Exception as e:
                self.last_error = f"{type(e).__name__}: {e}"
                continue

        self._cached = None
        self._cached_at = now
        return None
