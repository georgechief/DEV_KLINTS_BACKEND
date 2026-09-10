"""M3-OBS-01 Phase 6 — controlled benign ERROR on `web` (no data mutation).

Important: Alloy scrapes the *running* web container's Docker logs. A bare
``logger.error`` inside ``docker compose exec`` often never reaches Loki.
This command POSTs to the live web process so gunicorn emits the ERROR line.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.m3_obs import INDUCE_MARKER

DEFAULT_INDUCE_URL = "http://127.0.0.1:8000/ops/m3-obs-01/induce-error/"


class Command(BaseCommand):
    help = (
        "POST to the running web worker to emit one benign ERROR log line "
        "for M3-OBS-01 staging acceptance (Explore service=web + web alert). "
        "Does not touch tenant data. Requires M3_OBS_INDUCE_ENABLED + token."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--yes",
            action="store_true",
            help="Required confirmation (staging ops only).",
        )
        parser.add_argument(
            "--url",
            default=DEFAULT_INDUCE_URL,
            help=f"Induce URL (default {DEFAULT_INDUCE_URL}).",
        )

    def handle(self, *args, **options):
        if not options["yes"]:
            raise CommandError(
                "Refusing to run without --yes "
                "(staging acceptance only; see docs/sahil/M3_OBS_01_PHASE_6.md)."
            )
        if not getattr(settings, "M3_OBS_INDUCE_ENABLED", False):
            raise CommandError(
                "M3_OBS_INDUCE_ENABLED is not true — enable in staging .env / "
                "DEV_ENV_FILE only for the acceptance window, then disable."
            )
        token = getattr(settings, "M3_OBS_INDUCE_TOKEN", "") or ""
        if not token:
            raise CommandError("M3_OBS_INDUCE_TOKEN is empty — set a strong token.")

        url = options["url"]
        request = urllib.request.Request(
            url,
            data=b"",
            method="POST",
            headers={
                "X-M3-Obs-Induce-Token": token,
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as resp:
                body = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise CommandError(
                f"Induce HTTP {exc.code} from {url}: {detail}"
            ) from exc
        except urllib.error.URLError as exc:
            raise CommandError(
                f"Could not reach live web at {url}: {exc.reason}. "
                "Run inside the web container (or use the droplet script) "
                "so POST hits gunicorn on :8000."
            ) from exc

        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = {"raw": body}
        marker = payload.get("marker") or INDUCE_MARKER
        self.stdout.write(
            self.style.SUCCESS(
                f"Induced ERROR via live web ({url}). marker={marker}. "
                f'Explore: {{service="web"}} |= "{marker}"'
            )
        )
