"""
Local development settings.
"""

from .base import *  # noqa: F401, F403
from .base import REST_FRAMEWORK, env

DEBUG = True

# Keep local defaults, then merge any hosts from .env (e.g. ngrok for Shopify OAuth).
_local_hosts = ["localhost", "127.0.0.1", "[::1]"]
_env_hosts = env("ALLOWED_HOSTS", default=[])
ALLOWED_HOSTS = list(dict.fromkeys([*_local_hosts, *_env_hosts]))

CORS_ALLOW_ALL_ORIGINS = True
# Chrome Private Network Access preflight (localhost page → 127.0.0.1 API).
CORS_ALLOW_PRIVATE_NETWORK = True

REST_FRAMEWORK = {
    **REST_FRAMEWORK,
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ],
}

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Run tasks inline during unit tests / when Redis is unavailable
# Set CELERY_TASK_ALWAYS_EAGER=False in .env when using a real worker.
if env("CELERY_TASK_ALWAYS_EAGER", default=False):
    CELERY_TASK_ALWAYS_EAGER = True
