from __future__ import annotations

import logging
from typing import Any

from celery import shared_task
from django.utils import timezone

from dataruns.connectors.base import (
    CONNECTOR_BOOTSTRAP_KIND,
    bootstrap_data_run_may_persist,
    bootstrap_data_run_was_superseded,
    decrypt_connector_config,
    get_connector,
    mark_data_run_failed,
    resolve_bootstrap_days_from_data_run,
    resolve_company_from_data_run,
)
from dataruns.connectors.bootstrap_health import (
    build_health_report,
    classify_import_failure,
    connector_status_from_summary,
    health_issue,
    load_snapshot_data,
    missing_shopify_scopes,
    parse_shopify_scopes,
    persist_health_report,
    postflight_health,
    warn_issues_from_health_report,
)
from dataruns.connectors.import_data import (
    BootstrapSupersededError,
    ImportFailedError,
    run_import,
)
from dataruns.connectors.manago_ai.client import (
    ManagoClientError,
    _resolve_credentials,
    _resolve_owner,
)
from dataruns.models import DataRun
from tenants.manago import resolve_manago_api_base_url, verify_credentials
from tenants.models import Company, Connector
from tenants.shopify import ShopifyOAuthError, fetch_shop

logger = logging.getLogger(__name__)

_SUPPORTED_PLATFORMS = frozenset({"shopify", "manago_ai"})


@shared_task(bind=True, name="dataruns.run_dcs_score")
def run_dcs_score(self, data_run_id: int) -> dict[str, Any]:
    """
    DCS score worker (PRD-DCS-01 / PRD-DCS-07).

    Re-imports connected Shopify/Manago data, freezes run_snapshot, evaluates
    foundation gates, stubs remaining MVP1 checks as UNKNOWN, assembles score,
    and persists RunScore + RunIssue/Impact rows.

    Shopify token refresh also runs when metadata.live_revalidate is true
    (fresh import path refreshes Shopify tokens before fetch as well).
    """
    from dataruns.dcs.constants import DCS_SCORE_KIND
    from dataruns.dcs.orchestrate import run_dcs_pipeline

    try:
        data_run = DataRun.objects.select_related("tenant").get(pk=data_run_id)
    except DataRun.DoesNotExist:
        return {"ok": False, "error": f"DataRun {data_run_id} not found"}

    metadata = data_run.metadata or {}
    if metadata.get("kind") != DCS_SCORE_KIND:
        return {"ok": False, "error": "Not a DCS score DataRun."}

    if metadata.get("live_revalidate") is True:
        company_id = metadata.get("company_id")
        if company_id:
            try:
                company = Company.objects.get(pk=company_id)
                connector = get_connector(company=company, platform="shopify")
            except (Company.DoesNotExist, Connector.DoesNotExist):
                connector = None
            else:
                if connector.status in ("connected", "degraded"):
                    from dataruns.connectors.shopify_token import (
                        ShopifyAuthExpiredError,
                        classify_shopify_terminal_auth_failure,
                        ensure_fresh_shopify_token,
                        mark_shopify_auth_expired,
                    )

                    try:
                        ensure_fresh_shopify_token(connector=connector)
                    except (ShopifyAuthExpiredError, ShopifyOAuthError) as exc:
                        reason_code = classify_shopify_terminal_auth_failure(exc)
                        if reason_code is not None:
                            mark_shopify_auth_expired(
                                connector=connector,
                                company=company,
                                reason_code=reason_code,
                                source="dcs_live_revalidate",
                                error_message=str(exc),
                            )
                        data_run.status = DataRun.Status.FAILED
                        data_run.finished_at = timezone.now()
                        data_run.metadata = {
                            **metadata,
                            "error": str(exc),
                            "auth_failed": True,
                        }
                        data_run.save(
                            update_fields=[
                                "status",
                                "finished_at",
                                "metadata",
                                "updated_at",
                            ]
                        )
                        return {
                            "ok": False,
                            "error": str(exc),
                            "data_run_id": data_run.id,
                        }

    result = run_dcs_pipeline(data_run)
    if isinstance(result, dict):
        result = {
            **result,
            "celery_task_id": getattr(self.request, "id", None),
        }
    return result


