"""Transactional email delivery via the Klints Mailer API."""

from __future__ import annotations

import html as html_lib
import json
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlencode, urlsplit

from django.conf import settings

from tenants.models import Company, User

# Brand Board v1.0 (match frontend /src/styles.css)
_INK = "#16161a"
_ANCHOR = "#1f3a5f"
_SPARK = "#ff5b3d"
_SAND = "#f5f2eb"
_STONE = "#e8e4d9"
_FOG = "#9c9a92"
_ELEVATED = "#ffffff"
_REVENUE = "#2e8857"


class MailerAPIError(Exception):
    """Raised when the Klints Mailer API returns a non-success response."""


def send_email(
    *,
    to: str,
    subject: str,
    html: str,
    text: str,
    timeout: float = 15.0,
) -> None:
    """
    Send an email through the Klints Mailer API.

    Reusable for any notification email. Raises MailerAPIError if the API
    is unreachable or returns a non-success response.
    """
    body = json.dumps(
        {
            "to": to,
            "subject": subject,
            "html": html,
            "text": text,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        settings.MAILER_API_URL,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {settings.MAILER_API_TOKEN}",
            "Content-Type": "application/json",
        },
    )
    try:
        # urlopen raises HTTPError for every non-2xx response.
        with urllib.request.urlopen(request, timeout=timeout):
            pass
    except urllib.error.HTTPError as exc:
        detail = _error_detail(exc)
        raise MailerAPIError(
            f"Mailer API returned HTTP {exc.code}: {detail}"
        ) from exc
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", None) or str(exc)
        raise MailerAPIError(f"Could not reach Mailer API: {reason}") from exc


def _bootstrap_admin_recipient_emails(*, company: Company) -> list[str]:
    """Verified active company admins only (PRD-CONN-01 §9)."""
    return list(
        User.objects.filter(
            tenant_id=company.tenant_id,
            role=User.Role.ADMIN,
            email_verified=True,
            is_active=True,
        )
        .order_by("email")
        .values_list("email", flat=True)
    )


def _dcs_recipient_emails(
    *,
    company: Company,
    actor_user_id: str | None = None,
) -> list[str]:
    """
    DCS notify recipients (PRD-DCS-01 §8).

    Prefer the triggering user when known and verified; always include
    verified company admins so Beat / CLI runs still notify someone.
    """
    recipients: list[str] = []
    seen: set[str] = set()

    if actor_user_id:
        actor = (
            User.objects.filter(
                pk=actor_user_id,
                tenant_id=company.tenant_id,
                email_verified=True,
                is_active=True,
            )
            .only("email")
            .first()
        )
        if actor and actor.email and actor.email not in seen:
            seen.add(actor.email)
            recipients.append(actor.email)

    for email in _bootstrap_admin_recipient_emails(company=company):
        if email and email not in seen:
            seen.add(email)
            recipients.append(email)
    return recipients


def _integrations_url() -> str:
    return settings.FRONTEND_SHOPIFY_REDIRECT_URL


def _dcs_url() -> str:
    return getattr(settings, "FRONTEND_DCS_URL", None) or _integrations_url()


def _frontend_origin() -> str:
    configured = getattr(settings, "FRONTEND_APP_ORIGIN", "") or ""
    if configured.strip():
        return configured.strip().rstrip("/")
    for key in (
        "FRONTEND_VERIFY_URL",
        "FRONTEND_SHOPIFY_REDIRECT_URL",
        "FRONTEND_DCS_URL",
        "FRONTEND_INVITE_URL",
    ):
        value = getattr(settings, key, None) or ""
        if not value:
            continue
        parts = urlsplit(value)
        if parts.scheme and parts.netloc:
            return f"{parts.scheme}://{parts.netloc}"
    return "https://klints-frontend.vercel.app"


