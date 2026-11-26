"""Security middleware, rate limiting and log redaction for StockSight.

The app is intentionally account-free, so controls focus on the real attack
surface: public pages, JSON APIs, provider-backed endpoints and the filesystem.
"""

from __future__ import annotations

import json
import logging
import re
import secrets
import time
from functools import wraps

from django.conf import settings
from django.core.cache import cache
from django.http import JsonResponse

security_logger = logging.getLogger("stocksight.security")

_SENSITIVE = re.compile(
    r"(?i)(password|passwd|secret|token|api[_-]?key|authorization|cookie|csrf)"
    r"\s*[:=]\s*['\"]?[^,\s;]+"
)


class StructuredFormatter(logging.Formatter):
    """Emit one JSON object per log line for platform log aggregation."""

    def format(self, record: logging.LogRecord) -> str:
        return json.dumps({
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }, ensure_ascii=False, default=str)


class SensitiveDataFilter(logging.Filter):
    """Redact credential-shaped substrings from every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = _SENSITIVE.sub(lambda m: m.group(0).split(":", 1)[0].split("=", 1)[0] + "=[REDACTED]", message)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True


class SecurityHeadersMiddleware:
    """Apply nonce-based CSP and defence-in-depth response headers."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        nonce = secrets.token_urlsafe(18)
        request.csp_nonce = nonce
        response = self.get_response(request)

        script_src = "'self' 'nonce-%s'" % nonce
        # Inline style attributes are used by the existing UI for animation
        # delays. A nonce would disable 'unsafe-inline', so scripts get the
        # nonce while styles are limited to self + inline (no remote CSS).
        style_src = "'self' 'unsafe-inline'"
        csp = (
            "default-src 'self'; "
            f"script-src {script_src}; "
            f"style-src {style_src}; "
            "img-src 'self' data:; "
            "font-src 'self' data:; "
            "connect-src 'self'; "
            "media-src 'none'; object-src 'none'; "
            "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
        response.setdefault("Content-Security-Policy", csp)
        response.setdefault("X-Content-Type-Options", "nosniff")
        response.setdefault("X-Frame-Options", "DENY")
        response.setdefault("Referrer-Policy", "same-origin")
        response.setdefault(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=(), payment=(), usb=(), fullscreen=(self)",
        )
        response.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        response.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        if not settings.DEBUG and request.is_secure():
            response.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains; preload",
            )
        return response


def _client_ip(request) -> str:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    return request.META.get("REMOTE_ADDR", "unknown")[:64]


def rate_limit(scope: str, limit: int, window: int = 60):
    """Per-IP, per-endpoint quota backed by the configured Django cache.

    With the default locmem cache this is per-process; the single-worker
    production image is covered. For multi-worker deployments, configure a
    shared Redis cache (see Readme.md).
    """

    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if not getattr(settings, "RATE_LIMIT_ENABLED", True):
                return view(request, *args, **kwargs)
            key = f"rl:{scope}:{_client_ip(request)}"
            now = int(time.time())
            state = cache.get(key)
            if not isinstance(state, tuple) or now >= state[1]:
                state = (0, now + window)
            count = state[0] + 1
            ttl = max(1, state[1] - now)
            cache.set(key, (count, state[1]), ttl)
            remaining = max(0, limit - count)
            if count > limit:
                security_logger.warning(
                    "rate_limit_denied scope=%s ip=%s count=%s limit=%s",
                    scope, _client_ip(request), count, limit,
                )
                response = JsonResponse(
                    {"ok": False, "error": "Rate limit exceeded. Try again shortly."},
                    status=429,
                )
                response["Retry-After"] = str(ttl)
                return response
            response = view(request, *args, **kwargs)
            response["X-RateLimit-Limit"] = str(limit)
            response["X-RateLimit-Remaining"] = str(remaining)
            return response

        return wrapped

    return decorator
