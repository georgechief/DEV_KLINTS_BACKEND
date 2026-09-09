"""Offline import + DCS runner for GAP-01F demo seed (no live connector HTTP)."""

from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Callable
from unittest.mock import patch

from django.db import transaction
from django.utils import timezone

from dataruns.connectors.base import (
    attach_run_to_data_run,
    complete_import_run,
    create_import_run,
    create_run_connector_snapshot,
    decrypt_connector_config,
    get_connector,
    mark_data_run_succeeded,
)
from dataruns.connectors.bootstrap_health import (
    build_health_report,
    persist_health_report,
)
from dataruns.connectors.import_data import (
    _build_snapshot_data,
    _load_connector_map,
    _persist_contact_metrics,
    map_raw_payload,
    persist_normalized_records,
)
from dataruns.demo_seed.corpus import SkincareCorpus, build_skincare_corpus
from dataruns.dcs.context_builder import build_foundation_gate_context
from dataruns.dcs.enqueue import enqueue_dcs_score
from dataruns.dcs.fresh_import import refresh_connected_platforms_for_dcs
from dataruns.dcs.orchestrate import run_dcs_pipeline
from dataruns.models import Contact, DataRun
from tenants.models import Company


REMEDIATE_MIN = 50.0
REMEDIATE_MAX = 69.999


@dataclass(frozen=True)
class OfflineDcsResult:
    ok: bool
    data_run_id: int | None
    headline_score: float | None
    run_state: str | None
    contact_count: int
    corpus: SkincareCorpus
    in_remediate_band: bool
    detail: str


def _demo_apply_tracking(payload: dict[str, Any], *, company: Company | None = None) -> None:
    """Offline FD-07 signals — no live Manago recentActivity call."""
    if not payload.get("connected"):
        return
    payload["tracking_measurable"] = True
    payload["tracking_active"] = True
    payload["visit_events_recent"] = True
    payload["smclient_cookie_seen"] = True
    domain = getattr(company, "domain", None) if company is not None else None
    payload["storefront_domains"] = [domain] if domain else []
    payload["_tracking_detail"] = {"source": "gap01f_demo_seed"}


def _demo_apply_topology(
    payload: dict[str, Any],
    shopify_shop_domain: str | None = None,
) -> None:
    """Offline FD-06 topology — no live listByClient."""
    if not payload.get("connected"):
        return
    accounts = [
        {
            "owner": "demo-primary",
            "relationship": "primary",
            "endpoint": "https://app.manago.ai",
        }
    ]
    payload["topology_ok"] = True
    payload["topology_accounts"] = accounts
    payload["_topology_registry"] = {
        "accounts": accounts,
        "primary_owner": "demo-primary",
        "shopify_shop_domain": shopify_shop_domain,
        "source": "gap01f_demo_seed",
    }
    payload.pop("_topology_error", None)


def _demo_apply_rate_budget(payload: dict[str, Any], *, platform: str) -> None:
    """Offline FD-04 headroom — no live rate probe."""
    if not payload.get("connected"):
        return
    payload["rate_budget"] = {
        "platform": platform,
        "hit_rate_limit": False,
        "headroom_ok": True,
        "remaining": 40,
        "limit": 40,
        "used": 0,
        "source": "gap01f_demo_seed",
    }


def _demo_build_foundation_gate_context(*args: Any, **kwargs: Any):
    """Force skip_website_scrape so FD-07 Path B never hits live HTTP."""
    kwargs["skip_website_scrape"] = True
    return build_foundation_gate_context(*args, **kwargs)