def _email_logo_url() -> str:
    configured = getattr(settings, "EMAIL_LOGO_URL", "") or ""
    if configured.strip():
        return configured.strip()
    return f"{_frontend_origin()}/klints-mark.png"


def _escape(value: Any) -> str:
    return html_lib.escape(str(value), quote=True)


def _render_email(
    *,
    eyebrow: str,
    title: str,
    body_html: str,
    cta_url: str | None = None,
    cta_label: str | None = None,
    footer_note: str | None = None,
) -> str:
    """Shared Klints-branded HTML shell (sand canvas, ink type, anchor CTA)."""
    logo_url = _escape(_email_logo_url())
    eyebrow_e = _escape(eyebrow)
    title_e = _escape(title)
    cta_block = ""
    if cta_url and cta_label:
        cta_block = f"""
          <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin: 28px 0 0;">
            <tr>
              <td style="border-radius: 8px; background-color: {_ANCHOR};">
                <a href="{_escape(cta_url)}"
                   style="display: inline-block; padding: 12px 22px; font-family: Inter, Helvetica, Arial, sans-serif; font-size: 14px; font-weight: 600; color: {_ELEVATED}; text-decoration: none; border-radius: 8px;">
                  {_escape(cta_label)}
                </a>
              </td>
            </tr>
          </table>
        """
    footer = footer_note or (
        "You're receiving this because of activity on your Klints workspace."
    )
    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{title_e}</title>
</head>
<body style="margin: 0; padding: 0; background-color: {_SAND};">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: {_SAND};">
    <tr>
      <td align="center" style="padding: 32px 16px;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width: 560px; margin: 0 auto;">
          <tr>
            <td style="padding: 0 4px 20px;">
              <table role="presentation" cellpadding="0" cellspacing="0" border="0">
                <tr>
                  <td style="vertical-align: middle; padding-right: 10px;">
                    <img src="{logo_url}" width="28" height="28" alt="Klints" style="display: block; border: 0; width: 28px; height: 28px;" />
                  </td>
                  <td style="vertical-align: middle; font-family: Inter, Helvetica, Arial, sans-serif; font-size: 16px; font-weight: 600; letter-spacing: -0.02em; color: {_INK};">
                    Klints
                  </td>
                </tr>
              </table>
            </td>
          </tr>
          <tr>
            <td style="background-color: {_ELEVATED}; border: 1px solid {_STONE}; border-radius: 12px; overflow: hidden;">
              <div style="height: 3px; background: linear-gradient(90deg, {_ANCHOR} 0%, {_SPARK} 100%); line-height: 3px; font-size: 0;">&nbsp;</div>
              <div style="padding: 28px 28px 32px;">
                <div style="font-family: Inter, Helvetica, Arial, sans-serif; font-size: 11px; font-weight: 600; letter-spacing: 0.12em; text-transform: uppercase; color: {_FOG};">
                  {eyebrow_e}
                </div>
                <h1 style="margin: 10px 0 0; font-family: Inter, Helvetica, Arial, sans-serif; font-size: 22px; font-weight: 600; letter-spacing: -0.02em; line-height: 1.25; color: {_INK};">
                  {title_e}
                </h1>
                <div style="margin: 18px 0 0; font-family: Inter, Helvetica, Arial, sans-serif; font-size: 14px; line-height: 1.6; color: {_INK};">
                  {body_html}
                </div>
                {cta_block}
              </div>
            </td>
          </tr>
          <tr>
            <td style="padding: 20px 8px 0; font-family: Inter, Helvetica, Arial, sans-serif; font-size: 12px; line-height: 1.5; color: {_FOG}; text-align: center;">
              {_escape(footer)}
              <br />
              <span style="color: {_FOG};">Klints · Data-ready growth for commerce teams</span>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""


