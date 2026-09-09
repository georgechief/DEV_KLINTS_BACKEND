"""Overview Export brief PDF renderer — client feedback v1.

Shared by Overview Export brief and Data Consistency Export fix plan
(report_profile=overview_brief). Reuses layout helpers from render_assessment_pdf.
"""

from __future__ import annotations

from io import BytesIO
from typing import Any

from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer

from dataruns.reports.humanize import (
    connector_strip_labels,
    format_customer_title,
    format_generated_at,
    format_impact_overview,
)
from dataruns.reports.payload import REMEDIATION_FALLBACK
from dataruns.reports.remediation_ai import compact_suggested_fix_for_pdf
from dataruns.reports.render_pdf import (
    BOTTOM,
    CONTENT_W,
    LEFT,
    RIGHT,
    TOP,
    PdfRenderError,
    _banner,
    _company_line,
    _draw_chrome,
    _escape,
    _hero_stats,
    _narrative_block,
    _period_line,
    _severity_short,
    _styles,
    REMEDIATION_TABLE_COL_LIMITS,
    _table,
    _text,
)


def _overview_remediation_rows(items: list[Any]) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for row in items:
        if not isinstance(row, dict):
            continue
        suggested = _text(row.get("suggested_fix"), default="")
        if not suggested or suggested == REMEDIATION_FALLBACK:
            continue
        owner = _text(row.get("fix_owner"), default="")
        fix_type = _text(row.get("fix_type"), default="")
        rows.append(
            [
                row.get("check_id"),
                compact_suggested_fix_for_pdf(suggested),
                owner if owner != REMEDIATION_FALLBACK else "",
                fix_type if fix_type != REMEDIATION_FALLBACK else "",
                row.get("fix_href"),
            ]
        )
    return rows


def _overview_money(impact: dict[str, Any]) -> str:
    return format_impact_overview(
        impact.get("estimate"),
        impact.get("currency"),
        empty="Not available",
    )


def _architecture_incomplete(architecture: dict[str, Any]) -> bool:
    mode = str(architecture.get("mode") or "").upper()
    if mode == "INCOMPLETE":
        return True
    if architecture.get("weighted_score") is None and architecture.get("assessed"):
        return True
    return False


