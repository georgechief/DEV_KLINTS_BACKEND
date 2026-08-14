"""
Production settings.
"""

from .base import *  # noqa: F401, F403
from .base import ALLOWED_HOSTS as _ALLOWED_HOSTS
from .base import CSRF_TRUSTED_ORIGINS as _CSRF_TRUSTED_ORIGINS
from .base import env

DEBUG = False

# Always accept the public API hostname (avoids DisallowedHost 400 when .env lags DNS).
API_DOMAIN = env("API_DOMAIN", default="apis.klints.io")
ALLOWED_HOSTS = list(_ALLOWED_HOSTS)
if API_DOMAIN and API_DOMAIN not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(API_DOMAIN)
for _host in ("localhost", "127.0.0.1"):
    if _host not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(_host)

CSRF_TRUSTED_ORIGINS = list(_CSRF_TRUSTED_ORIGINS)
_api_origin = f"https://{API_DOMAIN}"
if API_DOMAIN and _api_origin not in CSRF_TRUSTED_ORIGINS:
    CSRF_TRUSTED_ORIGINS.append(_api_origin)

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
# Enabled via .env once nginx terminates TLS for apis.klints.io.
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=False)
SESSION_COOKIE_SECURE = env.bool("SESSION_COOKIE_SECURE", default=False)
CSRF_COOKIE_SECURE = env.bool("CSRF_COOKIE_SECURE", default=False)
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=0)
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

CORS_ALLOW_ALL_ORIGINS = False

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": env("REDIS_URL", default="redis://127.0.0.1:6379/1"),
    }
}

CELERY_TASK_ALWAYS_EAGER = False