def _meta_row(label: str, value: Any) -> str:
    return (
        f'<tr>'
        f'<td style="padding: 8px 0; border-bottom: 1px solid {_STONE}; '
        f'font-family: Inter, Helvetica, Arial, sans-serif; font-size: 12px; '
        f'color: {_FOG}; width: 42%; vertical-align: top;">{_escape(label)}</td>'
        f'<td style="padding: 8px 0; border-bottom: 1px solid {_STONE}; '
        f'font-family: Inter, Helvetica, Arial, sans-serif; font-size: 13px; '
        f'font-weight: 500; color: {_INK}; vertical-align: top;">{_escape(value)}</td>'
        f"</tr>"
    )


def _meta_table(rows: list[tuple[str, Any]]) -> str:
    inner = "".join(_meta_row(label, value) for label, value in rows)
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'border="0" style="margin: 4px 0 0; border-collapse: collapse;">{inner}</table>'
    )


def _platform_label(platform: str) -> str:
    if platform == "manago_ai":
        return "Manago.ai"
    if platform == "shopify":
        return "Shopify"
    return platform


def send_connector_connected_email(
    *,
    company: Company,
    platform: str,
    account_label: str | None = None,
) -> None:
    """
    Notify admins immediately when a connector is linked (before bootstrap finishes).

    Complements the later bootstrap success/failure emails (PRD-CONN-01 §9).
    """
    platform_label = _platform_label(platform)
    integrations_url = _integrations_url()
    account = (account_label or "").strip()
    subject = f"Klints: {platform_label} connected"
    account_line = f"Account: {account}\n" if account else ""
    text = (
        f"{platform_label} is now connected to Klints.\n\n"
        f"{account_line}"
        f"We're importing the recent data window next — you'll get another "
        f"email when that finishes.\n\n"
        f"Open Connected stack: {integrations_url}\n"
    )
    meta_rows: list[tuple[str, Any]] = [("Source", platform_label)]
    if account:
        meta_rows.append(("Account", account))
    body_html = f"""\
<p style="margin: 0 0 14px;">
  <strong>{_escape(platform_label)}</strong> is now connected to Klints.
</p>
{_meta_table(meta_rows)}
<p style="margin: 14px 0 0;">
  We're importing the recent data window next. You'll get another email when
  that import finishes.
</p>
"""
    html = _render_email(
        eyebrow="Connected stack",
        title=f"{platform_label} connected",
        body_html=body_html,
        cta_url=integrations_url,
        cta_label="Open Connected stack",
    )
    recipients = _bootstrap_admin_recipient_emails(company=company)
    if not recipients:
        return
    for email in recipients:
        send_email(to=email, subject=subject, html=html, text=text)


def send_connector_bootstrap_success_email(
    *,
    company: Company,
    platform: str,
    days: int,
    counts: dict[str, Any],
    window_start: str,
    window_end: str,
    warn_issues: list[dict[str, str]] | None = None,
) -> None:
    """Notify admins that a connector bootstrap import finished (PRD-CONN-01 §9)."""
    platform_label = _platform_label(platform)
    integrations_url = _integrations_url()
    contacts = counts.get("contacts", 0)
    orders = counts.get("orders", 0)
    subject = f"Klints: {platform_label} import finished ({days} days)"
    warn_lines = _format_warn_issues(warn_issues)
    text = (
        f"Your {platform_label} import finished.\n\n"
        f"Window: {window_start} to {window_end}\n"
        f"Contacts imported: {contacts}\n"
        f"Orders imported: {orders}\n"
    )
    if warn_lines:
        text += f"\nWarnings:\n{warn_lines}\n"
    text += f"\nOpen Connected stack: {integrations_url}\n"

    warn_html = ""
    if warn_lines:
        warn_html = (
            f'<div style="margin: 18px 0 0; padding: 12px 14px; background-color: {_SAND}; '
            f'border: 1px solid {_STONE}; border-radius: 8px; font-size: 13px; line-height: 1.5; color: {_INK};">'
            f"<strong>Warnings</strong><br>"
            f"{_escape(warn_lines).replace(chr(10), '<br>')}"
            f"</div>"
        )

    body_html = f"""\
<p style="margin: 0 0 14px;">
  Your <strong>{_escape(platform_label)}</strong> import finished successfully.
</p>
{_meta_table([
    ("Window", f"{window_start} → {window_end}"),
    ("Contacts imported", contacts),
    ("Orders imported", orders),
])}
{warn_html}
"""
    html = _render_email(
        eyebrow="Connected stack",
        title=f"{platform_label} import finished",
        body_html=body_html,
        cta_url=integrations_url,
        cta_label="Open Connected stack",
    )
    for email in _bootstrap_admin_recipient_emails(company=company):
        send_email(to=email, subject=subject, html=html, text=text)