@shared_task(bind=True, name="dataruns.run_architecture_assessment")
def run_architecture_assessment(self, assessment_id: str) -> dict[str, Any]:
    """Architecture Assessment worker (PRD-AF-01 Phase A scaffold)."""
    from dataruns.architecture.runner import run_architecture_assessment_job

    result = run_architecture_assessment_job(assessment_id)
    if isinstance(result, dict):
        result = {
            **result,
            "celery_task_id": getattr(self.request, "id", None),
        }
    return result


@shared_task(bind=True, name="dataruns.process_data_run")
def process_data_run(self, data_run_id: int):
    """
    Process a DataRun asynchronously.

    Scaffold: flips status through running → succeeded. Replace the body
    with real ingestion / pipeline work.
    """
    try:
        data_run = DataRun.objects.select_related("tenant").get(pk=data_run_id)
    except DataRun.DoesNotExist:
        return {"ok": False, "error": f"DataRun {data_run_id} not found"}

    data_run.status = DataRun.Status.RUNNING
    data_run.started_at = timezone.now()
    data_run.save(update_fields=["status", "started_at", "updated_at"])

    try:
        # Placeholder for pipeline work
        data_run.metadata = {
            **(data_run.metadata or {}),
            "celery_task_id": self.request.id,
            "processed_at": timezone.now().isoformat(),
        }
        data_run.status = DataRun.Status.SUCCEEDED
        data_run.finished_at = timezone.now()
        data_run.save(
            update_fields=["status", "finished_at", "metadata", "updated_at"]
        )
        return {
            "ok": True,
            "data_run_id": data_run.id,
            "tenant": data_run.tenant.slug,
            "status": data_run.status,
        }
    except Exception as exc:
        data_run.status = DataRun.Status.FAILED
        data_run.finished_at = timezone.now()
        data_run.metadata = {
            **(data_run.metadata or {}),
            "error": str(exc),
            "celery_task_id": self.request.id,
        }
        data_run.save(
            update_fields=["status", "finished_at", "metadata", "updated_at"]
        )
        raise


