from django.urls import path

from dataruns.use_cases.views import QaRunDetailView

urlpatterns = [
    path(
        "<uuid:qa_run_id>/",
        QaRunDetailView.as_view(),
        name="qa-run-detail",
    ),
]