def send_connector_bootstrap_failure_email(
    *,
    company: Company,
    platform: str,
    error_message: str,
    issue_codes: list[str] | None = None,
) -> None:
    """Notify admins that a connector bootstrap import failed (PRD-CONN-01 §9)."""
    del issue_codes  # kept for callers; not shown to merchants
    platform_label = _platform_label(platform)
    integrations_url = _integrations_url()
    subject = f"Klints: {platform_label} import didn’t finish"
    raw_error = " ".join(str(error_message or "").split()).strip()
    safe_error = (
        "We couldn’t finish importing your data. Please reconnect and try again."
        if (not raw_error or _looks_technical_copy(raw_error))
        else raw_error
    )
    text = (
        f"Your {platform_label} import didn’t finish.\n\n"
        f"What happened: {safe_error}\n\n"
        f"Reconnect in Connected stack: {integrations_url}\n"
    )
    body_html = f"""\
<p style="margin: 0 0 14px;">
  Your <strong>{_escape(platform_label)}</strong> import didn’t finish. Reconnect the source, then try again.
</p>
{_meta_table([
    ("Company", company.name),
    ("What happened", safe_error),
])}
"""
    html = _render_email(
        eyebrow="Connected stack",
        title=f"{platform_label} import didn’t finish",
        body_html=body_html,
        cta_url=integrations_url,
        cta_label="Reconnect in Connected stack",
    )
    for email in _bootstrap_admin_recipient_emails(company=company):
        send_email(to=email, subject=subject, html=html, text=text)


def send_shopify_auth_expired_email(
    *,
    company: Company,
    shop_domain: str,
    reason_code: str,
    source: str,
) -> None:
    """Notify admins that Shopify must be reconnected (PRD-CONN-05 §5.3)."""
    del reason_code, source  # internal diagnostics; not shown to merchants
    integrations_url = _integrations_url()
    shop_line = shop_domain.strip() or "your Shopify store"
    subject = "Klints: please reconnect Shopify"
    text = (
        f"Your Shopify connection for {shop_line} needs to be reconnected.\n\n"
        "This usually means the store login expired. "
        "Reconnect once and imports will continue.\n\n"
        f"Reconnect in Connected stack: {integrations_url}\n"
    )
    body_html = f"""\
<p style="margin: 0 0 14px;">
  Your Shopify connection for <strong>{_escape(shop_line)}</strong> needs to be
  reconnected. This usually means the store login expired.
</p>
<p style="margin: 0 0 14px; color: {_FOG}; font-size: 13px;">
  Reconnect once from Connected stack and imports will continue.
</p>
"""
    html = _render_email(
        eyebrow="Connected stack",
        title="Please reconnect Shopify",
        body_html=body_html,
        cta_url=integrations_url,
        cta_label="Reconnect Shopify",
    )
    for email in _bootstrap_admin_recipient_emails(company=company):
        send_email(to=email, subject=subject, html=html, text=text)


