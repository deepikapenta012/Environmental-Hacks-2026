"""User-triggered, cached location lookup for claim transport addresses."""

from __future__ import annotations

import json
import time
from threading import Lock
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.config import get_settings

_CACHE: dict[str, list[dict[str, float | str]]] = {}
_LOCK = Lock()
_LAST_REQUEST_AT = 0.0
_MIN_REQUEST_INTERVAL_SECONDS = 1.1
_CACHE_LIMIT = 512


def find_locations(query: str) -> list[dict[str, float | str]]:
    """Return up to five matching places, querying only on explicit user action."""
    global _LAST_REQUEST_AT

    normalized = " ".join(query.split()).casefold()
    with _LOCK:
        cached = _CACHE.get(normalized)
        if cached is not None:
            return cached

        wait_seconds = _MIN_REQUEST_INTERVAL_SECONDS - (time.monotonic() - _LAST_REQUEST_AT)
        if wait_seconds > 0:
            time.sleep(wait_seconds)

        settings = get_settings()
        params = urlencode({"q": query, "format": "jsonv2", "limit": 5})
        request = Request(
            f"{settings.geocoding_search_url}?{params}",
            headers={
                "Accept": "application/json",
                "User-Agent": "E-Waste-ChainGuard/1.0 (local development)",
            },
        )
        _LAST_REQUEST_AT = time.monotonic()
        try:
            with urlopen(request, timeout=8) as response:
                places = json.loads(response.read().decode("utf-8"))
        except (URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise RuntimeError("Location lookup is temporarily unavailable") from exc

        results = []
        if isinstance(places, list):
            for place in places:
                try:
                    latitude = float(place["lat"])
                    longitude = float(place["lon"])
                    label = str(place["display_name"])
                except (KeyError, TypeError, ValueError):
                    continue
                if -90 <= latitude <= 90 and -180 <= longitude <= 180 and label:
                    results.append({
                        "latitude": latitude,
                        "longitude": longitude,
                        "label": label,
                    })

        if len(_CACHE) >= _CACHE_LIMIT:
            _CACHE.pop(next(iter(_CACHE)))
        _CACHE[normalized] = results
        return results
