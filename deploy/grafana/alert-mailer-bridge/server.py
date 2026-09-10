#!/usr/bin/env python3
"""Grafana alert webhook → Klints Mailer API (M3-OBS-01 Phase 4).

Grafana cannot POST the mailer JSON shape directly. This tiny internal
bridge formats Grafana Alerting payloads and calls MAILER_API_* — same
path Django uses. No second mail product.
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


def _html_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _path_only(raw_path: str) -> str:
    return (urlparse(raw_path).path or "/").rstrip("/") or "/"


def _format_alert(payload: dict[str, Any]) -> tuple[str, str, str]:
    status = str(payload.get("status") or payload.get("state") or "unknown")
    common_labels = payload.get("commonLabels") or {}
    common_annotations = payload.get("commonAnnotations") or {}
    if not isinstance(common_labels, dict):
        common_labels = {}
    if not isinstance(common_annotations, dict):
        common_annotations = {}

    title = (
        str(payload.get("title") or "").strip()
        or str(common_labels.get("alertname") or "").strip()
        or str(payload.get("groupKey") or "").strip()
        or "Grafana alert"
    )
    alerts = payload.get("alerts") or []
    lines: list[str] = []
    for alert in alerts[:25]:
        if not isinstance(alert, dict):
            continue
        labels = alert.get("labels") or {}
        annotations = alert.get("annotations") or {}
        if not isinstance(labels, dict):
            labels = {}
        if not isinstance(annotations, dict):
            annotations = {}
        service = (
            labels.get("service")
            or common_labels.get("service")
            or labels.get("alertname")
            or "?"
        )
        state = alert.get("status") or status
        summary = (
            annotations.get("summary")
            or annotations.get("description")
            or common_annotations.get("summary")
            or ""
        )
        lines.append(f"[{state}] service={service} {summary}".strip())

    if not lines:
        # Contact-point Test or empty group — still email something useful.
        summary = common_annotations.get("summary") or payload.get("message") or ""
        raw = json.dumps(payload, indent=2)[:4000]
        text = f"Grafana {status}: {title}\n{summary}\n\n{raw}".strip()
    else:
        text = f"Grafana {status}: {title}\n" + "\n".join(lines)

    html = f'<pre style="font-family:monospace">{_html_escape(text)}</pre>'
    subject = f"[Klints staging] {status}: {title}"[:200]
    return subject, html, text


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
