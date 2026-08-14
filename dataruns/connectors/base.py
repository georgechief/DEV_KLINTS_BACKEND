"""Shared connector import helpers: workspace resolution, decrypt, run/snapshot creation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from dataruns.models import DataRun, Run, RunConnector
from tenants.crypto import SECRET_CONFIG_FIELDS, decrypt_api_key
from tenants.models import Company, Connector, ConnectorSnapshot, Tenant, User

CONNECTOR_FETCH_KIND = "connector_fetch"
CONNECTOR_BOOTSTRAP_KIND = "connector_bootstrap"


def resolve_tenant_from_user(user: User) -> Tenant:
    """Return the tenant for a JWT-authenticated user (PRD §6 step 1)."""
    return user.tenant


def resolve_company_from_user(user: User) -> Company | None:
    """Return the company (workspace) for a JWT-authenticated user (PRD §1, §6 step 1)."""
    return (
        Company.objects.filter(tenant_id=user.tenant_id)
        .order_by("created_at")
        .first()
    )


def get_connector(*, company: Company, platform: str) -> Connector:
    """Load the connected connector for a company and platform (PRD §6 step 2)."""
    return Connector.objects.get(company=company, name=platform)


def resolve_company_from_data_run(data_run: DataRun) -> Company:
    """Resolve workspace from a pre-created connector DataRun (PRD-CONN-01 §4 B)."""
    company_id = (data_run.metadata or {}).get("company_id")
    if not company_id:
        raise ValueError("DataRun metadata is missing company_id.")
    return Company.objects.get(pk=company_id)


def resolve_bootstrap_days_from_data_run(data_run: DataRun) -> int:
    """Return the enqueue-time fetch window stored on a bootstrap DataRun (PRD §4 B)."""
    days = (data_run.metadata or {}).get("days")
    if not isinstance(days, int) or isinstance(days, bool):
        raise ValueError("DataRun metadata is missing days.")
    if days < 1 or days > 31:
        raise ValueError("days must be between 1 and 31")
    return days


def decrypt_connector_config(config: dict[str, Any]) -> dict[str, Any]:
    """Decrypt secret connector config fields (PRD §6 step 3)."""
    decrypted = dict(config)
    for field in SECRET_CONFIG_FIELDS:
        value = decrypted.get(field)
        if isinstance(value, str) and value:
            decrypted[field] = decrypt_api_key(value)
    return decrypted


def create_connector_data_run(
    *,
    user: User | None = None,
    platform: str,
    days: int,
    company: Company,
    kind: str = CONNECTOR_FETCH_KIND,
    connector_id: str | None = None,
    triggered_by: str | None = None,
    actor_user_id: str | None = None,
) -> DataRun:
    """Create a DataRun at the start of connector import (PRD §6b, PRD-CONN-01 §4 B)."""
    if kind == CONNECTOR_BOOTSTRAP_KIND:
        if not connector_id:
            raise ValueError("connector_id is required for bootstrap DataRun.")
        return DataRun.objects.create(
            tenant=company.tenant,
            name=f"connector-bootstrap:{platform}",
            status=DataRun.Status.PENDING,
            metadata={
                "kind": CONNECTOR_BOOTSTRAP_KIND,
                "platform": platform,
                "connector_id": connector_id,
                "days": days,
                "triggered_by": triggered_by or "on_connect",
                "actor_user_id": actor_user_id,
                "company_id": str(company.id),
            },
        )

    if user is None:
        raise ValueError("user is required for connector fetch DataRun.")
    return DataRun.objects.create(
        tenant=user.tenant,
        name=f"connector-fetch:{platform}",
        status=DataRun.Status.RUNNING,
        started_at=timezone.now(),
        metadata={
            "kind": CONNECTOR_FETCH_KIND,
            "platform": platform,
            "days": days,
            "company_id": str(company.id),
        },
    )


@dataclass(frozen=True)
class BootstrapEnqueueResult:
    """Result of enqueueing (or reusing) an on-connect bootstrap DataRun."""

    data_run: DataRun
    task_queued: bool


def find_active_bootstrap_data_run(
    *,
    company: Company,
    connector: Connector,
) -> DataRun | None:
    """
    Return an active bootstrap DataRun for (company_id, connector.name), if any.

    PRD-CONN-01 §3 idempotency: one active bootstrap per company + connector name.
    """
    return (
        DataRun.objects.filter(
            name=f"connector-bootstrap:{connector.name}",
            status__in=[DataRun.Status.PENDING, DataRun.Status.RUNNING],
            metadata__kind=CONNECTOR_BOOTSTRAP_KIND,
            metadata__company_id=str(company.id),
            metadata__platform=connector.name,
        )
        .order_by("-created_at")
        .first()
    )


def supersede_active_bootstrap_data_runs(
    *,
    company: Company,
    connector: Connector,
    reason: str = "credentials_changed",
) -> int:
    """
    Mark active bootstrap DataRuns terminal so a fresh bootstrap can run.

    Used when connector credentials change (e.g. Shopify OAuth reconnect) while a
    prior bootstrap is still pending or running.
    """
    now = timezone.now()
    active_runs = DataRun.objects.filter(
        name=f"connector-bootstrap:{connector.name}",
        status__in=[DataRun.Status.PENDING, DataRun.Status.RUNNING],
        metadata__kind=CONNECTOR_BOOTSTRAP_KIND,
        metadata__company_id=str(company.id),
        metadata__platform=connector.name,
    )
    superseded_count = 0
    for data_run in active_runs:
        metadata = data_run.metadata or {}
        data_run.status = DataRun.Status.FAILED
        data_run.finished_at = now
        data_run.metadata = {
            **metadata,
            "superseded": True,
            "superseded_reason": reason,
            "error": "Bootstrap superseded by connector credential update.",
        }
        data_run.save(update_fields=["status", "finished_at", "metadata", "updated_at"])
        superseded_count += 1
    return superseded_count


def bootstrap_data_run_may_persist(data_run: DataRun) -> bool:
    """
    Return True when import terminal writes are allowed for this DataRun.

    Non-bootstrap imports always return True. Bootstrap imports may persist
    only while the worker still owns a non-superseded RUNNING run.
    """
    metadata = data_run.metadata or {}
    if metadata.get("kind") != CONNECTOR_BOOTSTRAP_KIND:
        return True
    data_run.refresh_from_db()
    metadata = data_run.metadata or {}
    if metadata.get("superseded"):
        return False
    return data_run.status == DataRun.Status.RUNNING


def bootstrap_data_run_was_superseded(data_run: DataRun) -> bool:
    """Return True when a bootstrap DataRun was cancelled by credential reconnect."""
    metadata = data_run.metadata or {}
    if metadata.get("kind") != CONNECTOR_BOOTSTRAP_KIND:
        return False
    data_run.refresh_from_db()
    return bool((data_run.metadata or {}).get("superseded"))


def find_latest_bootstrap_data_run(
    *,
    company: Company,
    connector: Connector,
) -> DataRun | None:
    """
    Return the most recent bootstrap DataRun for (company_id, connector.name).

    PRD-CONN-01 §8.3 — used by the bootstrap status API (read-only).
    """
    return (
        DataRun.objects.filter(
            name=f"connector-bootstrap:{connector.name}",
            metadata__kind=CONNECTOR_BOOTSTRAP_KIND,
            metadata__company_id=str(company.id),
            metadata__platform=connector.name,
        )
        .order_by("-created_at")
        .first()
    )


def enqueue_connector_bootstrap(
    *,
    company: Company,
    connector: Connector,
    triggered_by: str = "on_connect",
    actor_user_id: str | None = None,
    days: int | None = None,
    supersede_existing: bool = False,
) -> BootstrapEnqueueResult:
    """
    Enqueue on-connect bootstrap idempotently (PRD-CONN-01 §4 B–C, §3).

    If a bootstrap DataRun is already pending or running for this company and
    connector name, returns it without creating a duplicate or re-enqueueing.

    When ``supersede_existing`` is True (Shopify OAuth reconnect), any active
    bootstrap is marked failed first so the new run uses updated credentials.
    """
    if supersede_existing:
        supersede_active_bootstrap_data_runs(
            company=company,
            connector=connector,
            reason="credentials_changed",
        )

    existing = find_active_bootstrap_data_run(company=company, connector=connector)
    if existing is not None:
        return BootstrapEnqueueResult(data_run=existing, task_queued=False)

    bootstrap_days = days if days is not None else settings.BOOTSTRAP_DAYS
    data_run = create_connector_data_run(
        company=company,
        platform=connector.name,
        days=bootstrap_days,
        kind=CONNECTOR_BOOTSTRAP_KIND,
        connector_id=str(connector.id),
        triggered_by=triggered_by,
        actor_user_id=actor_user_id,
    )

    from dataruns.tasks import bootstrap_connector_fetch

    data_run_id = data_run.id

    def _enqueue() -> None:
        bootstrap_connector_fetch.delay(data_run_id)

    # Real workers: wait for the connecting request to commit so the connector
    # row is visible. Eager/test mode: run immediately (TestCase wraps tests
    # in a transaction where on_commit would not fire in time).
    if settings.CELERY_TASK_ALWAYS_EAGER:
        _enqueue()
    else:
        transaction.on_commit(_enqueue)
    return BootstrapEnqueueResult(data_run=data_run, task_queued=True)


def create_import_run(*, company: Company) -> Run:
    """Create a domain Run for connector import (PRD §6 step 5)."""
    return Run.objects.create(
        company=company,
        run_type=Run.RunType.INCREMENTAL,
        status=Run.Status.RUNNING,
        started_at=timezone.now(),
    )


def attach_run_to_data_run(*, data_run: DataRun, run: Run) -> None:
    """Store run_id on DataRun.metadata (PRD §6 step 6, §6b)."""
    data_run.metadata = {
        **data_run.metadata,
        "run_id": str(run.id),
    }
    data_run.save(update_fields=["metadata", "updated_at"])


def create_run_connector_snapshot(
    *,
    run: Run,
    connector: Connector,
    snapshot_data: dict[str, Any],
) -> ConnectorSnapshot:
    """Create ConnectorSnapshot and RunConnector (PRD §6 step 7)."""
    last_version = (
        ConnectorSnapshot.objects.filter(connector=connector)
        .aggregate(Max("version"))["version__max"]
        or 0
    )
    snapshot = ConnectorSnapshot.objects.create(
        connector=connector,
        version=last_version + 1,
        snapshot_data=snapshot_data,
    )
    RunConnector.objects.create(run=run, connector_snapshot=snapshot)
    return snapshot


def complete_import_run(*, run: Run) -> None:
    """Set Run to completed after a successful import (PRD §6 step 7)."""
    run.status = Run.Status.COMPLETED
    run.completed_at = timezone.now()
    run.save(update_fields=["status", "completed_at"])


def mark_data_run_succeeded(
    *,
    data_run: DataRun,
    counts: dict[str, Any],
    snapshot: ConnectorSnapshot,
) -> None:
    """Mark DataRun succeeded and merge success metadata (PRD §6b)."""
    if not bootstrap_data_run_may_persist(data_run):
        return
    data_run.status = DataRun.Status.SUCCEEDED
    data_run.finished_at = timezone.now()
    data_run.metadata = {
        **data_run.metadata,
        "counts": counts,
        "snapshot_id": str(snapshot.id),
    }
    data_run.save(update_fields=["status", "finished_at", "metadata", "updated_at"])


def mark_data_run_failed(*, data_run: DataRun, exc: BaseException) -> None:
    """Mark DataRun failed and store error in metadata (PRD §6b)."""
    if not bootstrap_data_run_may_persist(data_run):
        return
    data_run.status = DataRun.Status.FAILED
    data_run.finished_at = timezone.now()
    data_run.metadata = {
        **(data_run.metadata or {}),
        "error": str(exc),
        "error_type": type(exc).__name__,
    }
    data_run.save(update_fields=["status", "finished_at", "metadata", "updated_at"])


def finalize_import_run_on_failure(*, run: Run) -> None:
    """Set terminal state on a domain Run after import failure (PRD §6b)."""
    run.status = Run.Status.COMPLETED
    run.completed_at = timezone.now()
    run.save(update_fields=["status", "completed_at"])
