from django.urls import path

from dataruns.dcs.views import (
    DcsHistoryView,
    DcsRunsView,
    DcsStatusView,
    DcsWorklistDetailView,
    DcsWorklistView,
)

urlpatterns = [
    path("status/", DcsStatusView.as_view(), name="dcs-status"),
    path("history/", DcsHistoryView.as_view(), name="dcs-history"),
    path("runs/", DcsRunsView.as_view(), name="dcs-runs"),
    path("worklist/", DcsWorklistView.as_view(), name="dcs-worklist"),
    path(
        "worklist/<str:check_id>/",
        DcsWorklistDetailView.as_view(),
        name="dcs-worklist-detail",
    ),
]
