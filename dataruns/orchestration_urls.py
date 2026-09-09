from django.urls import path

from dataruns.orchestration.task_views import (
    OrchestrationTaskDetailView,
    OrchestrationTaskListCreateView,
    OrchestrationTaskTransitionView,
)
from dataruns.orchestration.views import OrchestrationPlanView

urlpatterns = [
    path(
        "plan/",
        OrchestrationPlanView.as_view(),
        name="orchestration-plan",
    ),
    path(
        "tasks/",
        OrchestrationTaskListCreateView.as_view(),
        name="orchestration-task-list-create",
    ),
    path(
        "tasks/<uuid:task_id>/",
        OrchestrationTaskDetailView.as_view(),
        name="orchestration-task-detail",
    ),
    path(
        "tasks/<uuid:task_id>/transition/",
        OrchestrationTaskTransitionView.as_view(),
        name="orchestration-task-transition",
    ),
]
