from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from tenants.models import Company, Invite, Tenant, User
from tenants.team_views import (
    TeamInviteAcceptView,
    TeamInviteListCreateView,
    TeamInviteResendView,
    TeamInviteRevokeView,
    TeamMemberDetailView,
)


class TeamInviteTestCase(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.tenant = Tenant.objects.create(name="Lumera Skin", slug="lumera-skin")
        self.company = Company.objects.create(
            tenant=self.tenant,
            name="Lumera Skin",
            domain="lumera.skin",
        )
        self.admin = self._create_user(
            "admin@lumera.skin",
            User.Role.ADMIN,
            name="George L.",
        )
        self.analyst = self._create_user(
            "analyst@lumera.skin",
            User.Role.ANALYST,
            name="Analyst User",
        )

    def _create_user(self, email, role, name=None, tenant=None):
        return User.objects.create_user(
            email=email,
            password="TestPass123!",
            name=name or email.split("@")[0],
            tenant=tenant or self.tenant,
            role=role,
            email_verified=True,
            is_active=True,
        )

    def _create_invite(self, email="new@lumera.skin", role=User.Role.ANALYST):
        return Invite.objects.create(
            tenant=self.tenant,
            email=email,
            role=role,
            invited_by=self.admin,
            expires_at=timezone.now() + timedelta(days=7),
        )


@patch("tenants.team_views.send_invite_email")
class TeamInviteCreateTests(TeamInviteTestCase):
    def setUp(self):
        super().setUp()
        self.view = TeamInviteListCreateView.as_view()

    def _post_invite(self, user, email="new@lumera.skin", role="analyst"):
        request = self.factory.post(
            "/api/v1/team/invites/",
            {"email": email, "role": role},
            format="json",
        )
        force_authenticate(request, user=user)
        return self.view(request)

    def test_admin_creates_invite(self, mock_send):
        response = self._post_invite(self.admin)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["email"], "new@lumera.skin")
        self.assertEqual(response.data["role"], "analyst")
        self.assertEqual(response.data["status"], "pending")
        self.assertEqual(response.data["invited_by"]["email"], self.admin.email)
        self.assertIsNone(response.data["accepted_at"])
        mock_send.assert_called_once()

    def test_non_admin_forbidden(self, mock_send):
        response = self._post_invite(self.analyst)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data, {"detail": "Admin only."})
        mock_send.assert_not_called()

    def test_rejects_existing_user_email(self, mock_send):
        response = self._post_invite(self.admin, email="analyst@lumera.skin")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data,
            {"email": ["A user with this email already exists."]},
        )
        mock_send.assert_not_called()

    def test_rejects_pending_invite(self, mock_send):
        self._create_invite(email="pending@lumera.skin")
        response = self._post_invite(self.admin, email="pending@lumera.skin")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data,
            {"email": ["An invite is already pending for this email."]},
        )
        mock_send.assert_not_called()