def render_overview_brief_pdf(
    payload: dict[str, Any],
    *,
    ai_narratives: dict[str, Any] | None = None,
) -> bytes:
    if not isinstance(payload, dict) or not isinstance(payload.get("content"), dict):
        raise PdfRenderError("Report payload is missing content.")

    content = payload["content"]
    ctx = content.get("render_context") if isinstance(content.get("render_context"), dict) else {}
    dcs = content.get("dcs") if isinstance(content.get("dcs"), dict) else {}
    architecture = (
        content.get("architecture") if isinstance(content.get("architecture"), dict) else {}
    )
    impact = (
        content.get("business_impact")
        if isinstance(content.get("business_impact"), dict)
        else {}
    )
    register = (
        content.get("check_register")
        if isinstance(content.get("check_register"), dict)
        else {}
    )
    remediation = (
        content.get("remediation") if isinstance(content.get("remediation"), dict) else {}
    )
    plan = (
        content.get("execution_plan")
        if isinstance(content.get("execution_plan"), dict)
        else {}
    )

    styles = _styles()
    payload_hash = _text(payload.get("payload_hash"), default="")
    footer_hash = payload_hash[:12] if payload_hash else "-"
    template_version = _text(
        payload.get("template_version"),
        default="KLINTS-OVERVIEW-BRIEF-1.0.0",
    )
    report_id = _text(payload.get("report_id"), default="")
    short_id = report_id.replace("-", "")[:8] if report_id else "-"

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=(595.27, 841.89),
        leftMargin=LEFT,
        rightMargin=RIGHT,
        topMargin=TOP,
        bottomMargin=BOTTOM,
        title="Data consistency assessment brief",
        author="Klints",
    )
    story: list[Any] = []

    company = _text(ctx.get("company_name"), default="Company")
    generated = format_generated_at(_text(payload.get("created_at"), default="")) or _text(
        payload.get("created_at")
    )
    score = dcs.get("headline_score")
    open_checks = register.get("open_checks") if isinstance(register.get("open_checks"), list) else []
    top_issues = content.get("top_issues") if isinstance(content.get("top_issues"), list) else []

    # Brief header (#7) — same page as In brief + stats (no blank cover / no PageBreak)
    story.append(Paragraph("KLINTS", styles["kicker"]))
    story.append(
        Paragraph(
            _escape("Data consistency assessment brief", limit=120),
            styles["h1"],
        )
    )
    story.append(
        Paragraph(
            _escape(f"Prepared for {company}", limit=160),
            styles["body"],
        )
    )
    if ctx.get("company_domain"):
        story.append(
            Paragraph(
                _escape(_company_line(company, ctx.get("company_domain")), limit=160),
                styles["muted"],
            )
        )
    story.append(
        Paragraph(
            _escape(
                f"{_period_line(ctx, _text(payload.get('data_as_of')))}  ·  Generated {generated}",
                limit=260,
            ),
            styles["muted"],
        )
    )
    story.append(Spacer(1, 3 * mm))

    narrative = _narrative_block(ai_narratives)
    if narrative:
        story.append(Paragraph("In brief", styles["h2"]))
        if narrative["exec_summary"]:
            story.append(Paragraph(_escape(narrative["exec_summary"], limit=2000), styles["body"]))
        if narrative["top_themes"]:
            theme_text = "  ·  ".join(narrative["top_themes"][:8])
            story.append(Paragraph(_escape(theme_text, limit=800), styles["muted"]))
        if narrative["recommended_focus"]:
            story.append(
                Paragraph(_escape(narrative["recommended_focus"], limit=800), styles["body"])
            )
        story.append(Spacer(1, 2.5 * mm))

    # No INCOMPLETE banner here (#4) — moved to Scope & method
    story.append(
        _hero_stats(
            score=_text(score, default="Not scored"),
            state=_text(dcs.get("state")),
            open_count=_text(len(open_checks)),
            at_stake=_overview_money(impact),
            styles=styles,
        )
    )
    story.append(Spacer(1, 3 * mm))

    if top_issues:
        story.append(Paragraph("Top risks", styles["h2"]))
        for index, issue in enumerate(top_issues[:5], start=1):
            if not isinstance(issue, dict):
                continue
            story.append(
                Paragraph(
                    _escape(
                        f"{index}. {_text(issue.get('check_id'))} · "
                        f"{_text(issue.get('severity'))} - {_text(issue.get('summary'))}",
                        limit=340,
                    ),
                    styles["body"],
                )
            )

    story.append(Paragraph("Score & dimensions", styles["h2"]))
    coverage = dcs.get("coverage")
    coverage_pct = "-"
    if isinstance(coverage, (int, float)):
        cov = float(coverage)
        coverage_pct = f"{round(cov * 100 if cov <= 1 else cov)}%"
    story.append(
        Paragraph(
            _escape(f"Overall {_text(score)}  ·  coverage {coverage_pct}", limit=160),
            styles["body"],
        )
    )
    dim_scores = dcs.get("dimension_scores") if isinstance(dcs.get("dimension_scores"), dict) else {}
    if dim_scores:
        dim_rows = [[name, _text(value)] for name, value in sorted(dim_scores.items())]
        story.append(
            _table(
                ["Dimension", "Score"],
                dim_rows,
                styles,
                [CONTENT_W * 0.72, CONTENT_W * 0.28],
            )
        )
    summary = dcs.get("check_summary") if isinstance(dcs.get("check_summary"), dict) else {}
    if summary:
        story.append(
            Paragraph(
                _escape(
                    "  ·  ".join(
                        f"{key} {summary.get(key, 0)}"
                        for key in (
                            "PASS",
                            "WARN",
                            "FAIL",
                            "UNKNOWN",
                            "NOT_CONNECTED",
                            "NOT_APPLICABLE",
                        )
                    ),
                    limit=240,
                ),
                styles["muted"],
            )
        )

    # What's wrong (#3 — conditional impact column)
    story.append(Paragraph("What's wrong", styles["h2"]))
    if open_checks:
        impact_values = [
            row.get("revenue_impact")
            for row in open_checks
            if isinstance(row, dict) and row.get("revenue_impact") not in (None, 0, "0", 0.0)
        ]
        show_impact = len(impact_values) > 0
        if show_impact:
            rows = [
                [
                    row.get("check_id"),
                    format_customer_title(str(row.get("title") or "")),
                    row.get("systems") or "-",
                    str(row.get("status") or "").upper() or "-",
                    _severity_short(row.get("severity")),
                    row.get("whats_wrong"),
                    format_impact_overview(row.get("revenue_impact"), row.get("currency")),
                    row.get("priority_class") or row.get("priority_score"),
                ]
                for row in open_checks
                if isinstance(row, dict)
            ]
            story.append(
                _table(
                    ["ID", "Title", "Systems", "Status", "Sev", "What's wrong", "Impact", "Prio"],
                    rows,
                    styles,
                    [
                        CONTENT_W * 0.08,
                        CONTENT_W * 0.14,
                        CONTENT_W * 0.13,
                        CONTENT_W * 0.07,
                        CONTENT_W * 0.05,
                        CONTENT_W * 0.28,
                        CONTENT_W * 0.10,
                        CONTENT_W * 0.15,
                    ],
                )
            )
            method_note = ctx.get("impact_method_note") or impact.get("method_note")
            if method_note:
                story.append(Paragraph(_escape(str(method_note), limit=240), styles["muted"]))
        else:
            rows = [
                [
                    row.get("check_id"),
                    format_customer_title(str(row.get("title") or "")),
                    row.get("systems") or "-",
                    str(row.get("status") or "").upper() or "-",
                    _severity_short(row.get("severity")),
                    row.get("whats_wrong"),
                    row.get("priority_class") or row.get("priority_score"),
                ]
                for row in open_checks
                if isinstance(row, dict)
            ]
            story.append(
                _table(
                    ["ID", "Title", "Systems", "Status", "Sev", "What's wrong", "Prio"],
                    rows,
                    styles,
                    [
                        CONTENT_W * 0.08,
                        CONTENT_W * 0.16,
                        CONTENT_W * 0.14,
                        CONTENT_W * 0.08,
                        CONTENT_W * 0.06,
                        CONTENT_W * 0.30,
                        CONTENT_W * 0.18,
                    ],
                )
            )
    else:
        story.append(Paragraph("No open FAIL or WARN checks in this run.", styles["body"]))

    # What to fix (#1 — AI piped in compose)
    items = remediation.get("items") if isinstance(remediation.get("items"), list) else []
    pdf_fix_rows = _overview_remediation_rows(items)
    if pdf_fix_rows:
        fix_block: list[Any] = [Paragraph("What to fix", styles["h2"])]
        fix_block.append(
            _table(
                ["ID", "Suggested fix", "Owner", "Type", "Path"],
                pdf_fix_rows,
                styles,
                [
                    CONTENT_W * 0.10,
                    CONTENT_W * 0.42,
                    CONTENT_W * 0.18,
                    CONTENT_W * 0.16,
                    CONTENT_W * 0.14,
                ],
                col_limits=REMEDIATION_TABLE_COL_LIMITS,
            )
        )
        story.append(KeepTogether(fix_block))

    # Architecture (#5 — suppress when INCOMPLETE)
    if not _architecture_incomplete(architecture):
        story.append(Paragraph("Architecture", styles["h2"]))
        if architecture.get("assessed"):
            weighted = architecture.get("weighted_score")
            weighted_s = _text(weighted, default="not scored")
            story.append(
                Paragraph(
                    _escape(
                        f"Mode {_text(architecture.get('mode'))}  ·  "
                        f"weighted {weighted_s}  ·  "
                        f"{_text(architecture.get('summary'))}",
                        limit=280,
                    ),
                    styles["body"],
                )
            )
            reason = architecture.get("incomplete_reason")
            if reason:
                story.append(Paragraph(_escape(reason, limit=280), styles["muted"]))
            fix_first = architecture.get("fix_first_assets")
            if isinstance(fix_first, list) and fix_first:
                names = ", ".join(_text(name) for name in fix_first[:3] if name)
                if names:
                    story.append(
                        Paragraph(
                            _escape(f"Top fix-first assets: {names}", limit=240),
                            styles["muted"],
                        )
                    )
            verdicts = architecture.get("verdict_counts")
            if isinstance(verdicts, dict) and verdicts and any(verdicts.values()):
                story.append(
                    _table(
                        ["Keep", "Improve", "Fix-first", "Consolidate", "Retire"],
                        [
                            [
                                verdicts.get("KEEP", 0),
                                verdicts.get("KEEP_IMPROVE", 0),
                                verdicts.get("FIX_FIRST", 0),
                                verdicts.get("CONSOLIDATE", 0),
                                verdicts.get("RETIRE_CANDIDATE", 0),
                            ]
                        ],
                        styles,
                        [CONTENT_W / 5] * 5,
                    )
                )

    story.append(Paragraph("Prioritised execution plan", styles["h2"]))
    tasks = plan.get("tasks") if isinstance(plan.get("tasks"), list) else []
    if tasks:
        rows = [
            [
                row.get("rank"),
                row.get("check_id"),
                format_customer_title(str(row.get("title") or "")),
                row.get("priority_class"),
                row.get("priority_score"),
            ]
            for row in tasks
            if isinstance(row, dict)
        ]
        story.append(
            _table(
                ["Rank", "ID", "Title", "Class", "Score"],
                rows,
                styles,
                [
                    CONTENT_W * 0.10,
                    CONTENT_W * 0.14,
                    CONTENT_W * 0.46,
                    CONTENT_W * 0.14,
                    CONTENT_W * 0.16,
                ],
            )
        )
    else:
        reason = plan.get("empty_reason") or "no_open_issues"
        story.append(
            Paragraph(_escape(f"Plan is empty ({reason}).", limit=160), styles["body"])
        )

    # Next-step block (#7)
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("Next steps", styles["h2"]))
    story.append(
        Paragraph(
            _escape(
                "Review What to fix above, open each issue on Fix to inspect evidence, "
                "approve writebacks where available, and track progress from Overview.",
                limit=400,
            ),
            styles["body"],
        )
    )

    # Scope & method (#2, #4 — incomplete banner here)
    story.append(Paragraph("Scope & method", styles["h2"]))
    incomplete_banner = dcs.get("incomplete_banner")
    if incomplete_banner or ctx.get("show_incomplete_banner"):
        banner_text = incomplete_banner or "Incomplete assessment — treat this score as directional."
        story.append(_banner(str(banner_text), styles))
        story.append(Spacer(1, 2 * mm))
    connectors = ctx.get("connector_status")
    if isinstance(connectors, list) and connectors:
        story.append(
            Paragraph(
                _escape(connector_strip_labels(connectors), limit=240),
                styles["body"],
            )
        )
    snapshots = payload.get("input_snapshot_ids") or []
    if snapshots:
        for item in snapshots:
            story.append(
                Paragraph(_escape(f"Snapshot {_text(item)}", limit=200), styles["muted"])
            )
    else:
        story.append(Paragraph("Snapshots: -", styles["muted"]))
    story.append(
        Paragraph(
            _escape(
                _text(
                    ctx.get("aggregate_notice"),
                    default="Aggregate report - no contact-level PII",
                ),
                limit=200,
            ),
            styles["muted"],
        )
    )
    story.append(
        Paragraph(
            _escape(
                f"payload_hash {footer_hash}  ·  template {template_version}  ·  report {short_id}",
                limit=200,
            ),
            styles["muted"],
        )
    )

    # Appendix (#6 — coverage tables only here)
    healthy = register.get("healthy_checks") if isinstance(register.get("healthy_checks"), list) else []
    coverage_checks = (
        register.get("coverage_checks")
        if isinstance(register.get("coverage_checks"), list)
        else []
    )
    if healthy or coverage_checks:
        story.append(PageBreak())
        story.append(Paragraph("Appendix", styles["h2"]))
        if healthy:
            story.append(Paragraph("Healthy checks", styles["h2"]))
            rows = [
                [
                    row.get("check_id"),
                    format_customer_title(str(row.get("title") or "")),
                    row.get("status"),
                ]
                for row in healthy
                if isinstance(row, dict)
            ]
            story.append(
                _table(
                    ["ID", "Title", "Status"],
                    rows,
                    styles,
                    [CONTENT_W * 0.18, CONTENT_W * 0.64, CONTENT_W * 0.18],
                )
            )
        if coverage_checks:
            not_connected = [
                row
                for row in coverage_checks
                if isinstance(row, dict)
                and str(row.get("status") or "").upper() == "NOT_CONNECTED"
            ]
            unknown = [
                row
                for row in coverage_checks
                if isinstance(row, dict)
                and str(row.get("status") or "").upper() != "NOT_CONNECTED"
            ]
            if not_connected:
                story.append(Paragraph("Coverage — not connected", styles["h2"]))
                rows = [
                    [
                        row.get("check_id"),
                        format_customer_title(str(row.get("title") or "")),
                        row.get("status"),
                    ]
                    for row in not_connected
                    if isinstance(row, dict)
                ]
                story.append(
                    _table(
                        ["ID", "Title", "Status"],
                        rows,
                        styles,
                        [CONTENT_W * 0.18, CONTENT_W * 0.64, CONTENT_W * 0.18],
                    )
                )
            if unknown:
                story.append(Paragraph("Coverage — unknown / other", styles["h2"]))
                rows = [
                    [
                        row.get("check_id"),
                        format_customer_title(str(row.get("title") or "")),
                        row.get("status"),
                    ]
                    for row in unknown
                    if isinstance(row, dict)
                ]
                story.append(
                    _table(
                        ["ID", "Title", "Status"],
                        rows,
                        styles,
                        [CONTENT_W * 0.18, CONTENT_W * 0.64, CONTENT_W * 0.18],
                    )
                )

    def on_page(canvas, doc_obj):  # noqa: ANN001
        _draw_chrome(canvas, doc_obj, footer_hash=footer_hash, template_version=template_version)

    try:
        doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    except Exception as exc:
        raise PdfRenderError("Overview brief PDF render failed.") from exc

    pdf_bytes = buffer.getvalue()
    buffer.close()
    if not pdf_bytes.startswith(b"%PDF"):
        raise PdfRenderError("Renderer produced an empty document.")
    return pdf_bytes
