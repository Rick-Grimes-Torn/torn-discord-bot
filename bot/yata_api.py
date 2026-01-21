import time
from typing import Any, Dict, Optional, Tuple, List

import aiohttp

YATA_TRAVEL_EXPORT_URL = "https://yata.yt/api/v1/travel/export/"

# In-memory cache (keep tiny; resets on restart)
_yata_export_cache: Dict[str, Any] = {
    "payload": None,
    "fetched_at": 0,
}

DEFAULT_YATA_CACHE_TTL_SECONDS = 60  # keep small; YATA already caches server-side


class YataError(RuntimeError):
    pass


async def yata_get_json(url: str, timeout_seconds: float = 15.0) -> dict:
    timeout_obj = aiohttp.ClientTimeout(total=float(timeout_seconds))
    headers = {"User-Agent": "discord-torn-bot"}

    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, timeout=timeout_obj) as resp:
            # YATA returns JSON; allow unknown content type just in case
            data = await resp.json(content_type=None)

    if isinstance(data, dict) and "error" in data:
        # YATA error format documented in their API page
        # {'error': {'error': 'message', 'code': N}}
        err = data.get("error") or {}
        if isinstance(err, dict):
            raise YataError(f"YATA error {err.get('code')}: {err.get('error')}")
        raise YataError(f"YATA error: {err}")

    if not isinstance(data, dict):
        raise YataError("Unexpected YATA response (not a JSON object).")
    return data


def _safe_int(v, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return default


def _safe_str(v) -> str:
    return v if isinstance(v, str) else str(v) if v is not None else ""


def country_name(code: str) -> str:
    # Country keys are documented by YATA
    # mex, cay, can, haw, uni, arg, swi, jap, chi, uae, sou :contentReference[oaicite:1]{index=1}
    mapping = {
        "mex": "Mexico",
        "cay": "Cayman Islands",
        "can": "Canada",
        "haw": "Hawaii",
        "uni": "United Kingdom",
        "arg": "Argentina",
        "swi": "Switzerland",
        "jap": "Japan",
        "chi": "China",
        "uae": "UAE",
        "sou": "South Africa",
    }
    return mapping.get(code.lower(), code.lower())


def normalize_export_payload(payload: dict) -> Dict[str, Any]:
    """
    Normalizes YATA travel export payload into a stable structure:
    {
      "timestamp": int,
      "stocks": {
        "mex": {"update": int, "stocks": [{"id":int,"name":str,"quantity":int,"cost":int}, ...]},
        ...
      }
    }
    """
    if not isinstance(payload, dict):
        raise YataError("Export payload not a dict.")

    ts = _safe_int(payload.get("timestamp"), 0)
    stocks = payload.get("stocks") or {}
    if not isinstance(stocks, dict):
        raise YataError("Export payload missing 'stocks' object.")

    out_stocks: Dict[str, Any] = {}
    for code, block in stocks.items():
        if not isinstance(block, dict):
            continue
        upd = _safe_int(block.get("update"), 0)
        items = block.get("stocks") or []
        if not isinstance(items, list):
            items = []

        norm_items: List[Dict[str, Any]] = []
        for it in items:
            if not isinstance(it, dict):
                continue
            norm_items.append(
                {
                    "id": _safe_int(it.get("id"), 0),
                    "name": _safe_str(it.get("name")),
                    "quantity": _safe_int(it.get("quantity"), 0),
                    "cost": _safe_int(it.get("cost"), 0),
                }
            )

        out_stocks[str(code).lower()] = {
            "update": upd,
            "stocks": norm_items,
        }

    return {"timestamp": ts, "stocks": out_stocks}


async def get_travel_export_cached(ttl_seconds: int = DEFAULT_YATA_CACHE_TTL_SECONDS) -> Dict[str, Any]:
    """
    Fetches YATA export stocks with a short TTL cache.
    IMPORTANT: Call the exact URL with no query params to benefit from YATA caching. :contentReference[oaicite:2]{index=2}
    """
    now = int(time.time())
    cached_payload = _yata_export_cache.get("payload")
    fetched_at = _safe_int(_yata_export_cache.get("fetched_at"), 0)

    if cached_payload and (now - fetched_at) <= int(ttl_seconds):
        return cached_payload

    raw = await yata_get_json(YATA_TRAVEL_EXPORT_URL)
    norm = normalize_export_payload(raw)

    _yata_export_cache["payload"] = norm
    _yata_export_cache["fetched_at"] = now
    return norm
