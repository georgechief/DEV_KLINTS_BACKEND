from django.urls import path

from dataruns.ai.views import (
    ExplainFindingView,
    FixSuggestionView,
    NbaBlurbView,
    ReportNarrativeView,
)

urlpatterns = [
    path(
        "suggestions/fix/",
        FixSuggestionView.as_view(),
        name="ai-fix-suggestion",
    ),
    path(
        "suggestions/explain/",
        ExplainFindingView.as_view(),
        name="ai-explain-finding",
    ),
    path(
        "suggestions/nba/",
        NbaBlurbView.as_view(),
        name="ai-nba-blurb",
    ),
    path(
        "narratives/report/",
        ReportNarrativeView.as_view(),
        name="ai-report-narrative",
    ),
]
