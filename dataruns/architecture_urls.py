from django.urls import path

from dataruns.architecture.views import (
    ArchitectureAssessmentAssetsView,
    ArchitectureAssessmentCoverageView,
    ArchitectureAssessmentDetailView,
    ArchitectureAssessmentGapsView,
    ArchitectureAssessmentGraphView,
    ArchitectureAssessmentsView,
    ArchitectureLatestView,
)

urlpatterns = [
    path(
        "assessments/latest/",
        ArchitectureLatestView.as_view(),
        name="architecture-assessments-latest",
    ),
    path(
        "assessments/",
        ArchitectureAssessmentsView.as_view(),
        name="architecture-assessments",
    ),
    path(
        "assessments/<uuid:assessment_id>/",
        ArchitectureAssessmentDetailView.as_view(),
        name="architecture-assessment-detail",
    ),
    path(
        "assessments/<uuid:assessment_id>/assets/",
        ArchitectureAssessmentAssetsView.as_view(),
        name="architecture-assessment-assets",
    ),
    path(
        "assessments/<uuid:assessment_id>/graph/",
        ArchitectureAssessmentGraphView.as_view(),
        name="architecture-assessment-graph",
    ),
    path(
        "assessments/<uuid:assessment_id>/coverage/",
        ArchitectureAssessmentCoverageView.as_view(),
        name="architecture-assessment-coverage",
    ),
    path(
        "assessments/<uuid:assessment_id>/gaps/",
        ArchitectureAssessmentGapsView.as_view(),
        name="architecture-assessment-gaps",
    ),
]
