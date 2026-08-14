"""Foundation gate executors FD-01…FD-07 (Excel sheet 02 + PRD-DCS-02)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

from dataruns.dcs.catalogue import (
    build_failure_message,
    foundation_gate_meta,
    root_cause_details,
    user_facing_suggested_fix,
)
from dataruns.dcs.types import CheckResult, Confidence, Evidence

# Sheet 02 FD-02 required scopes (stricter than CONN-01 bootstrap minimum).
SHOPIFY_FD02_REQUIRED_SCOPES = frozenset({"read_customers", "read_orders"})


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


@dataclass
class ConnectorGateInput:
    """Minimal connector + bootstrap health context for foundation gates."""

    platform: str
    connected: bool = False
    connector_status: str | None = None
    data_run_id: int | str | None = None
    health_report: dict[str, Any] | None = None
    # Sheet-accurate optional inputs
    live_auth_ok: bool | None = None
    live_auth_message: str | None = None
    scopes_granted: list[str] | None = None
    topology_ok: bool | None = None
    topology_accounts: list[dict[str, Any]] | None = None
    tracking_measurable: bool | None = None
    tracking_active: bool | None = None
    visit_events_recent: bool | None = None
    smclient_cookie_seen: bool | None = None
    storefront_domains: list[str] | None = None
    history_earliest: dict[str, str] | None = None
    rate_budget: dict[str, Any] | None = None


@dataclass
class FoundationGateContext:
    """Inputs for evaluating all foundation gates."""

    manago: ConnectorGateInput | None = None
    shopify: ConnectorGateInput | None = None
    erp_in_scope: bool = False
    erp_connected: bool = False
    erp_reachable: bool | None = None
    erp_row_count: int | None = None
    erp_schema_ok: bool | None = None
    erp_encoding_ok: bool | None = None
    # Company website (FD-07 scrape); host only, already normalized when set.
    company_website_domain: str | None = None
    # Extra hosts to scrape when company website missing/invalid (Shopify storefront).
    storefront_scrape_hosts: list[str] = field(default_factory=list)
    skip_website_scrape: bool = False
    website_scrape_opener: Any | None = None
    tenant_id: str = ""
    run_id: str = ""
    evaluated_at: str | None = None
    bootstrap_days_required: int = 30
    extra: dict[str, Any] = field(default_factory=dict)


def _issues_from_health(health_report: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(health_report, dict):
        return []
    issues: list[dict[str, Any]] = []
    for section_name in ("preflight", "postflight", "fetch"):
        section = health_report.get(section_name)
        if not isinstance(section, dict):
            continue
        raw = section.get("issues") or []
        if isinstance(raw, list):
            issues.extend(item for item in raw if isinstance(item, dict))
    top = health_report.get("issues")
    if isinstance(top, list):
        issues.extend(item for item in top if isinstance(item, dict))
    return issues


def _has_issue_code(issues: Iterable[dict[str, Any]], code: str) -> bool:
    return any(issue.get("code") == code for issue in issues)


def _preflight(health_report: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(health_report, dict):
        return {}
    preflight = health_report.get("preflight")
    return preflight if isinstance(preflight, dict) else {}


def _summary_status(health_report: dict[str, Any] | None) -> str | None:
    if not isinstance(health_report, dict):
        return None
    status = health_report.get("summary_status")
    return status if isinstance(status, str) else None


def _bootstrap_days(health_report: dict[str, Any] | None) -> int | None:
    if not isinstance(health_report, dict):
        return None
    for key in ("days", "window_days"):
        value = health_report.get(key)
        if isinstance(value, int):
            return value
    fetch = health_report.get("fetch")
    if isinstance(fetch, dict) and isinstance(fetch.get("days"), int):
        return fetch["days"]
    return None


def _evidence(
    *,
    source: str,
    locator: str,
    value: Any,
    observed_at: str,
) -> Evidence:
    return Evidence(
        source=source,
        locator=locator,
        value=value,
        observed_at=observed_at,
    )


def _result(
    *,
    check_id: str,
    status: str,
    confidence: Confidence = "HIGH",
    reason_code: str | None = None,
    evidence: list[Evidence] | None = None,
    ctx: FoundationGateContext,
    detail: str | None = None,
    root_cause_ids: list[str] | None = None,
) -> CheckResult:
    meta = foundation_gate_meta(check_id)
    catalogue_rcs = list(meta.get("root_cause_ids") or [])
    codes = list(root_cause_ids or [])
    if not codes and reason_code and str(reason_code).startswith("RC-"):
        codes = [str(reason_code)]
    if status == "FAIL" and not codes:
        codes = catalogue_rcs

    message = None
    suggested_fix = None
    severity = meta.get("severity")
    detection_logic = meta.get("detection_logic")
    rc_details: list[dict[str, str]] = []

    if status == "FAIL" and codes:
        primary = codes[0]
        reason_code = reason_code or primary
        rc_details = root_cause_details(codes)
        message = build_failure_message(
            check_id=check_id,
            root_cause_ids=codes,
            detail=detail,
        )
        suggested_fix = user_facing_suggested_fix(
            check_id,
            fallback=meta.get("suggested_fix")
            or (
                rc_details[0].get("standard_remediation_pattern")
                if rc_details
                else None
            ),
        )
    elif detail and status in {"NOT_CONNECTED", "UNKNOWN", "WARN"}:
        message = detail

    return CheckResult(
        check_id=check_id,
        status=status,  # type: ignore[arg-type]
        confidence=confidence,
        reason_code=reason_code,
        evidence=evidence or [],
        numeric_weight=0,
        tenant_id=ctx.tenant_id,
        run_id=ctx.run_id,
        evaluated_at=ctx.evaluated_at or _utcnow_iso(),
        scoring_model_version="DCS-1.0.0",
        severity=severity if status == "FAIL" else None,
        root_cause_ids=codes if status == "FAIL" else [],
        root_causes=rc_details if status == "FAIL" else [],
        message=message,
        suggested_fix=suggested_fix if status == "FAIL" else None,
        detection_logic=detection_logic if status == "FAIL" else None,
    )


def _locator(connector: ConnectorGateInput, suffix: str) -> str:
    run_id = connector.data_run_id if connector.data_run_id is not None else "unknown"
    return f"bootstrap:data_run:{run_id}:{suffix}"


def _granted_scopes(connector: ConnectorGateInput) -> set[str]:
    if connector.scopes_granted is not None:
        return {s.strip() for s in connector.scopes_granted if s and s.strip()}
    preflight = _preflight(connector.health_report)
    granted = preflight.get("scopes_granted") or []
    if isinstance(granted, list):
        return {str(s).strip() for s in granted if str(s).strip()}
    return set()


def evaluate_fd_01(ctx: FoundationGateContext) -> CheckResult:
    """Manago API authentication valid (sheet 02 detection logic)."""
    manago = ctx.manago
    observed = ctx.evaluated_at or _utcnow_iso()
    if manago is None or not manago.connected:
        return _result(
            check_id="FD-01",
            status="NOT_CONNECTED",
            reason_code="MANAGO_NOT_CONNECTED",
            confidence="HIGH",
            detail="Manago connector is not connected.",
            evidence=[
                _evidence(
                    source="manago_ai",
                    locator="connector:manago_ai:connected",
                    value=False,
                    observed_at=observed,
                )
            ],
            ctx=ctx,
        )

    # Prefer live signed test call result when provided (sheet 02).
    if manago.live_auth_ok is False:
        return _result(
            check_id="FD-01",
            status="FAIL",
            reason_code="RC-12",
            root_cause_ids=["RC-12"],
            detail=manago.live_auth_message or "Signed Manago test call did not return success=true.",
            evidence=[
                _evidence(
                    source="manago_ai",
                    locator="live:signed_read_call",
                    value={
                        "auth_ok": False,
                        "message": manago.live_auth_message,
                    },
                    observed_at=observed,
                )
            ],
            ctx=ctx,
        )

    if manago.live_auth_ok is True:
        return _result(
            check_id="FD-01",
            status="PASS",
            confidence="HIGH",
            evidence=[
                _evidence(
                    source="manago_ai",
                    locator="live:signed_read_call",
                    value={"auth_ok": True, "message": manago.live_auth_message},
                    observed_at=observed,
                )
            ],
            ctx=ctx,
        )

    issues = _issues_from_health(manago.health_report)
    preflight = _preflight(manago.health_report)
    auth_ok = preflight.get("auth_ok")
    if auth_ok is None:
        auth_ok = not _has_issue_code(issues, "AUTH_FAILED")

    if _has_issue_code(issues, "AUTH_FAILED") or auth_ok is False:
        issue_msg = next(
            (
                str(i.get("message") or "")
                for i in issues
                if i.get("code") == "AUTH_FAILED"
            ),
            "Manago authentication failed.",
        )
        return _result(
            check_id="FD-01",
            status="FAIL",
            reason_code="RC-12",
            root_cause_ids=["RC-12"],
            detail=issue_msg or "Manago authentication failed.",
            evidence=[
                _evidence(
                    source="manago_ai",
                    locator=_locator(manago, "preflight.auth_ok"),
                    value=False,
                    observed_at=observed,
                )
            ],
            ctx=ctx,
        )

    if manago.health_report is None and manago.connector_status not in {
        "connected",
        "degraded",
    }:
        return _result(
            check_id="FD-01",
            status="UNKNOWN",
            reason_code="MISSING_INPUT:health_report",
            confidence="LOW",
            detail="No live auth result or bootstrap health_report available.",
            evidence=[
                _evidence(
                    source="manago_ai",
                    locator=_locator(manago, "health_report"),
                    value=None,
                    observed_at=observed,
                )
            ],
            ctx=ctx,
        )

    return _result(
        check_id="FD-01",
        status="PASS",
        confidence="HIGH",
        evidence=[
            _evidence(
                source="manago_ai",
                locator=_locator(manago, "preflight.auth_ok"),
                value=True,
                observed_at=observed,
            )
        ],
        ctx=ctx,
    )


def evaluate_fd_02(ctx: FoundationGateContext) -> CheckResult:
    """Shopify API authentication and scopes (sheet 02)."""
    shopify = ctx.shopify
    observed = ctx.evaluated_at or _utcnow_iso()
    if shopify is None or not shopify.connected:
        return _result(
            check_id="FD-02",
            status="NOT_CONNECTED",
            reason_code="SHOPIFY_NOT_CONNECTED",
            confidence="HIGH",
            detail="Shopify connector is not connected.",
            evidence=[
                _evidence(
                    source="shopify",
                    locator="connector:shopify:connected",
                    value=False,
                    observed_at=observed,
                )
            ],
            ctx=ctx,
        )

    if shopify.live_auth_ok is False:
        return _result(
            check_id="FD-02",
            status="FAIL",
            reason_code="RC-12",
            root_cause_ids=["RC-12"],
            detail=shopify.live_auth_message or "Shopify token validation failed.",
            evidence=[
                _evidence(
                    source="shopify",
                    locator="live:shop_json",
                    value={
                        "auth_ok": False,
                        "message": shopify.live_auth_message,
                    },
                    observed_at=observed,
                )
            ],
            ctx=ctx,
        )

    issues = _issues_from_health(shopify.health_report)
    preflight = _preflight(shopify.health_report)
    auth_ok = shopify.live_auth_ok
    if auth_ok is None:
        auth_ok = preflight.get("auth_ok")
        if auth_ok is None:
            auth_ok = not _has_issue_code(issues, "AUTH_FAILED")

    if _has_issue_code(issues, "AUTH_FAILED") or auth_ok is False:
        return _result(
            check_id="FD-02",
            status="FAIL",
            reason_code="RC-12",
            root_cause_ids=["RC-12"],
            detail="Shopify OAuth token is invalid or Auth failed.",
            evidence=[
                _evidence(
                    source="shopify",
                    locator=_locator(shopify, "preflight.auth_ok"),
                    value=False,
                    observed_at=observed,
                )
            ],
            ctx=ctx,
        )

    granted = _granted_scopes(shopify)
    has_explicit_scopes = (
        shopify.scopes_granted is not None
        or ("scopes_granted" in preflight and isinstance(preflight.get("scopes_granted"), list))
    )
    scopes_ok = preflight.get("scopes_ok")
    scopes_missing_issue = _has_issue_code(issues, "SCOPES_MISSING")

    if has_explicit_scopes:
        missing = sorted(SHOPIFY_FD02_REQUIRED_SCOPES - granted)
        if missing:
            return _result(
                check_id="FD-02",
                status="FAIL",
                reason_code="RC-12",
                root_cause_ids=["RC-12"],
                detail="Missing required Shopify scopes: " + ", ".join(missing),
                evidence=[
                    _evidence(
                        source="shopify",
                        locator=_locator(shopify, "preflight.scopes"),
                        value={
                            "granted": sorted(granted),
                            "required": sorted(SHOPIFY_FD02_REQUIRED_SCOPES),
                            "missing": missing,
                        },
                        observed_at=observed,
                    )
                ],
                ctx=ctx,
            )
    elif scopes_missing_issue or scopes_ok is False:
        missing = [str(s) for s in (preflight.get("scopes_missing") or [])]
        required_missing = sorted(set(missing) & SHOPIFY_FD02_REQUIRED_SCOPES) or missing
        return _result(
            check_id="FD-02",
            status="FAIL",
            reason_code="RC-12",
            root_cause_ids=["RC-12"],
            detail=(
                "Missing required Shopify scopes: "
                + ", ".join(required_missing or sorted(SHOPIFY_FD02_REQUIRED_SCOPES))
            ),
            evidence=[
                _evidence(
                    source="shopify",
                    locator=_locator(shopify, "preflight.scopes"),
                    value={
                        "granted": sorted(granted),
                        "required": sorted(SHOPIFY_FD02_REQUIRED_SCOPES),
                        "missing": required_missing,
                    },
                    observed_at=observed,
                )
            ],
            ctx=ctx,
        )
    elif (
        shopify.live_auth_ok is None
        and shopify.health_report is None
        and shopify.connector_status not in {"connected", "degraded"}
    ):
        return _result(
            check_id="FD-02",
            status="UNKNOWN",
            reason_code="MISSING_INPUT:health_report",
            confidence="LOW",
            detail="No live Shopify auth result or bootstrap health_report available.",
            evidence=[
                _evidence(
                    source="shopify",
                    locator=_locator(shopify, "health_report"),
                    value=None,
                    observed_at=observed,
                )
            ],
            ctx=ctx,
        )
    elif not has_explicit_scopes:
        # Sheet requires verifying the four read scopes; do not fake PASS.
        return _result(
            check_id="FD-02",
            status="UNKNOWN",
            reason_code="MISSING_INPUT:scopes",
            confidence="LOW",
            detail=(
                "Shopify auth looks ok but granted scopes were not provided; "
                "cannot confirm read_customers/orders/products/inventory."
            ),
            evidence=[
                _evidence(
                    source="shopify",
                    locator=_locator(shopify, "preflight.scopes"),
                    value={
                        "granted": None,
                        "required": sorted(SHOPIFY_FD02_REQUIRED_SCOPES),
                    },
                    observed_at=observed,
                )
            ],
            ctx=ctx,
        )

    return _result(
        check_id="FD-02",
        status="PASS",
        confidence="HIGH",
        evidence=[
            _evidence(
                source="shopify",
                locator=_locator(shopify, "preflight.auth_and_scopes"),
                value={
                    "auth_ok": True,
                    "granted": sorted(granted),
                    "required": sorted(SHOPIFY_FD02_REQUIRED_SCOPES),
                },
                observed_at=observed,
            )
        ],
        ctx=ctx,
    )


def evaluate_fd_03(ctx: FoundationGateContext) -> CheckResult:
    """ERP feed reachable and parseable."""
    observed = ctx.evaluated_at or _utcnow_iso()
    if not ctx.erp_in_scope:
        return _result(
            check_id="FD-03",
            status="NOT_CONNECTED",
            reason_code="ERP_OUT_OF_SCOPE",
            confidence="HIGH",
            detail="ERP formally out of scope; Business Reality may be excluded.",
            evidence=[
                _evidence(
                    source="erp",
                    locator="scope:erp_in_scope",
                    value=False,
                    observed_at=observed,
                )
            ],
            ctx=ctx,
        )

    if not ctx.erp_connected:
        return _result(
            check_id="FD-03",
            status="NOT_CONNECTED",
            reason_code="ERP_NOT_CONNECTED",
            confidence="HIGH",
            detail="ERP is in scope but no ERP connector/feed is connected.",
            evidence=[
                _evidence(
                    source="erp",
                    locator="connector:erp:connected",
                    value=False,
                    observed_at=observed,
                )
            ],
            ctx=ctx,
        )

    # Sheet: retrievable + schema + rows > 0 + UTF-8
    if (
        ctx.erp_reachable is False
        or ctx.erp_schema_ok is False
        or ctx.erp_encoding_ok is False
        or (ctx.erp_row_count is not None and ctx.erp_row_count <= 0)
    ):
        detail_bits = []
        if ctx.erp_reachable is False:
            detail_bits.append("feed not retrievable")
        if ctx.erp_schema_ok is False:
            detail_bits.append("schema header mismatch")
        if ctx.erp_encoding_ok is False:
            detail_bits.append("encoding not valid UTF-8")
        if ctx.erp_row_count is not None and ctx.erp_row_count <= 0:
            detail_bits.append("row count is 0")
        return _result(
            check_id="FD-03",
            status="FAIL",
            reason_code="RC-12",
            root_cause_ids=["RC-06", "RC-12"],
            detail="; ".join(detail_bits) or "ERP feed failed parseability checks.",
            evidence=[
                _evidence(
                    source="erp",
                    locator="erp:feed",
                    value={
                        "reachable": ctx.erp_reachable,
                        "schema_ok": ctx.erp_schema_ok,
                        "encoding_ok": ctx.erp_encoding_ok,
                        "row_count": ctx.erp_row_count,
                    },
                    observed_at=observed,
                )
            ],
            ctx=ctx,
        )

    if ctx.erp_reachable is None and ctx.erp_row_count is None:
        return _result(
            check_id="FD-03",
            status="UNKNOWN",
            reason_code="MISSING_INPUT:erp_health",
            confidence="LOW",
            detail="ERP feed health inputs not provided.",
            evidence=[
                _evidence(
                    source="erp",
                    locator="erp:reachable",
                    value=None,
                    observed_at=observed,
                )
            ],
            ctx=ctx,
        )

    return _result(
        check_id="FD-03",
        status="PASS",
        confidence="HIGH",
        evidence=[
            _evidence(
                source="erp",
                locator="erp:feed",
                value={
                    "reachable": True,
                    "schema_ok": ctx.erp_schema_ok,
                    "encoding_ok": ctx.erp_encoding_ok,
                    "row_count": ctx.erp_row_count,
                },
                observed_at=observed,
            )
        ],
        ctx=ctx,
    )


def evaluate_fd_04(ctx: FoundationGateContext) -> CheckResult:
    """
    API rate-limit headroom measured (Excel FD-04 / RC-15).

    Requires a measured rate_budget per connected connector (import header /
    request sample or controlled probe). Hard rate-limit or zero headroom → FAIL.
    """
    from dataruns.dcs.rate_budget import budget_has_headroom

    observed = ctx.evaluated_at or _utcnow_iso()
    sources = [c for c in (ctx.manago, ctx.shopify) if c and c.connected]
    if not sources:
        return _result(
            check_id="FD-04",
            status="NOT_CONNECTED",
            reason_code="NO_CONNECTORS_FOR_RATE_LIMIT",
            confidence="HIGH",
            detail="No connected connectors available to measure rate-limit headroom.",
            evidence=[],
            ctx=ctx,
        )

    evidence: list[Evidence] = []
    saw_rate_limit = False
    missing_budget = False
    no_headroom = False
    budgets: dict[str, Any] = {}

    for connector in sources:
        issues = _issues_from_health(connector.health_report)
        hit = _has_issue_code(issues, "RATE_LIMIT")
        budget = connector.rate_budget
        if isinstance(budget, dict) and budget.get("hit_rate_limit") is True:
            hit = True
        saw_rate_limit = saw_rate_limit or hit
        if not isinstance(budget, dict) or not budget:
            missing_budget = True
        else:
            budgets[connector.platform] = budget
            if not budget_has_headroom(budget):
                no_headroom = True
        evidence.append(
            _evidence(
                source=connector.platform,
                locator=_locator(connector, "rate_limit"),
                value={"RATE_LIMIT": hit, "budget": budget},
                observed_at=observed,
            )
        )

    if saw_rate_limit or no_headroom:
        return _result(
            check_id="FD-04",
            status="FAIL",
            reason_code="RC-15",
            root_cause_ids=["RC-15"],
            detail=(
                "Hard rate-limit or insufficient API headroom; "
                "sweep must not emit a complete score."
            ),
            evidence=evidence,
            ctx=ctx,
        )

    if missing_budget:
        return _result(
            check_id="FD-04",
            status="UNKNOWN",
            reason_code="MISSING_INPUT:rate_budget",
            confidence="LOW",
            detail="Rate-limit headroom not measured for one or more connectors.",
            evidence=evidence,
            ctx=ctx,
        )

    return _result(
        check_id="FD-04",
        status="PASS",
        confidence="HIGH",
        evidence=evidence,
        ctx=ctx,
    )


def evaluate_fd_05(ctx: FoundationGateContext) -> CheckResult:
    """
    Historical data depth available (Excel: earliest timestamp per entity).

    Prefers DB-derived ``history_earliest`` / depth_days. Falls back to bootstrap
    window days (PRD MVP1) when entity timestamps are not yet available.
    """
    observed = ctx.evaluated_at or _utcnow_iso()
    sources = [c for c in (ctx.manago, ctx.shopify) if c and c.connected]
    if not sources:
        return _result(
            check_id="FD-05",
            status="NOT_CONNECTED",
            reason_code="NO_CONNECTORS_FOR_HISTORY",
            confidence="HIGH",
            detail="No connected connectors to assess historical depth.",
            evidence=[],
            ctx=ctx,
        )

    evidence: list[Evidence] = []
    any_pass = False
    any_measurable = False
    used_entity_timestamps = False
    history_extra = ctx.extra.get("history_depth")
    platform_depths: dict[str, Any] = {}
    if isinstance(history_extra, dict):
        platforms = history_extra.get("platforms")
        if isinstance(platforms, dict):
            platform_depths = platforms

    for connector in sources:
        report = connector.health_report
        summary = _summary_status(report)
        days = _bootstrap_days(report)
        earliest = connector.history_earliest
        depth = platform_depths.get(connector.platform)
        depth_days = depth.get("depth_days") if isinstance(depth, dict) else None
        meets = depth.get("meets_required") if isinstance(depth, dict) else None

        ok = False
        if earliest or isinstance(depth_days, int):
            any_measurable = True
            used_entity_timestamps = True
            if meets is True or (
                isinstance(depth_days, int)
                and depth_days >= ctx.bootstrap_days_required
            ):
                any_pass = True
                ok = True
            elif meets is False:
                # Measurable but too shallow — still counted below.
                pass
            elif earliest:
                # Earliest present but depth unknown → treat as measurable pass
                # only when bootstrap window also meets requirement.
                if days is None or days >= ctx.bootstrap_days_required:
                    any_pass = True
                    ok = True

        if summary in {"ok", "degraded"}:
            any_measurable = True
            if days is None or days >= ctx.bootstrap_days_required:
                any_pass = True
                ok = True

        evidence.append(
            _evidence(
                source=connector.platform,
                locator=_locator(connector, "history_depth"),
                value={
                    "summary_status": summary,
                    "days": days,
                    "earliest": earliest,
                    "depth_days": depth_days,
                    "meets_required": meets,
                    "ok": ok,
                },
                observed_at=observed,
            )
        )

    common_window = None
    if isinstance(history_extra, dict):
        common_window = history_extra.get("common_window_days")

    if any_pass:
        return _result(
            check_id="FD-05",
            status="PASS",
            confidence="HIGH" if used_entity_timestamps else "MEDIUM",
            detail=(
                f"Historical depth available; common_window_days={common_window}."
                if common_window is not None
                else None
            ),
            evidence=evidence,
            ctx=ctx,
        )

    if any_measurable:
        return _result(
            check_id="FD-05",
            status="FAIL",
            reason_code="RC-09",
            root_cause_ids=["RC-09"],
            detail=(
                "Historical depth below required window "
                f"({ctx.bootstrap_days_required}d) or incomplete history metadata."
            ),
            evidence=evidence,
            ctx=ctx,
        )

    return _result(
        check_id="FD-05",
        status="UNKNOWN",
        reason_code="MISSING_INPUT:bootstrap_depth",
        confidence="LOW",
        detail="No bootstrap success or per-entity earliest timestamps provided.",
        evidence=evidence,
        ctx=ctx,
    )


def evaluate_fd_06(ctx: FoundationGateContext) -> CheckResult:
    """
    Manago account/sub-account topology mapped (Excel FD-06 / RC-11).

    Requires enumerated owners (listByClient) + endpoint, and Excel relationship
    classification when more than one in-scope account exists.
    """
    manago = ctx.manago
    observed = ctx.evaluated_at or _utcnow_iso()
    if manago is None or not manago.connected:
        return _result(
            check_id="FD-06",
            status="NOT_CONNECTED",
            reason_code="MANAGO_NOT_CONNECTED",
            confidence="HIGH",
            detail="Manago is not connected yet.",
            evidence=[],
            ctx=ctx,
        )

    registry = ctx.extra.get("manago_topology")
    accounts = manago.topology_accounts
    if not accounts and isinstance(registry, dict):
        accounts = registry.get("accounts") if isinstance(registry.get("accounts"), list) else []
    accounts = accounts or []

    topology_error = ctx.extra.get("manago_topology_error")
    evidence_value: dict[str, Any] = {
        "topology_ok": manago.topology_ok,
        "account_count": len(accounts),
        "accounts": accounts,
        "registry": registry,
        "error": topology_error,
    }

    if manago.topology_ok is False:
        return _result(
            check_id="FD-06",
            status="FAIL",
            reason_code="RC-11",
            root_cause_ids=["RC-11"],
            detail=(
                str(topology_error)
                if topology_error
                else (
                    "We couldn't confirm how your Manago accounts are set up. "
                    "Choose a primary owner in Klints, and if you use more than "
                    "one account, tell us how they relate."
                )
            ),
            evidence=[
                _evidence(
                    source="manago_ai",
                    locator=_locator(manago, "topology"),
                    value=evidence_value,
                    observed_at=observed,
                )
            ],
            ctx=ctx,
        )

    if manago.topology_ok is True and accounts:
        return _result(
            check_id="FD-06",
            status="PASS",
            confidence="HIGH",
            evidence=[
                _evidence(
                    source="manago_ai",
                    locator=_locator(manago, "topology"),
                    value=evidence_value,
                    observed_at=observed,
                )
            ],
            ctx=ctx,
        )

    # Do not fake PASS from bootstrap summary — Excel requires a real account map.
    return _result(
        check_id="FD-06",
        status="UNKNOWN",
        reason_code="MISSING_INPUT:topology",
        confidence="LOW",
        detail="We haven't finished reading your Manago account list yet. Re-run the score after connecting Manago.",
        evidence=[
            _evidence(
                source="manago_ai",
                locator=_locator(manago, "topology_ok"),
                value=evidence_value,
                observed_at=observed,
            )
        ],
        ctx=ctx,
    )


def evaluate_fd_07(ctx: FoundationGateContext) -> CheckResult:
    """
    Manago site tracking code active (Excel FD-07).

    Combines:
    - VISIT / smclient / tracking_active signals (sheet 02)
    - Website HTML scrape for SalesManago markers on Company.domain
    """
    from dataruns.dcs.scrapers.company_website import (
        find_salesmanago_markers,
        is_storefront_password_wall,
        scrape_with_http_fallback,
        snippet_around_markers,
    )

    manago = ctx.manago
    observed = ctx.evaluated_at or _utcnow_iso()
    if manago is None or not manago.connected:
        return _result(
            check_id="FD-07",
            status="NOT_CONNECTED",
            reason_code="MANAGO_NOT_CONNECTED",
            confidence="HIGH",
            detail="Manago connector is not connected.",
            evidence=[],
            ctx=ctx,
        )

    evidence: list[Evidence] = []
    path_statuses: list[str] = []

    # --- Path A: VISIT / smclient / tracking_active ---
    signals_present = (
        manago.visit_events_recent is not None
        or manago.smclient_cookie_seen is not None
        or manago.tracking_active is not None
    )
    if signals_present:
        visits_ok = manago.visit_events_recent is True
        cookie_ok = manago.smclient_cookie_seen is True
        active_ok = manago.tracking_active is True
        measurable = manago.tracking_measurable is not False
        evidence.append(
            _evidence(
                source="manago_ai",
                locator=_locator(manago, "tracking"),
                value={
                    "visit_events_recent": manago.visit_events_recent,
                    "smclient_cookie_seen": manago.smclient_cookie_seen,
                    "tracking_active": manago.tracking_active,
                    "domains": manago.storefront_domains,
                },
                observed_at=observed,
            )
        )
        if not measurable:
            path_statuses.append("UNKNOWN")
        elif active_ok or (visits_ok and cookie_ok):
            path_statuses.append("PASS")
        elif active_ok is False or (visits_ok is False and cookie_ok is False):
            path_statuses.append("FAIL")
        else:
            path_statuses.append("UNKNOWN")
    elif manago.tracking_measurable is False:
        path_statuses.append("UNKNOWN")
        evidence.append(
            _evidence(
                source="manago_ai",
                locator=_locator(manago, "tracking"),
                value=None,
                observed_at=observed,
            )
        )

    host = ctx.company_website_domain

    # --- Path B: company website + Shopify storefront scrape ---
    scrape_hosts: list[str] = []
    if host:
        scrape_hosts.append(host)
    for extra in ctx.storefront_scrape_hosts or []:
        extra_host = str(extra or "").strip().lower().rstrip(".")
        if extra_host and extra_host not in scrape_hosts:
            scrape_hosts.append(extra_host)

    if scrape_hosts and not ctx.skip_website_scrape:
        any_scrape_pass = False
        any_scrape_fail = False
        any_scrape_unknown = False
        for scrape_host in scrape_hosts:
            scrape = scrape_with_http_fallback(
                scrape_host, opener=ctx.website_scrape_opener
            )
            if not scrape.ok and scrape.status_code is None:
                any_scrape_unknown = True
                evidence.append(
                    _evidence(
                        source="company_website",
                        locator=f"https://{scrape_host}/",
                        value={"error": scrape.error or "WEBSITE_UNREACHABLE"},
                        observed_at=observed,
                    )
                )
                continue
            if not scrape.ok and scrape.status_code is not None:
                any_scrape_unknown = True
                evidence.append(
                    _evidence(
                        source="company_website",
                        locator=scrape.final_url or f"https://{scrape_host}/",
                        value={
                            "status_code": scrape.status_code,
                            "error": scrape.error or "WEBSITE_HTTP_ERROR",
                        },
                        observed_at=observed,
                    )
                )
                continue
            markers = find_salesmanago_markers(scrape.html or "")
            password_wall = is_storefront_password_wall(
                final_url=scrape.final_url,
                html=scrape.html,
            )
            evidence.append(
                _evidence(
                    source="company_website",
                    locator=scrape.final_url or f"https://{scrape_host}/",
                    value={
                        "final_url": scrape.final_url,
                        "status_code": scrape.status_code,
                        "markers_matched": markers,
                        "snippet": snippet_around_markers(
                            scrape.html or "", markers
                        ),
                        "scrape_host": scrape_host,
                        "password_wall": password_wall,
                    },
                    observed_at=observed,
                )
            )
            if markers:
                any_scrape_pass = True
            elif password_wall:
                # Cannot verify theme scripts behind Shopify password gate.
                any_scrape_unknown = True
            else:
                any_scrape_fail = True
        if any_scrape_pass:
            path_statuses.append("PASS")
        elif any_scrape_fail:
            path_statuses.append("FAIL")
        elif any_scrape_unknown:
            path_statuses.append("UNKNOWN")
    elif not scrape_hosts:
        # Domain missing is only UNKNOWN for scrape path; signals may still pass.
        evidence.append(
            _evidence(
                source="company_website",
                locator="company:domain",
                value=None,
                observed_at=observed,
            )
        )

    if "PASS" in path_statuses:
        return _result(
            check_id="FD-07",
            status="PASS",
            confidence="HIGH",
            evidence=evidence,
            ctx=ctx,
        )
    if "FAIL" in path_statuses:
        return _result(
            check_id="FD-07",
            status="FAIL",
            reason_code="RC-12",
            root_cause_ids=["RC-12"],
            detail=(
                "Monitoring code inactive, VISIT/smclient signals missing, "
                "or SalesManago tracker markers absent on company website."
            ),
            evidence=evidence,
            ctx=ctx,
        )
    return _result(
        check_id="FD-07",
        status="UNKNOWN",
        reason_code="MISSING_INPUT:tracking",
        confidence="LOW",
        detail="Tracking not measurable; do not fake PASS.",
        evidence=evidence,
        ctx=ctx,
    )


FOUNDATION_EXECUTORS = {
    "FD-01": evaluate_fd_01,
    "FD-02": evaluate_fd_02,
    "FD-03": evaluate_fd_03,
    "FD-04": evaluate_fd_04,
    "FD-05": evaluate_fd_05,
    "FD-06": evaluate_fd_06,
    "FD-07": evaluate_fd_07,
}


def evaluate_foundation_gates(ctx: FoundationGateContext) -> list[CheckResult]:
    """Evaluate FD-01…FD-07 in order."""
    return [FOUNDATION_EXECUTORS[check_id](ctx) for check_id in sorted(FOUNDATION_EXECUTORS)]