def _format_warn_issues(warn_issues: list[dict[str, str]] | None) -> str:
    if not warn_issues:
        return ""
    lines: list[str] = []
    for issue in warn_issues:
        code = issue.get("code", "")
        message = issue.get("message", "")
        if code and message:
            lines.append(f"- {code}: {message}")
        elif message:
            lines.append(f"- {message}")
        elif code:
            lines.append(f"- {code}")
    return "\n".join(lines)


def _looks_technical_copy(text: str) -> bool:
    """Heuristic: Excel / engineering copy that should not go to merchants."""
    raw = (text or "").strip()
    if not raw:
        return False
    lowered = raw.casefold()
    needles = (
        "rc-",
        "fd-",
        "ci-",
        "le-",
        "pt-",
        "sp-",
        "cc-",
        "me-",
        "br-",
        "excel",
        "writeback",
        "era-flag",
        "era flag",
        "root cause",
        "topology",
        "schema",
        "idempotent",
        "webhook",
        "sla",
        "api ",
        "oauth",
        "bootstrap",
        "datarun",
        "reason_code",
        "check_id",
        "geo_variant",
        "independent_business_line",
        "segment_variant",
        "canonical",
        "provenance",
        "pipeline",
        "traceback",
        "exception",
        "auth_failed",
        "refresh token",
        "access token",
        "token refresh",
        "inactive",
        "backfill",
        " missing pipe",
        "the missing pipe",
        "pipe;",
        "pipe,",
        ".py",
        "http://",
        "https://",
    )
    if any(n in lowered for n in needles):
        return True
    # Dense identifier-style fragments (ORDER_ID, smclient, etc.)
    if any(ch.isupper() for ch in raw) and "_" in raw and " " not in raw[:20]:
        return True
    return False


def _merchant_issue_message(message: str) -> str:
    """Keep only plain-language detail lines for email."""
    text = " ".join(str(message or "").split()).strip()
    if not text or _looks_technical_copy(text):
        return ""
    return text


def _merchant_suggested_fix(
    *,
    suggested_fix: str,
    fix_in_klints: bool | None = None,
) -> str:
    """
    Prefer a short human fix. If catalogue copy is technical, fall back to a
    ownership-aware CTA that points people to the dashboard.
    """
    text = " ".join(str(suggested_fix or "").split()).strip()
    if text and not _looks_technical_copy(text):
        return text
    if fix_in_klints:
        return "Klints can help with this — open your dashboard for the next step."
    return "This needs a setup change on your side — open your dashboard for guidance."


def _top_fail_summaries(
    fail_checks: list[dict[str, Any]] | None,
    *,
    limit: int = 5,
) -> list[dict[str, str]]:
    """Normalize top FAIL rows for DCS email body (merchant-facing copy)."""
    rows: list[dict[str, str]] = []
    for item in fail_checks or []:
        if not isinstance(item, dict):
            continue
        check_id = str(item.get("check_id") or "").strip()
        if not check_id:
            continue
        title = str(
            item.get("check_name")
            or item.get("title")
            or "Data consistency item"
        ).strip()
        # Never lead with a bare check id in merchant email.
        if not title or title.casefold() == check_id.casefold():
            title = "Data consistency item"
        message = _merchant_issue_message(
            str(item.get("message") or item.get("detail") or "")
        )
        fix_in_klints = item.get("fix_in_klints")
        if fix_in_klints is None:
            owner = str(item.get("fix_owner") or "").strip().casefold()
            fix_in_klints = owner == "klints (automated)"
        suggested = _merchant_suggested_fix(
            suggested_fix=str(
                item.get("suggested_fix") or item.get("remediation") or ""
            ),
            fix_in_klints=bool(fix_in_klints),
        )
        rows.append(
            {
                "check_id": check_id,
                "title": title,
                "message": message,
                "suggested_fix": suggested,
            }
        )
        if len(rows) >= limit:
            break
    return rows


