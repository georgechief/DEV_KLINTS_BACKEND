"""
Base settings shared across all environments.
"""

from pathlib import Path
from zoneinfo import ZoneInfo

import environ
from django_celery_beat.tzcrontab import TzAwareCrontab

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, []),
    CORS_ALLOWED_ORIGINS=(list, []),
    CSRF_TRUSTED_ORIGINS=(list, []),
    CELERY_TASK_ALWAYS_EAGER=(bool, False),
    WRITEBACKS_ENABLED=(bool, False),
    WRITEBACK_CHECK_ALLOWLIST=(list, []),
    WRITEBACK_SANDBOX_COMPANY_IDS=(list, []),
    WRITEBACK_SANDBOX_MAX_ROWS=(int, 10),
    WRITEBACK_DEFAULT_BATCH_SIZE=(int, 25),
    WRITEBACK_PARTIAL_ROLLBACK_MINUTES=(int, 15),
    WRITEBACK_APPROVAL_TTL_MINUTES=(int, 60),
    AI_ENABLED=(bool, False),
    AI_PROVIDER=(str, "mock"),
    AI_JSON_MAX_RETRIES=(int, 3),
    AI_CALL_TIMEOUT_SECONDS=(float, 30.0),
    AI_TEMPERATURE=(float, 0.3),
)

environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY")

DEBUG = env("DEBUG")

ALLOWED_HOSTS = env("ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = env("CSRF_TRUSTED_ORIGINS")

DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "rest_framework_simplejwt",
    "corsheaders",
    "django_celery_beat",
    "django_celery_results",
]

LOCAL_APPS = [
    "core.apps.CoreConfig",
    "tenants.apps.TenantsConfig",
    "dataruns.apps.DatarunsConfig",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "core.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "core.wsgi.application"
ASGI_APPLICATION = "core.asgi.application"

DATABASES = {
    "default": env.db(
        "DATABASE_URL",
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
    )
}

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
    },
}

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "tenants.User"

REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 25,
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
}

CORS_ALLOWED_ORIGINS = env("CORS_ALLOWED_ORIGINS")
# Needed so the Overview export can read `filename="klints-assessment-….pdf"`.
CORS_EXPOSE_HEADERS = ["Content-Disposition"]

# ---------------------------------------------------------------------------
# Celery / Redis
# ---------------------------------------------------------------------------
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default="redis://127.0.0.1:6379/0")
CELERY_RESULT_BACKEND = env(
    "CELERY_RESULT_BACKEND",
    default="django-db",
)
CELERY_CACHE_BACKEND = "default"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = env.int("CELERY_TASK_TIME_LIMIT", default=30 * 60)
CELERY_TASK_SOFT_TIME_LIMIT = env.int("CELERY_TASK_SOFT_TIME_LIMIT", default=25 * 60)
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_ALWAYS_EAGER = env("CELERY_TASK_ALWAYS_EAGER")
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"
CELERY_RESULT_EXTENDED = True

# Periodic setup tasks (also editable in Admin via django-celery-beat)
CELERY_BEAT_SCHEDULE = {
    "core-ping-every-5-minutes": {
        "task": "core.ping",
        "schedule": 300.0,
    },
    "dcs-daily-score-1500-ist": {
        "task": "dataruns.dispatch_daily_dcs_scores",
        # 15:00 Asia/Kolkata (IST, UTC+5:30, no DST). Celery 5.6 crontab has no tz= kwarg;
        # django-celery-beat TzAwareCrontab syncs to Admin with timezone Asia/Kolkata.
        "schedule": TzAwareCrontab(hour=15, minute=0, tz=ZoneInfo("Asia/Kolkata")),
    },
}

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "klints-default",
    }
}

from datetime import timedelta

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=12),
    "AUTH_HEADER_TYPES": ("Bearer",),
}

CONNECTOR_FERNET_KEY = env("CONNECTOR_FERNET_KEY")
BOOTSTRAP_DAYS = env.int("BOOTSTRAP_DAYS", default=30)
FRONTEND_VERIFY_URL = env("FRONTEND_VERIFY_URL", default="http://localhost:8083/verify-email")
EMAIL_VERIFICATION_TTL_HOURS = env.int("EMAIL_VERIFICATION_TTL_HOURS", default=24)
FRONTEND_RESET_URL = env(
    "FRONTEND_RESET_URL",
    default="http://localhost:8082/reset-password",
)
PASSWORD_RESET_TTL_HOURS = env.int("PASSWORD_RESET_TTL_HOURS", default=24)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="noreply@klints.ai")

