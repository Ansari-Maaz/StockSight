"""Cheap, cached globals injected into every template."""

from __future__ import annotations

import time
from datetime import datetime, timezone

from django.conf import settings

from .services import data as data_service

_CACHE: dict = {}
_TTL = 60


def market_context(request):
    now = time.time()
    cached = _CACHE.get("status")
    if not cached or now - cached[0] > _TTL:
        status = data_service.status()
        cached = (now, {
            "symbol_count": status["symbol_count"],
            "stale_count": sum(1 for s in status["symbols"] if s["stale"]),
            "newest_date": max((s["last_date"] for s in status["symbols"] if s["last_date"]), default=None),
            "data_dir": status["data_dir"],
        })
        _CACHE["status"] = cached
    return {
        "market": cached[1],
        "app_name": getattr(settings, "APP_NAME", "StockSight"),
        "rendered_at": datetime.now(timezone.utc).strftime("%d %b %Y %H:%M UTC"),
        "csp_nonce": getattr(request, "csp_nonce", ""),
    }
