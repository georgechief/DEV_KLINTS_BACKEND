from celery import shared_task
from django.utils import timezone


@shared_task(name="core.ping")
def ping():
    """Lightweight setup task to verify the worker + Redis broker."""
    return {
        "status": "pong",
        "checked_at": timezone.now().isoformat(),
    }


@shared_task(name="core.health_check")
def health_check():
    """Confirm Django settings and Celery can talk to Redis."""
    from django.conf import settings
    from django.core.cache import cache

    cache_ok = False
    try:
        cache.set("celery:health", "ok", timeout=30)
        cache_ok = cache.get("celery:health") == "ok"
    except Exception as exc:  # noqa: BLE001 — surface broker/cache issues in task result
        return {
            "status": "degraded",
            "cache_ok": False,
            "error": str(exc),
            "broker_url": settings.CELERY_BROKER_URL,
            "checked_at": timezone.now().isoformat(),
        }

    return {
        "status": "ok" if cache_ok else "degraded",
        "cache_ok": cache_ok,
        "broker_url": settings.CELERY_BROKER_URL,
        "checked_at": timezone.now().isoformat(),
    }