def _dcs_run_state_label(run_state: str) -> str:
    state = str(run_state or "").upper()
    labels = {
        "BLOCKED": "Needs a few fixes first",
        "INCOMPLETE": "Still finishing",
        "REMEDIATE": "Improvements recommended",
        "CONDITIONALLY_READY": "Ready, with a few notes",
        "READY": "Ready",
        "SCORED": "Ready",
        "COMPLETE": "Ready",
        "COMPLETED": "Ready",
    }
    if state in labels:
        return labels[state]
    if state:
        return "Finished"
    return "Finished"


def _dcs_score_label(headline_score: float | int | None) -> str:
    if headline_score is None:
        return "Not ready yet"
    try:
        value = float(headline_score)
    except (TypeError, ValueError):
        return "Not ready yet"
    # Merchants don't need three decimal places.
    if value == int(value):
        return str(int(value))
    return f"{value:.1f}"


def _user_safe_pipeline_error(error_message: str) -> str:
    """Keep pipeline failure emails readable; never dump stack traces."""
    raw = " ".join(str(error_message or "").split()).strip()
    if not raw or _looks_technical_copy(raw):
        return (
            "Something went wrong while calculating your score. "
            "Please try again from the dashboard."
        )
    if len(raw) > 160:
        return (
            "Something went wrong while calculating your score. "
            "Please try again from the dashboard."
        )
    return raw


def send_dcs_completed_email(
    *,
    company: Company,
    run_state: str,
    headline_score: float | int | None,
    data_run_id: int | str,
    fail_checks: list[dict[str, Any]] | None = None,
    blocking_gates_failed: int = 0,
    actor_user_id: str | None = None,
) -> None:
    """
    Notify after a DCS pipeline finishes (PRD-DCS-01 §8).

    Merchant-facing copy only — no check IDs, reason codes, or Excel jargon.
    """
    del data_run_id  # kept in signature for callers; not shown to merchants
    dcs_url = _dcs_url()
    fails = _top_fail_summaries(fail_checks)
    score_label = _dcs_score_label(headline_score)
    blocked = str(run_state).upper() == "BLOCKED"
    state_label = _dcs_run_state_label(run_state)

    if blocked:
        subject = "Klints: a few fixes needed before your data score"
        lead = (
            "We checked how consistent your connected data is. "
            "A few required items still need attention before we can show your score."
        )
        title = "Action needed for your data score"
        issues_heading = "What to fix"
    else:
        subject = "Klints: your data consistency score is ready"
        lead = (
            "Your data consistency check finished. "
            "Open the dashboard to review the full results."
        )
        title = "Your data consistency score is ready"
        issues_heading = "Things to improve" if fails else "Issues"

    fail_text_lines: list[str] = []
    for row in fails:
        line = f"- {row['title']}"
        if row["message"]:
            line += f"\n  {row['message']}"
        if row["suggested_fix"]:
            line += f"\n  What to do: {row['suggested_fix']}"
        fail_text_lines.append(line)
    fails_block = (
        "\n".join(fail_text_lines)
        if fail_text_lines
        else "Nothing urgent in this summary."
    )

    text_parts = [
        f"{lead}\n",
        f"Company: {company.name}",
        f"Status: {state_label}",
        f"Score: {score_label}",
    ]
    if blocked and blocking_gates_failed:
        text_parts.append(f"Required items still open: {blocking_gates_failed}")
    text_parts.extend(
        [
            "",
            f"{issues_heading}:",
            fails_block,
            "",
            f"Open dashboard: {dcs_url}",
            "",
        ]
    )
    text = "\n".join(text_parts)

    html_fail_items = ""
    for row in fails:
        msg_html = (
            f'<div style="margin: 4px 0 0; color: {_FOG}; font-size: 12.5px;">'
            f'{_escape(row["message"])}</div>'
            if row["message"]
            else ""
        )
        fix_html = (
            f'<div style="margin: 6px 0 0; font-size: 12.5px; color: {_INK};">'
            f'<span style="color: {_ANCHOR}; font-weight: 600;">What to do:</span> '
            f'{_escape(row["suggested_fix"])}</div>'
            if row["suggested_fix"]
            else ""
        )
        html_fail_items += (
            f'<li style="margin: 0 0 14px; padding: 12px 14px; list-style: none; '
            f'background-color: {_SAND}; border: 1px solid {_STONE}; border-radius: 8px;">'
            f'<div style="font-weight: 600; color: {_INK};">'
            f'{_escape(row["title"])}</div>'
            f"{msg_html}{fix_html}</li>"
        )
    if not html_fail_items:
        html_fail_items = (
            f'<li style="list-style: none; color: {_FOG}; font-size: 13px;">'
            "Nothing urgent in this summary.</li>"
        )

    score_color = _FOG if headline_score is None else _REVENUE
    meta_rows: list[tuple[str, Any]] = [
        ("Company", company.name),
        ("Status", state_label),
    ]
    if blocked and blocking_gates_failed:
        meta_rows.append(("Required items still open", blocking_gates_failed))

    body_html = f"""\
<p style="margin: 0 0 14px;">{_escape(lead)}</p>
<div style="margin: 0 0 16px; padding: 14px 16px; background-color: {_SAND}; border: 1px solid {_STONE}; border-radius: 8px;">
  <div style="font-size: 11px; font-weight: 600; letter-spacing: 0.1em; text-transform: uppercase; color: {_FOG};">Your score</div>
  <div style="margin-top: 4px; font-size: 28px; font-weight: 600; letter-spacing: -0.03em; color: {score_color};">{_escape(score_label)}</div>
</div>
{_meta_table(meta_rows)}
<p style="margin: 22px 0 10px; font-size: 12px; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; color: {_FOG};">
  {_escape(issues_heading)}
</p>
<ul style="margin: 0; padding: 0;">{html_fail_items}</ul>
"""

    html = _render_email(
        eyebrow="Data consistency",
        title=title,
        body_html=body_html,
        cta_url=dcs_url,
        cta_label="Open dashboard",
    )
    for email in _dcs_recipient_emails(
        company=company, actor_user_id=actor_user_id
    ):
        send_email(to=email, subject=subject, html=html, text=text)