def _corpus_run_import_side_effect(
    corpus: SkincareCorpus,
) -> Callable[..., dict[str, Any]]:
    def side_effect(
        *,
        platform: str,
        company: Company | None = None,
        data_run: DataRun | None = None,
        days: int | None = None,
        user=None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if company is None or data_run is None:
            raise ValueError("company and data_run are required for demo seed import.")
        raw = corpus.shopify_raw if platform == "shopify" else corpus.manago_raw
        window_days = days or 30
        window_end = timezone.now()
        window_start = window_end - timedelta(days=window_days)
        connector = get_connector(company=company, platform=platform)
        config = decrypt_connector_config(connector.config)
        connector_map = _load_connector_map(platform)
        run = create_import_run(company=company)
        attach_run_to_data_run(data_run=data_run, run=run)
        normalized = map_raw_payload(
            raw=raw,
            connector_map=connector_map,
            config=config,
        )
        with transaction.atomic():
            counts = persist_normalized_records(
                company=company,
                normalized=normalized,
                platform=platform,
            )
            contact_metrics_written = _persist_contact_metrics(
                run=run, company=company
            )
            snapshot_data = _build_snapshot_data(
                platform=platform,
                raw=raw,
                normalized=normalized,
                connector_config=connector.config,
                window_start=window_start,
                window_end=window_end,
            )
            snapshot = create_run_connector_snapshot(
                run=run,
                connector=connector,
                snapshot_data=snapshot_data,
            )
            complete_import_run(run=run)
            success_counts = {**counts, "contact_metrics": contact_metrics_written}
            mark_data_run_succeeded(
                data_run=data_run,
                counts=success_counts,
                snapshot=snapshot,
            )
        result_payload = {
            "data_run_id": data_run.id,
            "run_id": str(run.id),
            "snapshot_id": str(snapshot.id),
            "connector": platform,
            "counts": success_counts,
            "window_start": window_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "window_end": window_end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "status": "succeeded",
        }
        # Honest offline health — auth/scopes from stub config; no live probe.
        health_report = build_health_report(
            platform=platform,
            days=window_days,
            config=config,
            preflight_issues=[],
            postflight_issues=[],
            result=result_payload,
            snapshot_data=snapshot_data,
            duration_ms=1,
            import_succeeded=True,
            data_run=data_run,
        )
        persist_health_report(data_run=data_run, health_report=health_report)
        return result_payload

    return side_effect


def run_offline_demo_dcs(
    *,
    company: Company,
    contacts: int,
    seed: int = 42,
    triggered_by: str = "gap01f_demo_seed",
) -> OfflineDcsResult:
    """
    Persist skincare corpus via patched ``run_import``, then run DCS in-process.

    No live Shopify/Manago HTTP (F0.2). Foundation probes that require live APIs
    are stubbed with explicit demo markers (tracking / topology / rate budget).
    Company-website scrape for FD-07 Path B is forced off (``skip_website_scrape``).
    """
    corpus = build_skincare_corpus(contacts=contacts, seed=seed)
    side_effect = _corpus_run_import_side_effect(corpus)

    enqueued = enqueue_dcs_score(
        company,
        triggered_by=triggered_by,
        erp_in_scope=False,
        live_revalidate=False,
        queue=False,
    )
    data_run = enqueued.data_run
    if data_run is None:
        return OfflineDcsResult(
            ok=False,
            data_run_id=None,
            headline_score=None,
            run_state=None,
            contact_count=0,
            corpus=corpus,
            in_remediate_band=False,
            detail=f"enqueue skipped: {enqueued.skip_reason}",
        )

    meta = dict(data_run.metadata or {})
    meta["live_revalidate"] = False
    meta["erp_in_scope"] = False
    meta["gap01f_demo_seed"] = True
    data_run.metadata = meta
    data_run.save(update_fields=["metadata", "updated_at"])

    with ExitStack() as stack:
        stack.enter_context(patch("dataruns.dcs.fresh_import._ensure_shopify_token"))
        stack.enter_context(
            patch("dataruns.architecture.enqueue.maybe_enqueue_architecture_after_dcs")
        )
        stack.enter_context(patch("dataruns.dcs.orchestrate._audit_dcs_completed"))
        stack.enter_context(patch("dataruns.dcs.orchestrate._notify_dcs_completed"))
        stack.enter_context(
            patch("tenants.manago_topology_service.ensure_manago_primary_owner")
        )
        stack.enter_context(
            patch(
                "dataruns.dcs.fresh_import.run_import",
                side_effect=side_effect,
            )
        )
        stack.enter_context(
            patch(
                "dataruns.dcs.orchestrate.refresh_connected_platforms_for_dcs",
                wraps=refresh_connected_platforms_for_dcs,
            )
        )
        stack.enter_context(
            patch(
                "dataruns.dcs.db_context._apply_manago_tracking_evidence",
                side_effect=_demo_apply_tracking,
            )
        )
        stack.enter_context(
            patch(
                "dataruns.dcs.db_context._apply_manago_topology",
                side_effect=_demo_apply_topology,
            )
        )
        stack.enter_context(
            patch(
                "dataruns.dcs.db_context._apply_rate_budget",
                side_effect=_demo_apply_rate_budget,
            )
        )
        stack.enter_context(
            patch(
                "dataruns.dcs.db_context.build_foundation_gate_context",
                side_effect=_demo_build_foundation_gate_context,
            )
        )
        result = run_dcs_pipeline(data_run)

    data_run.refresh_from_db()
    dcs = (data_run.metadata or {}).get("dcs_run") or {}
    headline = dcs.get("headline_score")
    run_state = dcs.get("run_state")
    contact_count = Contact.objects.filter(company=company).count()
    try:
        headline_f = float(headline) if headline is not None else None
    except (TypeError, ValueError):
        headline_f = None
    in_band = (
        headline_f is not None and REMEDIATE_MIN <= headline_f <= REMEDIATE_MAX
    )
    ok = bool(result.get("ok")) and data_run.status == DataRun.Status.SUCCEEDED
    detail = (
        f"status={data_run.status} state={run_state} headline={headline_f} "
        f"contacts={contact_count} matched={corpus.matched_count} "
        f"shopify_only={corpus.shopify_only_count} "
        f"manago_only={corpus.manago_only_count} mismatch={corpus.mismatch_count} "
        f"manago_dup={corpus.manago_dup_count}"
    )
    return OfflineDcsResult(
        ok=ok,
        data_run_id=data_run.id,
        headline_score=headline_f,
        run_state=str(run_state) if run_state else None,
        contact_count=contact_count,
        corpus=corpus,
        in_remediate_band=in_band,
        detail=detail,
    )
