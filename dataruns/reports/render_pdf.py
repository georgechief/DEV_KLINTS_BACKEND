"""Render assessment PDF from a stored payload (PRD-RPT-01 / RPT-01B).

Renderer: ReportLab (sync, Windows-friendly, no HTML engine).
PDF bytes are built in memory — never written to media/S3.
"""

from __future__ import annotations

from io import BytesIO
from typing import Any
import re

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from reportlab import rl_config

from dataruns.reports.humanize import (
    connector_strip_labels,
    format_customer_title,
    format_generated_at,
    format_impact_cell,
)

# Same payload should produce stable PDF bytes (PRD-RPT-01 replay).
rl_config.invariant = 1

INK = colors.HexColor("#1C1917")
SAND = colors.HexColor("#F4EFE6")
ACCENT = colors.HexColor("#B4532A")
MUTED = colors.HexColor("#78716C")
LINE = colors.HexColor("#E7E0D4")
BANNER_BG = colors.HexColor("#F8E9DF")
WHITE = colors.white

PAGE_W, PAGE_H = A4
LEFT = 16 * mm
RIGHT = 16 * mm
TOP = 22 * mm
BOTTOM = 16 * mm
CONTENT_W = 178 * mm


class PdfRenderError(Exception):
    """Raised when stored payload cannot be rendered."""


_WINANSI_TRANSLATE = str.maketrans(
    {
        "\u2014": "-",
        "\u2013": "-",
        "\u2012": "-",
        "\u2010": "-",
        "\u2212": "-",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2026": "...",
        "\u00a0": " ",
    }
)


def _winansi_safe(token: str) -> str:
    token = token.translate(_WINANSI_TRANSLATE)
    return token.encode("cp1252", errors="replace").decode("cp1252")


def _text(value: Any, default: str = "-") -> str:
    if value is None:
        token = default
    elif isinstance(value, float):
        if value.is_integer():
            token = str(int(value))
        else:
            token = f"{value:.2f}"
    else:
        token = str(value).strip() or default
    return _winansi_safe(token)


def _break_long_tokens(token: str, *, width: int = 36) -> str:
    """Prefer wrap at hyphens (ReportLab &shy;) so UUID lines do not look spaced."""
    shy = "&shy;"
    parts: list[str] = []
    for word in token.split(" "):
        if len(word) <= width:
            parts.append(word)
            continue
        if "-" in word:
            parts.append(word.replace("-", "-" + shy))
            continue
        chunks = [word[i : i + width] for i in range(0, len(word), width)]
        parts.append(shy.join(chunks))
    return " ".join(parts)


