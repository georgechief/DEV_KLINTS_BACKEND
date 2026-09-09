from django.urls import path

from dataruns.use_cases.views import (
    HandoffApproveView,
    HandoffConfirmActivatedView,
    HandoffDetailView,
    HandoffListView,
    HandoffRejectView,
)

urlpatterns = [
    path(
        "",
        HandoffListView.as_view(),
        name="handoff-list",
    ),
    path(
        "<uuid:handoff_id>/approve/",
        HandoffApproveView.as_view(),
        name="handoff-approve",
    ),
    path(
        "<uuid:handoff_id>/reject/",
        HandoffRejectView.as_view(),
        name="handoff-reject",
    ),
    path(
        "<uuid:handoff_id>/confirm-activated/",
        HandoffConfirmActivatedView.as_view(),
        name="handoff-confirm-activated",
    ),
    path(
        "<uuid:handoff_id>/",
        HandoffDetailView.as_view(),
        name="handoff-detail",
    ),
]
