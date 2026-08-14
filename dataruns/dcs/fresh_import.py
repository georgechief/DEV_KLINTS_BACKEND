"""Fresh connector re-import before DCS score evaluation."""

from __future__ import annotations

import logging
from typing import Any

from django.conf import settings
from django.utils import timezone

from dataruns.connectors.base import (
    CONNECTOR_FETCH_KIND,
    decrypt_connector_config,
    get_connector,
)
from dataruns.connectors.bootstrap_health import (
    build_health_report,
    load_snapshot_data,
    persist_health_report,
    postflight_health,
)
from dataruns.connectors.import_data import ImportFailedError, run_import
from dataruns.models import DataRun
from tenants.models import Company, Connector

logger = logging.getLogger(__name__)

_PLATFORMS = ("shopify", "manago_ai")
_CONNECTED = frozenset({"connected", "degraded"})


class DcsFreshImportError(Exception):
    """Raised when a required connected platform fails to re-import for DCS."""

    def __init__(self, message: str, *, platform: str) -> None:
        super().__init__(message)
        self.platform = platform


def _create_fresh_import_data_run(
    *,
    company: Company,
    platform: str,
    days: int,
    dcs_data_run_id: int | None,
) -> DataRun:
    return DataRun.objects.create(
        tenant=company.tenant,
        name=f"dcs-fresh-import:{platform}",
        status=DataRun.Status.RUNNING,
        started_at=timezone.now(),
        metadata={
            "kind": CONNECTOR_FETCH_KIND,
            "platform": platform,
            "days": days,
            "company_id": str(company.id),
            "triggered_by": "dcs_score",
            "dcs_data_run_id": dcs_data_run_id,
        },
    )


def _handle_shopify_auth_failure(
    *,
    connector: Connector,
    company: Company,
    exc: BaseException,
    source: str,
) -> None:
    from dataruns.connectors.shopify_token import (
        classify_shopify_terminal_auth_failure,
        mark_shopify_auth_expired,
    )

    reason_code = classify_shopify_terminal_auth_failure(exc)
    if reason_code is None:
        return
    mark_shopify_auth_expired(
        connector=connector,
        company=company,
        reason_code=reason_code,
        source=source,
        error_message=str(exc),
    )


def _ensure_shopify_token(*, connector: Connector, company: Company) -> None:
    from dataruns.connectors.shopify_token import (
        ShopifyAuthExpiredError,
        ensure_fresh_shopify_token,
    )
    from tenants.shopify import ShopifyOAuthError

    try:
        ensure_fresh_shopify_token(connector=connector)
    except (ShopifyAuthExpiredError, ShopifyOAuthError) as exc:
        _handle_shopify_auth_failure(
            connector=connector,
            company=company,
            exc=exc,
            source="dcs_fresh_import",
        )
        raise DcsFreshImportError(
            f"Shopify token refresh failed: {exc}",
            platform="shopify",
        ) from exc


def _connected_connectors(company: Company) -> list[Connector]:
    connectors: list[Connector] = []
    for platform in _PLATFORMS:
        try:
            connector = get_connector(company=company, platform=platform)
        except Connector.DoesNotExist:
            continue
        if connector.status in _CONNECTED:
            connectors.append(connector)
    return connectors


def refresh_connected_platforms_for_dcs(
    *,
    company: Company,
    dcs_data_run: DataRun,
    days: int | None = None,
) -> dict[str, Any]:
    """
    Re-import every connected Shopify/Manago platform into the DB.

    Returns source_runs / fresh_imports maps keyed by platform → data_run id.
    Raises DcsFreshImportError if any connected platform import fails.
    """
    window_days = days if days is not None else settings.BOOTSTRAP_DAYS
    source_runs: dict[str, int | None] = {
        "shopify": None,
        "manago_ai": None,
    }
    fresh_imports: dict[str, dict[str, Any]] = {}

    connectors = _connected_connectors(company)
    if not connectors:
        return {
            "source_runs": source_runs,
            "fresh_imports": fresh_imports,
            "window_days": window_days,
        }

    for connector in connectors:
        platform = connector.name
        if platform == "shopify":
            _ensure_shopify_token(connector=connector, company=company)

        import_data_run = _create_fresh_import_data_run(
            company=company,
            platform=platform,
            days=window_days,
            dcs_data_run_id=dcs_data_run.id,
        )
        started = timezone.now()
        config = decrypt_connector_config(connector.config)

        try:
            result = run_import(
                platform=platform,
                company=company,
                data_run=import_data_run,
                days=window_days,
            )
        except ImportFailedError as exc:
            duration_ms = int((timezone.now() - started).total_seconds() * 1000)
            health_report = build_health_report(
                platform=platform,
                days=window_days,
                config=config,
                preflight_issues=[],
                postflight_issues=[],
                result=None,
                snapshot_data=load_snapshot_data(
                    (import_data_run.metadata or {}).get("snapshot_id")
                ),
                duration_ms=duration_ms,
                import_succeeded=False,
                data_run=import_data_run,
            )
            persist_health_report(
                data_run=import_data_run, health_report=health_report
            )
            raise DcsFreshImportError(
                f"Fresh {platform} import failed: {exc}",
                platform=platform,
            ) from exc
        except Exception as exc:  # noqa: BLE001
            import_data_run.refresh_from_db()
            if import_data_run.status != DataRun.Status.FAILED:
                import_data_run.status = DataRun.Status.FAILED
                import_data_run.finished_at = timezone.now()
                import_data_run.metadata = {
                    **(import_data_run.metadata or {}),
                    "error": str(exc),
                }
                import_data_run.save(
                    update_fields=[
                        "status",
                        "finished_at",
                        "metadata",
                        "updated_at",
                    ]
                )
            raise DcsFreshImportError(
                f"Fresh {platform} import failed: {exc}",
                platform=platform,
            ) from exc

        duration_ms = int((timezone.now() - started).total_seconds() * 1000)
        snapshot_data = load_snapshot_data(result.get("snapshot_id"))
        postflight_issues = postflight_health(
            platform=platform,
            days=window_days,
            result=result,
            snapshot_data=snapshot_data,
        )
        health_report = build_health_report(
            platform=platform,
            days=window_days,
            config=config,
            preflight_issues=[],
            postflight_issues=postflight_issues,
            result=result,
            snapshot_data=snapshot_data,
            duration_ms=duration_ms,
            import_succeeded=True,
            data_run=import_data_run,
        )
        persist_health_report(data_run=import_data_run, health_report=health_report)

        source_runs[platform] = import_data_run.id
        fresh_imports[platform] = {
            "data_run_id": import_data_run.id,
            "run_id": result.get("run_id"),
            "snapshot_id": result.get("snapshot_id"),
            "counts": result.get("counts") or {},
            "window_start": result.get("window_start"),
            "window_end": result.get("window_end"),
        }
        logger.info(
            "DCS fresh import ok company_id=%s platform=%s data_run_id=%s",
            company.id,
            platform,
            import_data_run.id,
        )

    return {
        "source_runs": source_runs,
        "fresh_imports": fresh_imports,
        "window_days": window_days,
    }
