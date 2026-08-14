from django.http import JsonResponse
from django.views import View


class HealthCheckView(View):
    """Lightweight liveness probe for load balancers and deploys."""

    def get(self, request, *args, **kwargs):
        return JsonResponse({"status": "ok"})
