from django.urls import path

from dataruns.reports.views import (
    AssessmentReportDetailView,
    AssessmentReportListCreateView,
    AssessmentReportPdfView,
)

urlpatterns = [
    path(
        "",
        AssessmentReportListCreateView.as_view(),
        name="assessment-reports",
    ),
    path(
        "<uuid:report_id>/pdf/",
        AssessmentReportPdfView.as_view(),
        name="assessment-report-pdf",
    ),
    path(
        "<uuid:report_id>/",
        AssessmentReportDetailView.as_view(),
        name="assessment-report-detail",
    ),
]
