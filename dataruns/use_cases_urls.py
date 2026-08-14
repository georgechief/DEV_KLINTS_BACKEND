from django.urls import path

from dataruns.use_cases.views import (
    UseCaseCatalogueView,
    UseCaseDetailView,
    UseCaseRecommendationDetailView,
    UseCaseRecommendationsView,
)

urlpatterns = [
    # Recommendations before <use_case_id> so "recommendations" is not captured as an id.
    path(
        "recommendations/",
        UseCaseRecommendationsView.as_view(),
        name="use-cases-recommendations",
    ),
    path(
        "recommendations/<str:use_case_id>/",
        UseCaseRecommendationDetailView.as_view(),
        name="use-cases-recommendation-detail",
    ),
    path(
        "",
        UseCaseCatalogueView.as_view(),
        name="use-cases-catalogue",
    ),
    path(
        "<str:use_case_id>/",
        UseCaseDetailView.as_view(),
        name="use-case-detail",
    ),
]
