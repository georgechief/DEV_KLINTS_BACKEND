from django.urls import path

from tenants.team_views import (
    TeamInviteAcceptView,
    TeamInviteListCreateView,
    TeamInviteResendView,
    TeamInviteRevokeView,
    TeamMemberDetailView,
    TeamMemberListView,
)

urlpatterns = [
    path("members/", TeamMemberListView.as_view(), name="team-members"),
    path(
        "members/<uuid:id>/",
        TeamMemberDetailView.as_view(),
        name="team-member-detail",
    ),
    path(
        "invites/accept/",
        TeamInviteAcceptView.as_view(),
        name="team-invite-accept",
    ),
    path("invites/", TeamInviteListCreateView.as_view(), name="team-invites"),
    path(
        "invites/<uuid:id>/resend/",
        TeamInviteResendView.as_view(),
        name="team-invite-resend",
    ),
    path(
        "invites/<uuid:id>/revoke/",
        TeamInviteRevokeView.as_view(),
        name="team-invite-revoke",
    ),
]