# Klints Mailer API (transactional email service)
MAILER_API_URL = env("MAILER_API_URL")
MAILER_API_TOKEN = env("MAILER_API_TOKEN")

# Shopify OAuth app credentials (per-app, not per-connector)
SHOPIFY_API_KEY = env("SHOPIFY_API_KEY", default="")
SHOPIFY_API_SECRET = env("SHOPIFY_API_SECRET", default="")
SHOPIFY_SCOPES = env(
    "SHOPIFY_SCOPES",
    default="read_orders,read_customers",
)
SHOPIFY_API_VERSION = env("SHOPIFY_API_VERSION", default="2026-01")
SHOPIFY_OAUTH_REDIRECT_URI = env(
    "SHOPIFY_OAUTH_REDIRECT_URI",
    default="http://localhost:8000/api/v1/connectors/shopify/callback/",
)
# Where the browser lands after the OAuth callback (integrations page by default;
# the start endpoint accepts a `return_to` override for the onboarding flow).
FRONTEND_SHOPIFY_REDIRECT_URL = env(
    "FRONTEND_SHOPIFY_REDIRECT_URL",
    default="http://localhost:8083/integrations",
)
# Data Consistency / DCS results page (PRD-DCS-01 email CTA).
FRONTEND_DCS_URL = env(
    "FRONTEND_DCS_URL",
    default="http://localhost:8083/dashboard",
)

FRONTEND_INVITE_URL = env(
    "FRONTEND_INVITE_URL",
    default="http://localhost:8083/invite/accept",
)
INVITE_TTL_DAYS = env.int("INVITE_TTL_DAYS", default=7)

# Email branding (logo must be a public HTTPS PNG/JPG — SVG is unreliable in clients)
FRONTEND_APP_ORIGIN = env("FRONTEND_APP_ORIGIN", default="")
EMAIL_LOGO_URL = env("EMAIL_LOGO_URL", default="")

# Manago.ai API (single production endpoint for all connectors)
MANAGO_API_BASE_URL = env(
    "MANAGO_API_BASE_URL",
    default="https://app2.manago.ai",
)

# Writeback adapter foundation (PRD-WB-01) — prod execute off by default.
WRITEBACKS_ENABLED = env("WRITEBACKS_ENABLED")
WRITEBACK_CHECK_ALLOWLIST = env("WRITEBACK_CHECK_ALLOWLIST")
WRITEBACK_SANDBOX_COMPANY_IDS = env("WRITEBACK_SANDBOX_COMPANY_IDS")
WRITEBACK_SANDBOX_MAX_ROWS = env("WRITEBACK_SANDBOX_MAX_ROWS")
WRITEBACK_DEFAULT_BATCH_SIZE = env("WRITEBACK_DEFAULT_BATCH_SIZE")
WRITEBACK_PARTIAL_ROLLBACK_MINUTES = env("WRITEBACK_PARTIAL_ROLLBACK_MINUTES")
WRITEBACK_APPROVAL_TTL_MINUTES = env("WRITEBACK_APPROVAL_TTL_MINUTES")
WRITEBACK_MANAGO_BATCH_MAX = 1000

# AI narrative layer (PRD-AI-01) — fail closed when disabled; mock needs no keys.
AI_ENABLED = env("AI_ENABLED")
AI_PROVIDER = env("AI_PROVIDER")
AI_PRIVACY_POLICY_VERSION = env(
    "AI_PRIVACY_POLICY_VERSION",
    default="privacy_gate.v1",
)
MISTRAL_MODEL = env("MISTRAL_MODEL", default="mistral-small-latest")
MISTRAL_API_KEY = env("MISTRAL_API_KEY", default="")
AI_JSON_MAX_RETRIES = env("AI_JSON_MAX_RETRIES")
AI_CALL_TIMEOUT_SECONDS = env("AI_CALL_TIMEOUT_SECONDS")
AI_TEMPERATURE = env("AI_TEMPERATURE")