@shared_task(bind=True, name="dataruns.bootstrap_connector_fetch")
def bootstrap_connector_fetch(self, data_run_id: int) -> dict[str, Any]:
    """
    On-connect bootstrap worker (PRD-CONN-01 §4 E, §6, §7).

    Preflight connector health, then run the existing import pipeline against a
    pre-created bootstrap DataRun.
    """
    try:
        data_run = DataRun.objects.get(pk=data_run_id)
    except DataRun.DoesNotExist:
        return {"ok": False, "error": f"DataRun {data_run_id} not found"}

    metadata = data_run.metadata or {}
    if metadata.get("kind") != CONNECTOR_BOOTSTRAP_KIND:
        return {"ok": False, "error": "Not a bootstrap DataRun."}

    # Only PENDING runs execute: enqueue idempotency prevents duplicate active
    # bootstraps; this guard prevents duplicate worker execution when Celery
    # redelivers the same task (ACKS_LATE). Non-pending statuses are terminal
    # or already in progress.
    if data_run.status != DataRun.Status.PENDING:
        return {
            "ok": True,
            "skipped": True,
            "data_run_id": data_run.id,
            "status": data_run.status,
            "reason": "status_guard",
        }

    claimed = DataRun.objects.filter(
        pk=data_run.id,
        status=DataRun.Status.PENDING,
    ).update(
        status=DataRun.Status.RUNNING,
        started_at=timezone.now(),
        updated_at=timezone.now(),
    )
    if claimed == 0:
        data_run.refresh_from_db()
        return {
            "ok": True,
            "skipped": True,
            "data_run_id": data_run.id,
            "status": data_run.status,
            "reason": "status_guard",
        }
    data_run.refresh_from_db()

    try:
        company = resolve_company_from_data_run(data_run)
    except (ValueError, Company.DoesNotExist) as exc:
        return _fail_bootstrap(
            data_run=data_run,
            connector=None,
            error_message=str(exc),
            celery_task_id=self.request.id,
            platform=metadata.get("platform"),
        )

    platform = metadata.get("platform")
    if platform not in _SUPPORTED_PLATFORMS:
        return _fail_bootstrap(
            data_run=data_run,
            connector=None,
            error_message=f"Unknown platform: {platform}",
            celery_task_id=self.request.id,
            company=company,
            platform=platform,
        )

    skipped = _skipped_superseded_bootstrap(data_run=data_run)
    if skipped is not None:
        return skipped

    try:
        connector, config = _load_fresh_connector_config(
            company=company,
            platform=platform,
        )
    except Connector.DoesNotExist:
        return _fail_bootstrap(
            data_run=data_run,
            connector=None,
            error_message="Connector not connected.",
            celery_task_id=self.request.id,
            company=company,
            platform=platform,
        )

    if platform == "shopify":
        refreshed, token_failure = _ensure_shopify_token_for_bootstrap(
            connector=connector,
            config=config,
            data_run=data_run,
            celery_task_id=self.request.id,
            company=company,
        )
        if token_failure is not None:
            return token_failure
        config = refreshed

    issues = _preflight_connector(platform=platform, config=config)
    if _blocking_issues(issues):
        return _fail_bootstrap_preflight(
            data_run=data_run,
            connector=connector,
            issues=issues,
            celery_task_id=self.request.id,
            company=company,
            platform=platform,
            config=config,
        )

    try:
        days = resolve_bootstrap_days_from_data_run(data_run)
    except ValueError as exc:
        return _fail_bootstrap(
            data_run=data_run,
            connector=connector,
            error_message=str(exc),
            celery_task_id=self.request.id,
            company=company,
            platform=platform,
        )

    skipped = _skipped_superseded_bootstrap(data_run=data_run)
    if skipped is not None:
        return skipped

    try:
        import_started_at = timezone.now()
        result = run_import(
            platform=platform,
            company=company,
            data_run=data_run,
            days=days,
        )
    except BootstrapSupersededError:
        skipped = _skipped_superseded_bootstrap(data_run=data_run)
        if skipped is not None:
            return skipped
        raise
    except ImportFailedError as exc:
        skipped = _skipped_superseded_bootstrap(data_run=data_run)
        if skipped is not None:
            return skipped

        duration_ms = int((timezone.now() - import_started_at).total_seconds() * 1000)
        import_issue = classify_import_failure(exc)
        health_report = build_health_report(
            platform=platform,
            days=days,
            config=config,
            preflight_issues=issues,
            postflight_issues=[],
            result=None,
            snapshot_data=load_snapshot_data((data_run.metadata or {}).get("snapshot_id")),
            duration_ms=duration_ms,
            import_succeeded=False,
            import_issue=import_issue,
            data_run=data_run,
        )
        persist_health_report(data_run=data_run, health_report=health_report)
        _apply_connector_status(connector, health_report)
        _notify_bootstrap_failure(
            data_run=data_run,
            company=company,
            platform=platform,
            error_message=str(exc),
            issue_codes=[import_issue["code"]],
        )
        return {
            "ok": False,
            "data_run_id": data_run.id,
            "error": str(exc),
        }
    except Exception as exc:
        skipped = _skipped_superseded_bootstrap(data_run=data_run)
        if skipped is not None:
            return skipped

        duration_ms = int((timezone.now() - import_started_at).total_seconds() * 1000)
        import_issue = classify_import_failure(exc)
        mark_data_run_failed(data_run=data_run, exc=exc)
        health_report = build_health_report(
            platform=platform,
            days=days,
            config=config,
            preflight_issues=issues,
            postflight_issues=[],
            result=None,
            snapshot_data=load_snapshot_data((data_run.metadata or {}).get("snapshot_id")),
            duration_ms=duration_ms,
            import_succeeded=False,
            import_issue=import_issue,
            data_run=data_run,
        )
        persist_health_report(data_run=data_run, health_report=health_report)
        _apply_connector_status(connector, health_report)
        _notify_bootstrap_failure(
            data_run=data_run,
            company=company,
            platform=platform,
            error_message=str(exc),
            issue_codes=[import_issue["code"]],
        )
        raise

    if bootstrap_data_run_was_superseded(data_run):
        return _bootstrap_skip_response(data_run=data_run, reason="superseded")

    duration_ms = int((timezone.now() - import_started_at).total_seconds() * 1000)
    snapshot_data = load_snapshot_data(result.get("snapshot_id"))
    postflight_issues = postflight_health(
        platform=platform,
        days=days,
        result=result,
        snapshot_data=snapshot_data,
    )
    health_report = build_health_report(
        platform=platform,
        days=days,
        config=config,
        preflight_issues=issues,
        postflight_issues=postflight_issues,
        result=result,
        snapshot_data=snapshot_data,
        duration_ms=duration_ms,
        import_succeeded=True,
        data_run=data_run,
    )
    persist_health_report(data_run=data_run, health_report=health_report)
    _apply_connector_status(connector, health_report)

    warn_issues = warn_issues_from_health_report(health_report)
    _notify_bootstrap_success(
        company=company,
        platform=platform,
        days=days,
        result=result,
        warn_issues=warn_issues,
    )
    _audit_bootstrap_succeeded(
        company=company,
        platform=platform,
        data_run=data_run,
        result=result,
    )

    dcs_enqueue = _maybe_enqueue_dcs_after_bootstrap(company)
    payload = {"ok": True, **result}
    if dcs_enqueue is not None:
        payload["dcs_score"] = {
            "enqueued": not dcs_enqueue.skipped and dcs_enqueue.task_queued,
            "skipped": dcs_enqueue.skipped,
            "skip_reason": dcs_enqueue.skip_reason,
            "data_run_id": (
                dcs_enqueue.data_run.id if dcs_enqueue.data_run is not None else None
            ),
        }
    return payload


