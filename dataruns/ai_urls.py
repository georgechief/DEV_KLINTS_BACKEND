from django.urls import path

from dataruns.ai.views import FixSuggestionView

urlpatterns = [
    path(
        "suggestions/fix/",
        FixSuggestionView.as_view(),
        name="ai-fix-suggestion",
    ),
]
