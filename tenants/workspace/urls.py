from django.urls import path

from tenants.workspace.views import WorkspaceView

urlpatterns = [
    path(
        "workspace/",
        WorkspaceView.as_view(),
        name="auth-workspace",
    ),
]
