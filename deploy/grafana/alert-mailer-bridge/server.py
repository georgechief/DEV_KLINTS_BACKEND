#!/usr/bin/env python3
"""Grafana alert webhook → Klints Mailer API (M3-OBS-01 Phase 4).

Grafana cannot POST the mailer JSON shape directly. This tiny internal
bridge formats Grafana Alerting payloads and calls MAILER_API_* — same
path Django uses. No second mail product.

Email subjects/bodies are written for humans (ops inbox), not raw Grafana
machine titles like ``[FIRING:1] staging-logs-error-nginx …``.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

MAILER_URL = os.environ.get("MAILER_API_URL", "").strip()
MAILER_TOKEN = os.environ.get("MAILER_API_TOKEN", "").strip()
ALERT_TO = os.environ.get("ALERT_EMAIL_TO", "noreplyklints@gmail.com").strip()
BIND_HOST = os.environ.get("BIND_HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8080"))

# Friendly names for known M3-OBS-01 Docker services.
_SERVICE_LABELS = {
    "web": "web (Django API)",
    "celery_worker": "celery worker",
    "celery_beat": "celery beat",
    "nginx": "nginx",
    "redis": "redis",
}


def _html_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _path_only(raw_path: str) -> str:
    return (urlparse(raw_path).path or "/").rstrip("/") or "/"


def _normalize_status(raw: str) -> str:
    value = (raw or "unknown").strip().lower()
    if value in {"firing", "alerting", "alert"}:
        return "firing"
    if value in {"resolved", "ok", "normal"}:
        return "resolved"
    return value or "unknown"


def _service_from_payload(payload: dict[str, Any]) -> str:
    common_labels = payload.get("commonLabels") or {}
    if isinstance(common_labels, dict):
        service = common_labels.get("service")
        if isinstance(service, str) and service.strip():
            return service.strip()

    alerts = payload.get("alerts") or []
    if isinstance(alerts, list):
        for alert in alerts:
            if not isinstance(alert, dict):
                continue
            labels = alert.get("labels") or {}
            if isinstance(labels, dict):
                service = labels.get("service")
                if isinstance(service, str) and service.strip():
                    return service.strip()

    # Fall back: scrape rule uid / alertname when labels missing.
    for key in ("alertname",):
        if isinstance(common_labels, dict):
            name = common_labels.get(key)
            if isinstance(name, str) and name.strip():
                return name.strip()
    title = str(payload.get("title") or "")
    for candidate in _SERVICE_LABELS:
        if candidate in title:
            return candidate
    return "unknown"


def _human_service(service: str) -> str:
    return _SERVICE_LABELS.get(service, service)


def _summary_from_payload(payload: dict[str, Any]) -> str:
    common_annotations = payload.get("commonAnnotations") or {}
    if isinstance(common_annotations, dict):
        for key in ("summary", "description"):
            value = common_annotations.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

    alerts = payload.get("alerts") or []
    if isinstance(alerts, list):
        for alert in alerts:
            if not isinstance(alert, dict):
                continue
            annotations = alert.get("annotations") or {}
            if not isinstance(annotations, dict):
                continue
            for key in ("summary", "description"):
                value = annotations.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
    return ""


def _rule_name(payload: dict[str, Any]) -> str:
    common_labels = payload.get("commonLabels") or {}
    if isinstance(common_labels, dict):
        alertname = common_labels.get("alertname")
        if isinstance(alertname, str) and alertname.strip():
            return alertname.strip()
    # Grafana often puts the rule title in payload["title"] — keep as footer only.
    title = str(payload.get("title") or "").strip()
    return title[:120] if title else "M3 OBS-01 log alert"


def _format_alert(payload: dict[str, Any]) -> tuple[str, str, str]:
    status = _normalize_status(
        str(payload.get("status") or payload.get("state") or "unknown")
    )
    service = _service_from_payload(payload)
    human_service = _human_service(service)
    summary = _summary_from_payload(payload)
    rule = _rule_name(payload)
    alert_count = 0
    alerts = payload.get("alerts") or []
    if isinstance(alerts, list):
        alert_count = len([a for a in alerts if isinstance(a, dict)])

    if status == "firing":
        subject = f"[Klints staging] ALERT — {human_service} error logs"
        status_line = "Status: FIRING (needs attention)"
        what = (
            summary
            or f"Staging {human_service} logged ERROR-like lines in the last ~5 minutes."
        )
        next_steps = (
            "What to do:\n"
            f"1. Open Grafana Explore and filter service={service}\n"
            "2. Find recent error / exception / critical / emerg lines\n"
            "3. Fix or confirm noise; a CLEARED email follows when the window is clean"
        )
    elif status == "resolved":
        subject = f"[Klints staging] CLEARED — {human_service} error logs"
        status_line = "Status: CLEARED (resolved)"
        what = (
            summary
            or f"Staging {human_service} no longer matches the ERROR-log alert window."
        )
        next_steps = (
            "No action needed unless you were still investigating the earlier ALERT."
        )
    else:
        subject = f"[Klints staging] Grafana notice — {human_service}"
        status_line = f"Status: {status.upper()}"
        what = summary or "Grafana sent a notification with no firing/resolved state."
        next_steps = "Check Grafana Alerting if this was unexpected."

    body_lines = [
        status_line,
        f"Service: {human_service} (label={service})",
        f"What happened: {what}",
        "",
        next_steps,
        "",
        f"Alert rule: {rule}",
    ]
    if alert_count:
        body_lines.append(f"Alerts in this notification: {alert_count}")
    body_lines.extend(
        [
            "Environment: Klints staging (apis.klints.io)",
            "Monitor: M3-OBS-01 Docker ERROR-log rules",
        ]
    )

    # Contact-point Test / empty payloads: append a short raw dump for debug.
    if not summary and not alert_count:
        raw = json.dumps(payload, indent=2)[:2000]
        body_lines.extend(["", "Raw payload (truncated):", raw])

    text = "\n".join(body_lines).strip()
    html = (
        '<div style="font-family:Segoe UI,Helvetica,Arial,sans-serif;'
        'font-size:14px;line-height:1.45;color:#111">'
        f"<p><strong>{_html_escape(status_line)}</strong></p>"
        f"<p>Service: <code>{_html_escape(human_service)}</code>"
        f" (label=<code>{_html_escape(service)}</code>)</p>"
        f"<p>What happened: {_html_escape(what)}</p>"
        f"<pre style='white-space:pre-wrap;background:#f6f8fa;padding:12px;"
        f"border-radius:6px'>{_html_escape(next_steps)}</pre>"
        f"<p style='color:#555;font-size:12px'>Alert rule: "
        f"{_html_escape(rule)} · Klints staging · M3-OBS-01</p>"
        "</div>"
    )
    return subject[:200], html, text


def _send_mail(*, to: str, subject: str, html: str, text: str) -> None:
    if not MAILER_URL or not MAILER_TOKEN:
        raise RuntimeError(
            "MAILER_API_URL / MAILER_API_TOKEN not set - stop-and-flag email path"
        )
    body = json.dumps(
        {"to": to, "subject": subject, "html": html, "text": text}
    ).encode("utf-8")
    request = urllib.request.Request(
        MAILER_URL,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {MAILER_TOKEN}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20):
            pass
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"Mailer HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Mailer unreachable: {exc.reason}") from exc


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[obs-alert-mailer] {self.address_string()} - {fmt % args}")

    def _json(self, code: int, payload: dict[str, Any]) -> None:
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:  # noqa: N802
        if _path_only(self.path) == "/health":
            configured = bool(MAILER_URL and MAILER_TOKEN)
            self._json(200, {"ok": True, "mailer_configured": configured})
            return
        self._json(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if _path_only(self.path) != "/alert":
            self._json(404, {"ok": False, "error": "not found"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
            if not isinstance(payload, dict):
                payload = {"value": payload}
        except json.JSONDecodeError:
            payload = {"raw": raw.decode("utf-8", errors="replace")}

        subject, html, text = _format_alert(payload)
        try:
            _send_mail(to=ALERT_TO, subject=subject, html=html, text=text)
        except Exception as exc:  # noqa: BLE001 — surface to Grafana webhook
            print(f"[obs-alert-mailer] send failed: {exc}")
            self._json(502, {"ok": False, "error": str(exc)})
            return
        self._json(200, {"ok": True, "to": ALERT_TO})


def main() -> None:
    print(
        f"[obs-alert-mailer] listening on {BIND_HOST}:{PORT} -> {ALERT_TO} "
        f"(mailer={'set' if MAILER_URL else 'MISSING'})"
    )
    ThreadingHTTPServer((BIND_HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
