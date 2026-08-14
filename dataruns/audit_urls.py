from django.urls import path

from dataruns.audit_views import (
    AuditEventMarkReadView,
    AuditEventsListView,
    AuditNotificationsListView,
    AuditNotificationsMarkAllReadView,
)

urlpatterns = [
    path("events/", AuditEventsListView.as_view(), name="audit-events"),
    path(
        "events/<uuid:event_id>/mark-read/",
        AuditEventMarkReadView.as_view(),
        name="audit-event-mark-read",
    ),
    path(
        "notifications/",
        AuditNotificationsListView.as_view(),
        name="audit-notifications",
    ),
    path(
        "notifications/mark-all-read/",
        AuditNotificationsMarkAllReadView.as_view(),
        name="audit-notifications-mark-all-read",
    ),
]