def _escape(value: Any, default: str = "-", *, limit: int = 280) -> str:
    token = _text(value, default=default)
    token = (
        token.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    if len(token) > limit:
        token = token[: limit - 3] + "..."
    return _break_long_tokens(token)


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "kicker": ParagraphStyle(
            "Kicker",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=8,
            textColor=ACCENT,
            spaceAfter=1.5 * mm,
        ),
        "h1": ParagraphStyle(
            "H1",
            parent=base["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=20,
            leading=24,
            textColor=INK,
            spaceAfter=2.5 * mm,
        ),
        "h2": ParagraphStyle(
            "H2",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=12,
            leading=16,
            textColor=INK,
            spaceBefore=6 * mm,
            spaceAfter=2.5 * mm,
        ),
        "body": ParagraphStyle(
            "Body",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=9.5,
            leading=13,
            textColor=INK,
            alignment=TA_LEFT,
            spaceAfter=1.8 * mm,
        ),
        "muted": ParagraphStyle(
            "Muted",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=8,
            leading=11,
            textColor=MUTED,
            spaceAfter=1.4 * mm,
        ),
        "banner": ParagraphStyle(
            "Banner",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=8.5,
            leading=11.5,
            textColor=INK,
            spaceAfter=0,
        ),
        "cell": ParagraphStyle(
            "Cell",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=7,
            leading=9.5,
            textColor=INK,
        ),
        "th": ParagraphStyle(
            "Th",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=7,
            leading=9.5,
            textColor=INK,
        ),
        "stat": ParagraphStyle(
            "Stat",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=18,
            leading=22,
            textColor=INK,
        ),
        "stat_secondary": ParagraphStyle(
            "StatSecondary",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=12,
            leading=15,
            textColor=INK,
        ),
        "stat_label": ParagraphStyle(
            "StatLabel",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=7.5,
            leading=10,
            textColor=MUTED,
        ),
        "chip": ParagraphStyle(
            "Chip",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8,
            leading=10,
            textColor=ACCENT,
        ),
    }


def _draw_chrome(canvas, doc, *, footer_hash: str, template_version: str) -> None:
    canvas.saveState()
    canvas.setFillColor(INK)
    canvas.rect(0, PAGE_H - 12 * mm, PAGE_W, 12 * mm, fill=1, stroke=0)
    canvas.setFillColor(WHITE)
    canvas.setFont("Helvetica", 8)
    canvas.drawString(LEFT, PAGE_H - 7.5 * mm, "Klints  ·  Data consistency assessment")
    canvas.setFillColor(ACCENT)
    canvas.rect(0, 0, PAGE_W, 8 * mm, fill=1, stroke=0)
    canvas.setFillColor(WHITE)
    canvas.setFont("Helvetica", 7)
    page = canvas.getPageNumber()
    canvas.drawString(LEFT, 3 * mm, f"p.{page}")
    canvas.drawRightString(
        PAGE_W - RIGHT,
        3 * mm,
        f"{footer_hash}  ·  {template_version}",
    )
    canvas.restoreState()


def _table(headers: list[str], rows: list[list[Any]], styles, col_widths: list[float]) -> Table:
    if not rows:
        rows = [["-"] * len(headers)]
    header = [Paragraph(_escape(h, limit=80), styles["th"]) for h in headers]
    body = []
    for row in rows:
        padded = list(row) + [""] * max(0, len(headers) - len(row))
        body.append(
            [
                Paragraph(_escape(cell, limit=260), styles["cell"])
                for cell in padded[: len(headers)]
            ]
        )
    table = Table([header, *body], colWidths=col_widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), SAND),
                ("TEXTCOLOR", (0, 0), (-1, 0), INK),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 7),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("GRID", (0, 0), (-1, -1), 0.4, LINE),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, colors.HexColor("#FAF7F2")]),
            ]
        )
    )
    return table


def _hero_stats(
    *,
    score: str,
    state: str,
    open_count: str,
    at_stake: str,
    styles,
) -> Table:
    values = [
        Paragraph(_escape(score, limit=24), styles["stat"]),
        Paragraph(_escape(state, limit=28), styles["stat_secondary"]),
        Paragraph(_escape(open_count, limit=16), styles["stat_secondary"]),
        Paragraph(_escape(at_stake, limit=32), styles["stat_secondary"]),
    ]
    labels = [
        Paragraph("DCS score", styles["stat_label"]),
        Paragraph("State", styles["stat_label"]),
        Paragraph("Open FAIL+WARN", styles["stat_label"]),
        Paragraph("At stake", styles["stat_label"]),
    ]
    widths = [
        CONTENT_W * 0.28,
        CONTENT_W * 0.26,
        CONTENT_W * 0.22,
        CONTENT_W * 0.24,
    ]
    table = Table([values, labels], colWidths=widths)
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BACKGROUND", (0, 0), (-1, -1), SAND),
                ("BOX", (0, 0), (-1, -1), 0, SAND),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    return table


def _banner(text: str, styles) -> Table:
    inner = Paragraph(_escape(text, limit=420), styles["banner"])
    table = Table([[inner]], colWidths=[CONTENT_W])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), BANNER_BG),
                ("BOX", (0, 0), (-1, -1), 0.6, ACCENT),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    return table


def _period_line(ctx: dict[str, Any], data_as_of: str) -> str:
    start = ctx.get("period_from")
    end = ctx.get("period_to")
    if start and end:
        return f"Period {start} - {end}"
    if data_as_of:
        generated = format_generated_at(data_as_of) or data_as_of
        return f"Run of {generated}"
    return "Period not specified"


def _money(impact: dict[str, Any]) -> str:
    estimate = impact.get("estimate")
    currency = impact.get("currency") or ""
    if estimate is None:
        return "Not available"
    return format_impact_cell(estimate, currency, empty="Not available")


def _company_line(company: str, domain: Any) -> str:
    domain_s = _text(domain, default="")
    if not domain_s or domain_s == "-":
        return company
    return f"{company}  ·  {domain_s}"


