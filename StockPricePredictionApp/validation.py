"""Strict server-side validation for every external input.

Nothing in this module trusts the browser. All values are treated as hostile,
length-limited and matched against an allowlist before they reach services,
filesystem paths or outbound HTTP providers.
"""

from __future__ import annotations

import re
from datetime import date

SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9._^-]{0,19}$")
SEARCH_RE = re.compile(r"^[A-Za-z0-9 .,&'\"()/_-]{0,80}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DOWNLOAD_IDS = {"0", "1", "2", "history", "3", "prediction", "4"}


class InputError(ValueError):
    """Raised when user-controlled input fails validation."""


def clean_symbol(raw, default: str | None = None, required: bool = False) -> str:
    text = str(raw or "").strip().upper()
    if not text:
        if required:
            raise InputError("A stock symbol is required.")
        return default or ""
    if not SYMBOL_RE.fullmatch(text):
        raise InputError("Invalid stock symbol.")
    return text


def clean_search(raw, default: str = "", max_length: int = 80) -> str:
    text = str(raw or "").strip()
    if len(text) > max_length or (text and not SEARCH_RE.fullmatch(text)):
        raise InputError("Invalid search query.")
    return text or default


def clean_int(raw, field: str, default: int, minimum: int, maximum: int) -> int:
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise InputError(f"Invalid {field}.") from exc
    if not minimum <= value <= maximum:
        raise InputError(f"{field} must be between {minimum} and {maximum}.")
    return value


def clean_date(raw, field: str, default: str | None = None) -> str:
    if raw is None or raw == "":
        if default is not None:
            return default
        return ""
    text = str(raw).strip()
    if not DATE_RE.fullmatch(text):
        raise InputError(f"Invalid {field} date.")
    try:
        date.fromisoformat(text)
    except ValueError as exc:
        raise InputError(f"Invalid {field} date.") from exc
    return text


def clean_download_id(raw, default: str = "4") -> str:
    text = str(raw or "").strip()
    return text if text in DOWNLOAD_IDS else default


def clean_symbols(raw, max_items: int = 50) -> list[str]:
    if isinstance(raw, str):
        parts = raw.split(",")
    elif isinstance(raw, (list, tuple)):
        parts = list(raw)
    elif raw is None:
        parts = []
    else:
        raise InputError("Invalid symbols list.")
    cleaned: list[str] = []
    for part in parts:
        if len(cleaned) >= max_items:
            break
        symbol = clean_symbol(part)
        if symbol and symbol not in cleaned:
            cleaned.append(symbol)
    return cleaned