def _maybe_enqueue_dcs_after_bootstrap(company: Company) -> Any:
    """Enqueue DCS when both Shopify + Manago bootstraps are ready."""
    from dataruns.dcs.enqueue import maybe_enqueue_dcs_after_bootstrap

    try:
        result = maybe_enqueue_dcs_after_bootstrap(company)
    except Exception:  # noqa: BLE001 — never fail bootstrap because of DCS enqueue
        logger.exception(
            "post_bootstrap DCS enqueue failed company_id=%s",
            company.id,
        )
        return None
    if result is None:
        return None
    if result.data_run is not None:
        logger.info(
            "post_bootstrap DCS enqueued company_id=%s data_run_id=%s",
            company.id,
            result.data_run.id,
        )
    elif result.skipped:
        logger.info(
            "post_bootstrap DCS skipped company_id=%s reason=%s",
            company.id,
            result.skip_reason,
        )
    return result


def _bootstrap_platform_label(platform: str) -> str:
    if platform == "manago_ai":
        return "Manago.ai"
    if platform == "shopify":
        return "Shopify"
    return platform


def _audit_bootstrap_succeeded(
    *,
    company: Company,
    platform: str,
    data_run: DataRun,
    result: dict[str, Any],
) -> None:
    from dataruns.audit import append_audit_event, resolve_performed_by_email

    metadata = data_run.metadata or {}
    actor_user_id = metadata.get("actor_user_id")
    performed_by = resolve_performed_by_email(
        str(actor_user_id) if actor_user_id else None
    )
    counts = result.get("counts") or metadata.get("counts") or {}
    contacts = int(counts.get("contacts") or 0)
    orders = int(counts.get("orders") or 0)
    label = _bootstrap_platform_label(platform)
    append_audit_event(
        company=company,
        action="connector.bootstrap_succeeded",
        summary=f"{label} bootstrap succeeded · {contacts} contacts · {orders} orders",
        performed_by=performed_by,
        actor_user_id=str(actor_user_id) if actor_user_id else None,
        metadata={
            "platform": platform,
            "data_run_id": data_run.id,
            "run_id": metadata.get("run_id"),
        },
    )


def _audit_bootstrap_failed(
    *,
    company: Company,
    data_run: DataRun,
    platform: str,
    error_message: str,
) -> None:
    from dataruns.audit import append_audit_event, resolve_performed_by_email
    from dataruns.models import AuditLog

    metadata = data_run.metadata or {}
    actor_user_id = metadata.get("actor_user_id")
    performed_by = resolve_performed_by_email(
        str(actor_user_id) if actor_user_id else None
    )
    label = _bootstrap_platform_label(platform)
    append_audit_event(
        company=company,
        action="connector.bootstrap_failed",
        summary=f"{label} bootstrap failed · {error_message}",
        performed_by=performed_by,
        tone=AuditLog.Tone.LOSS,
        actor_user_id=str(actor_user_id) if actor_user_id else None,
        metadata={
            "platform": platform,
            "data_run_id": data_run.id,
            "run_id": metadata.get("run_id"),
            "error": error_message,
        },
    )


