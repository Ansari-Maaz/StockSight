"""Django settings for the StockSight project.

Configuration is environment-driven so the same code runs locally and in
production (gunicorn/Docker). See .env.example and Readme.md.
"""

from pathlib import Path
import os

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent


def env(key, default=None, cast=str):
    value = os.environ.get(key, default)
    if value is None or value == "":
        return default
    try:
        return cast(value)
    except (TypeError, ValueError) as exc:
        raise ImproperlyConfigured(f"Invalid value for {key}: {value}") from exc


DEBUG = env("DJANGO_DEBUG", "True").lower() in ("1", "true", "yes")
SECRET_KEY = env("DJANGO_SECRET_KEY", "django-insecure-dev-only-change-me")
if not DEBUG and (SECRET_KEY == "django-insecure-dev-only-change-me" or len(SECRET_KEY) < 32):
    raise ImproperlyConfigured(
        "DJANGO_SECRET_KEY must be set to a unique random value of at least 32 characters "
        "when DEBUG is disabled."
    )
ALLOWED_HOSTS = [h for h in env("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h]
if not DEBUG and "*" in ALLOWED_HOSTS:
    raise ImproperlyConfigured(
        "DJANGO_ALLOWED_HOSTS may not be '*' in production; list the exact hostnames."
    )

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "StockPricePredictionApp",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "StockPricePrediction.security.SecurityHeadersMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "StockPricePrediction.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "StockPricePredictionApp" / "template"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "StockPricePredictionApp.context_processors.market_context",
            ],
        },
    },
]

WSGI_APPLICATION = "StockPricePrediction.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": env("DB_ENGINE", "django.db.backends.sqlite3"),
        "NAME": env("DB_NAME", str(BASE_DIR / "db.sqlite3")),
    }
}

# Rate-limit counter store. LocMem is per-process and sufficient for the
# single-worker image; set REDIS_URL in Readme.md for multi-worker deployments.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "stocksight-ratelimits",
        "OPTIONS": {"MAX_ENTRIES": 10000},
    }
}
RATE_LIMIT_ENABLED = env("RATE_LIMIT_ENABLED", "True").lower() in ("1", "true", "yes")

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# --------------------------------------------------------------------------- #
# Static assets and application data
# --------------------------------------------------------------------------- #
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "StockPricePrediction.storage.LenientCompressedManifestStaticFilesStorage"
    },
}

# Keep hashing/compression, but don't fail a deploy when an optional vendored
# file (for example a source map) is missing.
WHITENOISE_MANIFEST_STRICT = False

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

APP_NAME = "StockSight"
MARKET_DATA_DIR = Path(env("MARKET_DATA_DIR", str(BASE_DIR / "data" / "market")))
MARKET_UNIVERSE_CSV = Path(env("MARKET_UNIVERSE_CSV", str(BASE_DIR / "all_stockss.csv")))
MARKET_REFRESH_TTL_HOURS = env("MARKET_REFRESH_TTL_HOURS", "1", float)
NEWS_DIR = Path(env("NEWS_DIR", str(BASE_DIR / "data" / "news")))
NEWS_TTL_HOURS = env("NEWS_TTL_HOURS", "6", float)

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Production hardening - only active when DEBUG is off.
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = env("SECURE_SSL_REDIRECT", "False").lower() in ("1", "true", "yes")
    CSRF_TRUSTED_ORIGINS = [o.strip() for o in env("CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()]
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    X_FRAME_OPTIONS = "DENY"
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = "same-origin"
    SECURE_HSTS_SECONDS = env("HSTS_SECONDS", "31536000", int)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "redact": {"()": "StockPricePrediction.security.SensitiveDataFilter"},
    },
    "formatters": {
        "standard": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"},
        "structured": {"()": "StockPricePrediction.security.StructuredFormatter"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "structured",
            "filters": ["redact"],
        },
    },
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
    "loggers": {
        "django.request": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "StockPricePredictionApp": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO"),
                                    "propagate": False},
        "stocksight.security": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}
