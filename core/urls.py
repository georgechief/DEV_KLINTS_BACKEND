from django.contrib import admin
from django.urls import include, path

from core.views import HealthCheckView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", HealthCheckView.as_view(), name="health"),
    path("api/v1/tenants/", include("tenants.urls")),
    path("api/v1/dataruns/", include("dataruns.urls")),
    path("api/v1/dcs/", include("dataruns.dcs_urls")),
    path("api/v1/writebacks/", include("dataruns.writebacks_urls")),
    path("api/v1/architecture/", include("dataruns.architecture_urls")),
    path("api/v1/use-cases/", include("dataruns.use_cases_urls")),
    path("api/v1/orchestration/", include("dataruns.orchestration_urls")),
    path("api/v1/assessment-reports/", include("dataruns.reports_urls")),
    path("api/v1/ai/", include("dataruns.ai_urls")),
    path("api/v1/audit/", include("dataruns.audit_urls")),
    path("api/v1/search/", include("dataruns.search_urls")),
    path("api/v1/auth/", include("tenants.auth_urls")),
    path("api/v1/connectors/", include("tenants.connector_urls")),
    path("api/v1/team/", include("tenants.team_urls")),
]
