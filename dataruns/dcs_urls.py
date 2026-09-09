from django.urls import path

from dataruns.dcs.pilot_gates.views import (
    PilotGatesEvaluateView,
    PilotGatesLatestView,
    PilotGatesMasterView,
    PilotSupplementalReadinessView,
)
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
    path(
        "pilot-gates/master/",
        PilotGatesMasterView.as_view(),
        name="dcs-pilot-gates-master",
    ),
    path(
        "pilot-gates/latest/",
        PilotGatesLatestView.as_view(),
        name="dcs-pilot-gates-latest",
    ),
    path(
        "pilot-gates/evaluate/",
        PilotGatesEvaluateView.as_view(),
        name="dcs-pilot-gates-evaluate",
    ),
    path(
        "pilots/<str:use_case_id>/readiness/",
        PilotSupplementalReadinessView.as_view(),
        name="dcs-pilot-supplemental-readiness",
    ),
]
