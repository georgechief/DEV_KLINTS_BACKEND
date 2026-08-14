from django.urls import path

from dataruns.orchestration.views import OrchestrationPlanView

urlpatterns = [
    path(
        "plan/",
        OrchestrationPlanView.as_view(),
        name="orchestration-plan",
    ),
]
