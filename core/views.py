from django.http import Http404, HttpResponseForbidden, JsonResponse
from django.views import View
from django.conf import settings
import logging
import secrets

from core.m3_obs import INDUCE_MARKER


class HealthCheckView(View):
    """Lightweight liveness probe for load balancers and deploys."""

    def get(self, request, *args, **kwargs):
        return JsonResponse({"status": "ok"})


class M3ObsInduceErrorView(View):
    """M3-OBS-01 Phase 6 — log one benign ERROR on the *running* web worker.

    Must be handled by gunicorn/web (not docker exec stdout) so Alloy scrapes
    it from the container json-file log stream into Loki under service=web.
    Disabled unless M3_OBS_INDUCE_ENABLED + matching token.
    """

    http_method_names = ["post", "head", "options"]

    def post(self, request, *args, **kwargs):
        if not getattr(settings, "M3_OBS_INDUCE_ENABLED", False):
            raise Http404()
        expected = getattr(settings, "M3_OBS_INDUCE_TOKEN", "") or ""
        if not expected:
            raise Http404()
        provided = request.headers.get("X-M3-Obs-Induce-Token") or ""
        if len(provided) != len(expected) or not secrets.compare_digest(
            provided, expected
        ):
            return HttpResponseForbidden("forbidden")

        logger = logging.getLogger("m3_obs_01")
        message = (
            f"{INDUCE_MARKER} controlled benign ERROR for Explore/alert proof "
            "(service=web · no data mutation · M3-OBS-01 Phase 6)"
        )
        # stderr ensures gunicorn → Docker json-file even if LOGGING is sparse.
        print(f"ERROR {message}", flush=True)
        logger.error("%s", message)
        return JsonResponse(
            {
                "ok": True,
                "marker": INDUCE_MARKER,
                "explore": f'{{service="web"}} |= "{INDUCE_MARKER}"',
            }
        )
