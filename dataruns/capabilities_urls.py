from django.urls import path

from dataruns.capabilities.views import CapabilityDetailView, CapabilityListView

urlpatterns = [
    path(
        "",
        CapabilityListView.as_view(),
        name="capability-list",
    ),
    path(
        "<str:capability_id>/",
        CapabilityDetailView.as_view(),
        name="capability-detail",
    ),
]