@patch("tenants.team_views.send_invite_email")
class TeamInviteAcceptTests(TeamInviteTestCase):
    def setUp(self):
        super().setUp()
        self.view = TeamInviteAcceptView.as_view()

    def _get_preview(self, token):
        request = self.factory.get(
            f"/api/v1/team/invites/accept/?token={token}",
        )
        return self.view(request)

    def _post_accept(self, token, name="Sam Rivera", password="SecurePass123!"):
        request = self.factory.post(
            "/api/v1/team/invites/accept/",
            {"token": token, "name": name, "password": password},
            format="json",
        )
        return self.view(request)

    def test_accept_preview_and_create_user(self, mock_send):
        invite = self._create_invite()
        preview = self._get_preview(invite.token)
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.data["email"], invite.email)
        self.assertEqual(preview.data["workspace_name"], "Lumera Skin")
        self.assertEqual(preview.data["invited_by_name"], self.admin.name)

        response = self._post_accept(invite.token)
        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.data)
        self.assertEqual(response.data["user"]["email"], invite.email)
        self.assertEqual(response.data["user"]["name"], "Sam Rivera")
        self.assertEqual(response.data["user"]["role"], "analyst")
        self.assertTrue(response.data["user"]["email_verified"])
        self.assertEqual(response.data["user"]["tenant"]["slug"], "lumera-skin")
        self.assertEqual(response.data["connectors"], [])
        self.assertTrue(response.data["needs_connector"])

        user = User.objects.get(email=invite.email)
        self.assertEqual(user.tenant_id, self.tenant.id)
        invite.refresh_from_db()
        self.assertEqual(invite.status, Invite.Status.ACCEPTED)
        self.assertIsNotNone(invite.accepted_at)
        self.assertEqual(invite.accepted_user_id, user.id)

    def test_expired_invite_returns_410(self, mock_send):
        invite = self._create_invite(email="expired@lumera.skin")
        invite.expires_at = timezone.now() - timedelta(hours=1)
        invite.save(update_fields=["expires_at"])

        preview = self._get_preview(invite.token)
        self.assertEqual(preview.status_code, 410)
        self.assertEqual(
            preview.data,
            {"detail": "Invite is no longer valid."},
        )
        invite.refresh_from_db()
        self.assertEqual(invite.status, Invite.Status.EXPIRED)

    def test_revoked_invite_returns_410(self, mock_send):
        invite = self._create_invite(email="revoked@lumera.skin")
        invite.status = Invite.Status.REVOKED
        invite.save(update_fields=["status"])

        response = self._post_accept(invite.token)
        self.assertEqual(response.status_code, 410)
        self.assertEqual(
            response.data,
            {"detail": "Invite is no longer valid."},
        )


@patch("tenants.team_views.send_invite_email")
class TeamInviteResendTests(TeamInviteTestCase):
    def setUp(self):
        super().setUp()
        self.view = TeamInviteResendView.as_view()
        self.accept_view = TeamInviteAcceptView.as_view()

    def test_resend_rotates_token(self, mock_send):
        invite = self._create_invite(email="resend@lumera.skin")
        old_token = invite.token

        request = self.factory.post(
            f"/api/v1/team/invites/{invite.id}/resend/",
            {},
            format="json",
        )
        force_authenticate(request, user=self.admin)
        response = self.view(request, id=invite.id)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "pending")
        mock_send.assert_called_once()

        invite.refresh_from_db()
        self.assertNotEqual(invite.token, old_token)

        preview = self.accept_view(
            self.factory.get(
                f"/api/v1/team/invites/accept/?token={old_token}",
            )
        )
        self.assertEqual(preview.status_code, 404)


class TeamMemberGuardTests(TeamInviteTestCase):
    def setUp(self):
        super().setUp()
        self.view = TeamMemberDetailView.as_view()

    def _patch_member(self, user, member_id, data):
        request = self.factory.patch(
            f"/api/v1/team/members/{member_id}/",
            data,
            format="json",
        )
        force_authenticate(request, user=user)
        return self.view(request, id=member_id)

    def test_cannot_deactivate_last_admin(self):
        response = self._patch_member(
            self.admin,
            self.admin.id,
            {"is_active": False},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data,
            {"detail": "Cannot remove the last admin."},
        )

    def test_cannot_demote_last_admin(self):
        response = self._patch_member(
            self.admin,
            self.admin.id,
            {"role": "analyst"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data,
            {"detail": "Cannot remove the last admin."},
        )


class TeamInviteRevokeTests(TeamInviteTestCase):
    def setUp(self):
        super().setUp()
        self.view = TeamInviteRevokeView.as_view()
        self.accept_view = TeamInviteAcceptView.as_view()

    def test_revoke_then_accept_returns_410(self):
        invite = self._create_invite(email="revoke-flow@lumera.skin")

        request = self.factory.post(
            f"/api/v1/team/invites/{invite.id}/revoke/",
            {},
            format="json",
        )
        force_authenticate(request, user=self.admin)
        response = self.view(request, id=invite.id)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "revoked")

        accept_request = self.factory.post(
            "/api/v1/team/invites/accept/",
            {
                "token": invite.token,
                "name": "Sam Rivera",
                "password": "SecurePass123!",
            },
            format="json",
        )
        accept_response = self.accept_view(accept_request)
        self.assertEqual(accept_response.status_code, 410)
