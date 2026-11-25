"""Lightweight, explainable headline-tone summary.

This is deliberately keyword-based: it gives a quick "news pulse" alongside the
headlines themselves, not a trading signal. No model or network call is needed.
"""

from __future__ import annotations

import re

_POSITIVE = (
    "beat", "beats", "beating", "upgrade", "upgrades", "upside", "surge", "surges",
    "rally", "rallies", "growth", "grows", "strong", "strength", "gain", "gains",
    "rise", "rises", "record", "outperform", "bullish", "soar", "soars", "jump",
    "jumps", "profit", "profits", "raises", "rebound", "wins", "approval", "boost",
)

_NEGATIVE = (
    "miss", "misses", "missing", "downgrade", "downgrades", "downside", "fall",
    "falls", "plunge", "plunges", "slump", "slumps", "weak", "weakness", "loss",
    "losses", "risk", "risks", "concern", "concerns", "sell", "underperform",
    "bearish", "drop", "drops", "cuts", "lawsuit", "outage", "decline", "declines",
    "overvalued", "slowdown", "warning", "warns", "probe", "fraud", "bankruptcy",
)

_POS_RE = re.compile(r"\b(?:" + "|".join(_POSITIVE) + r")\w*\b", re.I)
_NEG_RE = re.compile(r"\b(?:" + "|".join(_NEGATIVE) + r")\w*\b", re.I)


def score(articles) -> dict | None:
    """Return headline tone counts for a list of news article dicts."""
    rows = [a for a in (articles or []) if isinstance(a, dict) and a.get("title")]
    if not rows:
        return None

    positive = sum(1 for a in rows if _POS_RE.search(a["title"]))
    negative = sum(1 for a in rows if _NEG_RE.search(a["title"]))
    if positive > negative:
        label = "Bullish"
        css = "buy"
    elif negative > positive:
        label = "Bearish"
        css = "sell"
    else:
        label = "Neutral"
        css = "neutral"
    return {
        "label": label,
        "css": css,
        "positive": positive,
        "negative": negative,
        "total": len(rows),
    }