def _ensure_shopify_token_for_bootstrap(
    *,
    connector: Connector,
    config: dict[str, Any],
    data_run: DataRun,
    celery_task_id: str | None,
    company: Company,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    from dataruns.connectors.shopify_token import (
        ShopifyAuthExpiredError,
        ensure_fresh_shopify_token,
    )

    try:
        return ensure_fresh_shopify_token(connector=connector), None
    except (ShopifyAuthExpiredError, ShopifyOAuthError) as exc:
        from dataruns.connectors.shopify_token import (
            classify_shopify_terminal_auth_failure,
            mark_shopify_auth_expired,
        )

        reason_code = classify_shopify_terminal_auth_failure(exc)
        if reason_code is not None:
            mark_shopify_auth_expired(
                connector=connector,
                company=company,
                reason_code=reason_code,
                source="bootstrap",
                error_message=str(exc),
            )
        issues = [
            health_issue(
                code="AUTH_FAILED",
                severity="error",
                message=str(exc),
            )
        ]
        return config, _fail_bootstrap_preflight(
            data_run=data_run,
            connector=connector,
            issues=issues,
            celery_task_id=celery_task_id,
            company=company,
            platform="shopify",
            config=config,
        )


def _load_fresh_connector_config(
    *,
    company: Company,
    platform: str,
) -> tuple[Connector, dict[str, Any]]:
    """Load connector and decrypt config from the database (never cached)."""
    connector = get_connector(company=company, platform=platform)
    config = decrypt_connector_config(connector.config)
    return connector, config


def _bootstrap_skip_response(*, data_run: DataRun, reason: str) -> dict[str, Any]:
    data_run.refresh_from_db()
    return {
        "ok": True,
        "skipped": True,
        "data_run_id": data_run.id,
        "status": data_run.status,
        "reason": reason,
    }


def _skipped_superseded_bootstrap(*, data_run: DataRun) -> dict[str, Any] | None:
    """Return a skip response when this bootstrap was superseded or is no longer active."""
    if bootstrap_data_run_was_superseded(data_run):
        return _bootstrap_skip_response(data_run=data_run, reason="superseded")
    data_run.refresh_from_db()
    metadata = data_run.metadata or {}
    if metadata.get("kind") == CONNECTOR_BOOTSTRAP_KIND:
        if data_run.status != DataRun.Status.RUNNING:
            return _bootstrap_skip_response(data_run=data_run, reason="status_guard")
    return None


def _preflight_connector(*, platform: str, config: dict[str, Any]) -> list[dict[str, str]]:
    if platform == "manago_ai":
        return _preflight_manago(config)
    if platform == "shopify":
        return _preflight_shopify(config)
    return [
        health_issue(
            code="FETCH_FAILED",
            severity="error",
            message=f"Unsupported platform: {platform}",
        )
    ]


def _preflight_manago(config: dict[str, Any]) -> list[dict[str, str]]:
    workspace_id = config.get("workspace_id")
    api_key = config.get("api_key")
    endpoint = resolve_manago_api_base_url(config)

    if not isinstance(workspace_id, str) or not workspace_id.strip():
        return [
            health_issue(
                code="AUTH_FAILED",
                severity="error",
                message="Manago connector is missing workspace_id.",
            )
        ]
    if not isinstance(api_key, str) or not api_key:
        return [
            health_issue(
                code="AUTH_FAILED",
                severity="error",
                message="Manago connector is missing api_key.",
            )
        ]

    result = verify_credentials(
        client_id=workspace_id.strip(),
        api_secret=api_key,
        endpoint=endpoint,
    )
    if not result.valid:
        return [
            health_issue(
                code="AUTH_FAILED",
                severity="error",
                message=result.message,
            )
        ]

    try:
        resolved_endpoint, client_id, api_secret = _resolve_credentials(config)
        _resolve_owner(
            endpoint=resolved_endpoint,
            client_id=client_id,
            api_secret=api_secret,
            timeout=15.0,
        )
    except ManagoClientError as exc:
        return [
            health_issue(
                code="AUTH_FAILED",
                severity="error",
                message=str(exc),
            )
        ]

    return []


def _preflight_shopify(config: dict[str, Any]) -> list[dict[str, str]]:
    shop_domain = config.get("shop_domain")
    access_token = config.get("access_token")

    if not isinstance(shop_domain, str) or not shop_domain.strip():
        return [
            health_issue(
                code="AUTH_FAILED",
                severity="error",
                message="Shopify connector is missing shop_domain.",
            )
        ]
    if not isinstance(access_token, str) or not access_token:
        return [
            health_issue(
                code="AUTH_FAILED",
                severity="error",
                message="Shopify connector is missing access_token.",
            )
        ]

    try:
        fetch_shop(shop=shop_domain.strip(), access_token=access_token)
    except ShopifyOAuthError as exc:
        return [
            health_issue(
                code="AUTH_FAILED",
                severity="error",
                message=str(exc),
            )
        ]

    granted_scopes = parse_shopify_scopes(config.get("scopes"))
    issues: list[dict[str, str]] = []

    missing_required, missing_recommended = missing_shopify_scopes(granted_scopes)
    if missing_required:
        issues.append(
            health_issue(
                code="SCOPES_MISSING",
                severity="error",
                message=(
                    "Missing required Shopify scopes: "
                    f"{', '.join(missing_required)}"
                ),
            )
        )

    if missing_recommended:
        issues.append(
            health_issue(
                code="SCOPES_MISSING",
                severity="warn",
                message=(
                    "Missing recommended Shopify scopes: "
                    f"{', '.join(missing_recommended)}"
                ),
            )
        )

    return issues


def _blocking_issues(issues: list[dict[str, str]]) -> list[dict[str, str]]:
    return [issue for issue in issues if issue.get("severity") == "error"]


def _fail_bootstrap_preflight(
    *,
    data_run: DataRun,
    connector: Connector,
    issues: list[dict[str, str]],
    celery_task_id: str | None,
    company: Company,
    platform: str,
    config: dict[str, Any],
) -> dict[str, Any]:
    blocking = _blocking_issues(issues)
    error_message = blocking[0]["message"] if blocking else "Bootstrap preflight failed."
    return _fail_bootstrap(
        data_run=data_run,
        connector=connector,
        error_message=error_message,
        celery_task_id=celery_task_id,
        preflight_issues=issues,
        company=company,
        platform=platform,
        config=config,
    )


def _fail_bootstrap(
    *,
    data_run: DataRun,
    connector: Connector | None,
    error_message: str,
    celery_task_id: str | None,
    preflight_issues: list[dict[str, str]] | None = None,
    company: Company | None = None,
    platform: str | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if bootstrap_data_run_was_superseded(data_run):
        return _bootstrap_skip_response(data_run=data_run, reason="superseded")

    data_run.status = DataRun.Status.FAILED
    data_run.finished_at = timezone.now()
    metadata = data_run.metadata or {}
    resolved_platform = platform or metadata.get("platform")
    resolved_days = metadata.get("days")
    days = resolved_days if isinstance(resolved_days, int) and not isinstance(resolved_days, bool) else 30
    resolved_config = config or {}
    if connector is not None and not resolved_config:
        resolved_config = decrypt_connector_config(connector.config)

    health_report = build_health_report(
        platform=str(resolved_platform or "unknown"),
        days=days,
        config=resolved_config,
        preflight_issues=preflight_issues or [],
        postflight_issues=[],
        result=None,
        snapshot_data={},
        duration_ms=0,
        import_succeeded=False,
        import_issue=(
            health_issue(
                code="FETCH_FAILED",
                severity="error",
                message=error_message,
            )
            if preflight_issues is None
            else None
        ),
        data_run=data_run,
    )

    metadata = {
        **metadata,
        "error": error_message,
        "health_report": health_report,
    }
    if celery_task_id:
        metadata["celery_task_id"] = celery_task_id
    data_run.metadata = metadata
    data_run.save(update_fields=["status", "finished_at", "metadata", "updated_at"])
    _apply_connector_status(connector, health_report)

    response: dict[str, Any] = {
        "ok": False,
        "data_run_id": data_run.id,
        "error": error_message,
    }
    if preflight_issues is not None:
        response["preflight"] = preflight_issues
    _notify_bootstrap_failure(
        data_run=data_run,
        company=company,
        platform=platform,
        error_message=error_message,
        preflight_issues=preflight_issues,
    )
    if company is not None:
        _audit_bootstrap_failed(
            company=company,
            data_run=data_run,
            platform=str(resolved_platform or "unknown"),
            error_message=error_message,
        )
    return response


def _apply_connector_status(
    connector: Connector | None,
    health_report: dict[str, Any],
) -> None:
    """Map summary_status to Connector.status on terminal bootstrap paths."""
    if connector is None:
        return
    connector.status = connector_status_from_summary(health_report["summary_status"])
    connector.save(update_fields=["status", "updated_at"])


def _notify_bootstrap_success(
    *,
    company: Company,
    platform: str,
    days: int,
    result: dict[str, Any],
    warn_issues: list[dict[str, str]],
) -> None:
    from tenants.emails import MailerAPIError, send_connector_bootstrap_success_email

    window_start = result.get("window_start") or ""
    window_end = result.get("window_end") or ""
    try:
        send_connector_bootstrap_success_email(
            company=company,
            platform=platform,
            days=days,
            counts=result.get("counts") or {},
            window_start=str(window_start),
            window_end=str(window_end),
            warn_issues=warn_issues or None,
        )
    except MailerAPIError:
        logger.warning(
            "bootstrap success email failed platform=%s company_id=%s",
            platform,
            company.id,
        )
    except Exception:  # noqa: BLE001 — never fail bootstrap because of email
        logger.exception(
            "bootstrap success email unexpected error platform=%s company_id=%s",
            platform,
            company.id,
        )


def _notify_bootstrap_failure(
    *,
    data_run: DataRun,
    company: Company | None,
    platform: str | None,
    error_message: str,
    preflight_issues: list[dict[str, str]] | None = None,
    issue_codes: list[str] | None = None,
) -> None:
    from tenants.emails import MailerAPIError, send_connector_bootstrap_failure_email

    resolved_company = company
    if resolved_company is None:
        try:
            resolved_company = resolve_company_from_data_run(data_run)
        except (ValueError, Company.DoesNotExist):
            return

    resolved_platform = platform or (data_run.metadata or {}).get("platform")
    if not isinstance(resolved_platform, str) or not resolved_platform:
        return

    resolved_issue_codes = issue_codes
    if not resolved_issue_codes:
        resolved_issue_codes = [
            str(issue["code"])
            for issue in (preflight_issues or [])
            if issue.get("code")
        ] or None

    try:
        send_connector_bootstrap_failure_email(
            company=resolved_company,
            platform=resolved_platform,
            error_message=error_message,
            issue_codes=resolved_issue_codes,
        )
    except MailerAPIError:
        return


@shared_task(bind=True, name="dataruns.dispatch_daily_dcs_scores")
def dispatch_daily_dcs_scores(self) -> dict[str, Any]:
    """Beat entrypoint: enqueue run_dcs_score for every eligible company."""
    from dataruns.dcs.enqueue import DAILY_BEAT_TRIGGER, enqueue_dcs_score, find_eligible_companies

    eligible_companies = list(find_eligible_companies())
    enqueued = 0
    skipped_already_ran = 0
    errors: list[dict[str, str]] = []

    for company in eligible_companies:
        try:
            result = enqueue_dcs_score(company, triggered_by=DAILY_BEAT_TRIGGER)
            if result.skipped:
                skipped_already_ran += 1
                continue
            enqueued += 1
            if result.data_run is not None:
                logger.info(
                    "daily_dcs_score enqueued company_id=%s data_run_id=%s",
                    company.id,
                    result.data_run.id,
                )
        except Exception as exc:  # noqa: BLE001 — isolate per-company failures
            errors.append(
                {
                    "company_id": str(company.id),
                    "error": str(exc),
                }
            )

    return {
        "ok": True,
        "eligible_companies": len(eligible_companies),
        "enqueued": enqueued,
        "skipped_already_ran": skipped_already_ran,
        "errors": errors,
    }
