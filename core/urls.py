from django.contrib import admin
from django.urls import include, path

from core.views import HealthCheckView, M3ObsInduceErrorView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", HealthCheckView.as_view(), name="health"),
    path(
        "ops/m3-obs-01/induce-error/",
        M3ObsInduceErrorView.as_view(),
        name="m3_obs_induce_error",
    ),
    path("api/v1/tenants/", include("tenants.urls")),
    path("api/v1/dataruns/", include("dataruns.urls")),
    path("api/v1/dcs/", include("dataruns.dcs_urls")),
    path("api/v1/writebacks/", include("dataruns.writebacks_urls")),
    path("api/v1/architecture/", include("dataruns.architecture_urls")),
    path("api/v1/use-cases/", include("dataruns.use_cases_urls")),
    path("api/v1/build-packages/", include("dataruns.build_packages_urls")),
    path("api/v1/capabilities/", include("dataruns.capabilities_urls")),
    path("api/v1/qa-runs/", include("dataruns.qa_runs_urls")),
    path("api/v1/handoffs/", include("dataruns.handoffs_urls")),
    path("api/v1/orchestration/", include("dataruns.orchestration_urls")),
    path("api/v1/assessment-reports/", include("dataruns.reports_urls")),
    path("api/v1/ai/", include("dataruns.ai_urls")),
    path("api/v1/audit/", include("dataruns.audit_urls")),
    path("api/v1/search/", include("dataruns.search_urls")),
    path("api/v1/auth/", include("tenants.auth_urls")),
    path("api/v1/connectors/", include("tenants.connector_urls")),
    path("api/v1/team/", include("tenants.team_urls")),
]