def _severity_short(value: Any) -> str:
    token = str(value or "").strip().lower()
    mapping = {
        "critical": "crit",
        "high": "high",
        "medium": "med",
        "low": "low",
        "informational": "info",
    }
    return mapping.get(token, token[:4] or "-")


def _dimension_short(value: Any) -> str:
    """Fixed short labels so narrow columns never mid-word wrap (e.g. Measureme/nt)."""
    token = _text(value, default="")
    if not token or token == "-":
        return "-"
    lower = token.lower()
    # Strip leading "01 " style prefixes
    lower = re.sub(r"^\d+\s+", "", lower)
    mapping = (
        ("customer identity", "Identity"),
        ("lifecycle event", "Lifecycle"),
        ("product & transaction", "Product"),
        ("product and transaction", "Product"),
        ("segment & property", "Segment"),
        ("segment and property", "Segment"),
        ("channel & consent", "Consent"),
        ("channel and consent", "Consent"),
        ("measurement", "Measure"),
        ("foundation", "Found."),
        ("business", "Biz"),
    )
    for needle, label in mapping:
        if needle in lower:
            return label
    parts = token.split()
    if parts and parts[0][:1].isdigit():
        parts = parts[1:]
    if not parts:
        return token[:10]
    return parts[0][:10]


def render_assessment_pdf(payload: dict[str, Any]) -> bytes:
    """Render PDF bytes from an immutable composed payload. No live DCS reads."""
    if not isinstance(payload, dict) or not isinstance(payload.get("content"), dict):
        raise PdfRenderError("Report payload is missing content.")

    content = payload["content"]
    ctx = content.get("render_context") if isinstance(content.get("render_context"), dict) else {}
    dcs = content.get("dcs") if isinstance(content.get("dcs"), dict) else {}
    issue_summary = (
        content.get("issue_summary") if isinstance(content.get("issue_summary"), dict) else {}
    )
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
    template_version = _text(payload.get("template_version"), default="KLINTS-REPORT-1.1.0")
    report_id = _text(payload.get("report_id"), default="")
    short_id = report_id.replace("-", "")[:8] if report_id else "-"

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=LEFT,
        rightMargin=RIGHT,
        topMargin=TOP,
        bottomMargin=BOTTOM,
        title="Data consistency assessment report",
        author="Klints",
    )
    story: list[Any] = []

    title = _text(ctx.get("report_title"), default="Data consistency assessment report")
    company = _text(ctx.get("company_name"), default="Company")
    story.append(Paragraph("KLINTS", styles["kicker"]))
    story.append(Paragraph(_escape(title, limit=120), styles["h1"]))
    story.append(
        Paragraph(_escape(_company_line(company, ctx.get("company_domain")), limit=160), styles["body"])
    )
    generated = format_generated_at(_text(payload.get("created_at"), default="")) or _text(
        payload.get("created_at")
    )
    story.append(
        Paragraph(
            _escape(
                f"{_period_line(ctx, _text(payload.get('data_as_of')))}  ·  "
                f"Generated {generated}  ·  "
                f"Report {short_id}  ·  {template_version}",
                limit=260,
            ),
            styles["muted"],
        )
    )
    story.append(Spacer(1, 2.5 * mm))

    score = dcs.get("headline_score")
    incomplete_banner = dcs.get("incomplete_banner")
    if incomplete_banner or ctx.get("show_incomplete_banner"):
        banner_text = incomplete_banner or "Incomplete assessment — treat this score as directional."
        story.append(_banner(str(banner_text), styles))
        story.append(Spacer(1, 2.5 * mm))

    open_checks = register.get("open_checks") if isinstance(register.get("open_checks"), list) else []
    story.append(
        _hero_stats(
            score=_text(score, default="Not scored"),
            state=_text(dcs.get("state")),
            open_count=_text(len(open_checks)),
            at_stake=_money(impact),
            styles=styles,
        )
    )
    story.append(Spacer(1, 3 * mm))
    story.append(
        Paragraph(
            _escape(
                f"Architecture: {_text(architecture.get('summary'), default='Not assessed')}"
                + (
                    f"  ·  mode {_text(architecture.get('mode'))}"
                    if architecture.get("assessed")
                    else ""
                ),
                limit=240,
            ),
            styles["body"],
        )
    )
    counts = (
        f"Critical {issue_summary.get('critical', 0)}  ·  "
        f"High {issue_summary.get('high', 0)}  ·  "
        f"Medium {issue_summary.get('medium', 0)}  ·  "
        f"Low {issue_summary.get('low', 0)}"
    )
    story.append(Paragraph(_escape(counts, limit=200), styles["muted"]))

    top_issues = content.get("top_issues") if isinstance(content.get("top_issues"), list) else []
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

    story.append(Paragraph("What's wrong", styles["h2"]))
    if open_checks:
        rows = [
            [
                row.get("check_id"),
                format_customer_title(str(row.get("title") or "")),
                _dimension_short(row.get("dimension")),
                row.get("systems") or "-",
                str(row.get("status") or "").upper() or "-",
                _severity_short(row.get("severity")),
                row.get("whats_wrong"),
                format_impact_cell(row.get("revenue_impact"), row.get("currency")),
                row.get("priority_class") or row.get("priority_score"),
            ]
            for row in open_checks
            if isinstance(row, dict)
        ]
        story.append(
            _table(
                ["ID", "Title", "Dim", "Systems", "Status", "Sev", "What's wrong", "Impact", "Prio"],
                rows,
                styles,
                [
                    CONTENT_W * 0.07,
                    CONTENT_W * 0.14,
                    CONTENT_W * 0.09,
                    CONTENT_W * 0.13,
                    CONTENT_W * 0.07,
                    CONTENT_W * 0.05,
                    CONTENT_W * 0.25,
                    CONTENT_W * 0.10,
                    CONTENT_W * 0.10,
                ],
            )
        )
    else:
        story.append(Paragraph("No open FAIL or WARN checks in this run.", styles["body"]))

    items = remediation.get("items") if isinstance(remediation.get("items"), list) else []
    fix_block: list[Any] = [Paragraph("What to fix", styles["h2"])]
    if items:
        rows = [
            [
                row.get("check_id"),
                row.get("suggested_fix"),
                row.get("fix_owner"),
                row.get("fix_type"),
                row.get("fix_href"),
            ]
            for row in items
            if isinstance(row, dict)
        ]
        fix_block.append(
            _table(
                ["ID", "Suggested fix", "Owner", "Type", "Path"],
                rows,
                styles,
                [
                    CONTENT_W * 0.10,
                    CONTENT_W * 0.42,
                    CONTENT_W * 0.18,
                    CONTENT_W * 0.16,
                    CONTENT_W * 0.14,
                ],
            )
        )
    else:
        fix_block.append(Paragraph("No open issues to remediate.", styles["body"]))
    story.append(KeepTogether(fix_block))

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
        if isinstance(verdicts, dict) and verdicts:
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
    else:
        story.append(
            Paragraph(
                _escape(
                    _text(architecture.get("summary"), default="Not assessed"),
                    limit=200,
                ),
                styles["body"],
            )
        )
        story.append(
            Paragraph(
                _escape(
                    architecture.get("incomplete_reason")
                    or "No architecture assessment was available for this run.",
                    limit=240,
                ),
                styles["muted"],
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
            Paragraph(
                _escape(f"Plan is empty ({reason}).", limit=160),
                styles["body"],
            )
        )

    story.append(Paragraph("Scope & method", styles["h2"]))
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
                Paragraph(
                    _escape(f"Snapshot {_text(item)}", limit=200),
                    styles["muted"],
                )
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
                f"payload_hash {footer_hash}  ·  template {template_version}",
                limit=160,
            ),
            styles["muted"],
        )
    )

    healthy = register.get("healthy_checks") if isinstance(register.get("healthy_checks"), list) else []
    coverage_checks = (
        register.get("coverage_checks")
        if isinstance(register.get("coverage_checks"), list)
        else []
    )
    if healthy or coverage_checks:
        story.append(PageBreak())
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
                ]
                story.append(
                    _table(
                        ["ID", "Title", "Status"],
                        rows,
                        styles,
                        [CONTENT_W * 0.18, CONTENT_W * 0.64, CONTENT_W * 0.18],
                    )
                )

    def on_page(canvas, doc_obj):
        _draw_chrome(
            canvas,
            doc_obj,
            footer_hash=footer_hash,
            template_version=template_version,
        )

    try:
        doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    except Exception as exc:
        raise PdfRenderError("PDF render failed.") from exc

    pdf_bytes = buffer.getvalue()
    buffer.close()
    if not pdf_bytes.startswith(b"%PDF"):
        raise PdfRenderError("Renderer produced an empty document.")
    return pdf_bytes