def send_dcs_failed_email(
    *,
    company: Company,
    error_message: str,
    data_run_id: int | str | None = None,
    actor_user_id: str | None = None,
) -> None:
    """Notify when the DCS Celery pipeline itself fails (PRD-DCS-01 §8)."""
    dcs_url = _dcs_url()
    subject = "Klints: we couldn't finish your data score"
    safe_error = _user_safe_pipeline_error(error_message)
    text = (
        "We started checking your data consistency but couldn't finish the run.\n\n"
        f"Company: {company.name}\n"
        f"What happened: {safe_error}\n\n"
        f"Open the dashboard and try again: {dcs_url}\n"
    )
    meta_rows: list[tuple[str, Any]] = [
        ("Company", company.name),
        ("What happened", safe_error),
    ]
    body_html = f"""\
<p style="margin: 0 0 14px;">
  We started checking your data consistency but couldn't finish. Please try again from your dashboard.
</p>
{_meta_table(meta_rows)}
"""
    html = _render_email(
        eyebrow="Data consistency",
        title="We couldn't finish your score",
        body_html=body_html,
        cta_url=dcs_url,
        cta_label="Open dashboard",
    )
    for email in _dcs_recipient_emails(
        company=company, actor_user_id=actor_user_id
    ):
        send_email(to=email, subject=subject, html=html, text=text)


