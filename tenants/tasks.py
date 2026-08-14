from celery import shared_task
from django.utils import timezone


@shared_task(name="tenants.deactivate_inactive")
def deactivate_inactive_tenants(days_inactive: int = 90):
    """
    Example maintenance task: mark tenants inactive after prolonged inactivity.

    Hook real activity signals later; this is a scaffold stub.
    """
    from datetime import timedelta

    from tenants.models import Tenant

    cutoff = timezone.now() - timedelta(days=days_inactive)
    updated = Tenant.objects.filter(
        is_active=True,
        updated_at__lt=cutoff,
    ).update(is_active=False)
    return {"deactivated": updated, "cutoff": cutoff.isoformat()}
