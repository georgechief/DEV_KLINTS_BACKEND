from django.urls import path

from dataruns.writebacks.views import (
    WritebackExecuteView,
    WritebackKindsView,
    WritebackMappingsView,
    WritebackPreviewView,
    WritebackRollbackView,
)
from dataruns.writebacks.approvals.views import (
    WritebackApprovalApproveView,
    WritebackApprovalDetailView,
    WritebackApprovalRejectView,
    WritebackApprovalRequestView,
)

urlpatterns = [
    path("mappings/", WritebackMappingsView.as_view(), name="writeback-mappings"),
    path("kinds/", WritebackKindsView.as_view(), name="writeback-kinds"),
    path("preview/", WritebackPreviewView.as_view(), name="writeback-preview"),
    path("execute/", WritebackExecuteView.as_view(), name="writeback-execute"),
    path("rollback/", WritebackRollbackView.as_view(), name="writeback-rollback"),
    path("approvals/", WritebackApprovalRequestView.as_view(), name="writeback-approval-request"),
    path(
        "approvals/<uuid:approval_id>/",
        WritebackApprovalDetailView.as_view(),
        name="writeback-approval-detail",
    ),
    path(
        "approvals/<uuid:approval_id>/approve/",
        WritebackApprovalApproveView.as_view(),
        name="writeback-approval-approve",
    ),
    path(
        "approvals/<uuid:approval_id>/reject/",
        WritebackApprovalRejectView.as_view(),
        name="writeback-approval-reject",
    ),
]
