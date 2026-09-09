from django.urls import path

from dataruns.use_cases.views import (
    BuildPackageDetailView,
    BuildPackageHandoffView,
    BuildPackageQaView,
)

urlpatterns = [
    # More specific subpaths must be registered before the bare package detail.
    path(
        "<uuid:package_id>/qa/",
        BuildPackageQaView.as_view(),
        name="build-package-qa",
    ),
    path(
        "<uuid:package_id>/handoff/",
        BuildPackageHandoffView.as_view(),
        name="build-package-handoff",
    ),
    path(
        "<uuid:package_id>/",
        BuildPackageDetailView.as_view(),
        name="build-package-detail",
    ),
]