def send_verification_email(*, email: str, token: str) -> None:
    query = urlencode({"token": token, "email": email})
    link = f"{settings.FRONTEND_VERIFY_URL}?{query}"
    subject = "Verify your Klints account"
    text = (
        f"Verify your email by opening this link:\n\n{link}\n\n"
        "If you did not create a Klints account, you can safely ignore this email."
    )
    body_html = f"""\
<p style="margin: 0 0 14px;">
  Confirm your email to activate your Klints account and start connecting your stack.
</p>
<p style="margin: 0; font-size: 12.5px; color: {_FOG};">
  If the button doesn’t work, paste this link into your browser:<br />
  <a href="{_escape(link)}" style="color: {_ANCHOR}; word-break: break-all;">{_escape(link)}</a>
</p>
"""
    html = _render_email(
        eyebrow="Welcome",
        title="Verify your email",
        body_html=body_html,
        cta_url=link,
        cta_label="Verify email",
        footer_note="If you didn’t create a Klints account, you can safely ignore this email.",
    )
    send_email(to=email, subject=subject, html=html, text=text)


def send_password_reset_email(*, email: str, token: str) -> None:
    query = urlencode({"token": token, "email": email})
    link = f"{settings.FRONTEND_RESET_URL}?{query}"
    ttl_hours = settings.PASSWORD_RESET_TTL_HOURS
    subject = "Reset your Klints password"
    text = (
        f"We received a request to reset the password for {email}.\n\n"
        f"Reset your password:\n{link}\n\n"
        f"This link expires in {ttl_hours} hours.\n\n"
        "If you did not ask for this, ignore this email."
    )
    body_html = f"""\
<p style="margin: 0 0 14px;">
  We received a request to reset the password for <strong>{_escape(email)}</strong>.
</p>
<p style="margin: 0 0 14px; font-size: 13px; color: {_FOG};">
  This link expires in {_escape(ttl_hours)} hours.
</p>
<p style="margin: 0; font-size: 12.5px; color: {_FOG};">
  If the button doesn’t work, paste this link into your browser:<br />
  <a href="{_escape(link)}" style="color: {_ANCHOR}; word-break: break-all;">{_escape(link)}</a>
</p>
"""
    html = _render_email(
        eyebrow="Account",
        title="Reset your password",
        body_html=body_html,
        cta_url=link,
        cta_label="Reset password",
        footer_note="If you didn’t ask for this, you can safely ignore this email.",
    )
    send_email(to=email, subject=subject, html=html, text=text)


def send_invite_email(
    *,
    email: str,
    token: str,
    workspace_name: str,
    invited_by_name: str,
    role: str,
) -> None:
    query = urlencode({"token": token})
    link = f"{settings.FRONTEND_INVITE_URL}?{query}"
    ttl_days = settings.INVITE_TTL_DAYS
    subject = f"You're invited to {workspace_name} on Klints"
    text = (
        f"{invited_by_name} invited you to join {workspace_name} as {role}.\n\n"
        f"Accept your invite:\n{link}\n\n"
        f"This link expires in {ttl_days} days."
    )
    body_html = f"""\
<p style="margin: 0 0 14px;">
  <strong>{_escape(invited_by_name)}</strong> invited you to join
  <strong>{_escape(workspace_name)}</strong> as <strong>{_escape(role)}</strong>.
</p>
<p style="margin: 0 0 14px; font-size: 13px; color: {_FOG};">
  This invite expires in {_escape(ttl_days)} days.
</p>
<p style="margin: 0; font-size: 12.5px; color: {_FOG};">
  If the button doesn’t work, paste this link into your browser:<br />
  <a href="{_escape(link)}" style="color: {_ANCHOR}; word-break: break-all;">{_escape(link)}</a>
</p>
"""
    html = _render_email(
        eyebrow="Team invite",
        title=f"Join {workspace_name}",
        body_html=body_html,
        cta_url=link,
        cta_label="Accept invite",
    )
    send_email(to=email, subject=subject, html=html, text=text)


def _error_detail(exc: urllib.error.HTTPError) -> str:
    try:
        raw = exc.read().decode("utf-8")
        if raw:
            return raw[:500]
    except Exception:  # noqa: BLE001
        pass
    return exc.reason or "no response body"
