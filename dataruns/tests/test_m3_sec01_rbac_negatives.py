"""M3-SEC-01 Phase 4 — RBAC negatives on mutating product surfaces.

Viewer (or wrong role) → 403; unauthenticated → 401.

Gates proven in older modules are listed in docs/sahil/M3_SEC_01_PHASE_4.md
(cite inventory). This module covers money/connect/score mutates plus team /
workspace / connectors / writeback /run/ and approval approve/reject.
"""

from __future__ import annotations

import uuid

from django.test import TestCase

from dataruns.tests.helpers_m3_sec01 import make_sec01_role_clients
from tenants.models import Invite, User


class M3Sec01RbacNegativesTests(TestCase):
    """Mutating surfaces from the RBAC matrix (Viewer-denied / Admin-only)."""

    def setUp(self):
        self.roles = make_sec01_role_clients(slug_prefix="sec01-rbac")

    def _assert_viewer_403_unauth_401(self, method: str, path: str, **kwargs):
        viewer_fn = getattr(self.roles.client_viewer, method.lower())
        anon_fn = getattr(self.roles.client_anon, method.lower())
        viewer_resp = viewer_fn(path, **kwargs)
        self.assertEqual(
            viewer_resp.status_code,
            403,
            msg=f"viewer {method} {path} → {viewer_resp.status_code} {viewer_resp.data}",
        )
        anon_resp = anon_fn(path, **kwargs)
        self.assertEqual(
            anon_resp.status_code,
            401,
            msg=f"anon {method} {path} → {anon_resp.status_code}",
        )

    def _assert_analyst_403(self, method: str, path: str, **kwargs):
        fn = getattr(self.roles.client_analyst, method.lower())
        response = fn(path, **kwargs)
        self.assertEqual(
            response.status_code,
            403,
            msg=f"analyst {method} {path} → {response.status_code} {response.data}",
        )

    # --- DCS / writebacks / architecture / orch / reports ---

    def test_dcs_runs_viewer_and_analyst_forbidden(self):
        path = "/api/v1/dcs/runs/"
        self._assert_viewer_403_unauth_401("post", path, data={}, format="json")
        self._assert_analyst_403("post", path, data={}, format="json")

    def test_writeback_execute_viewer_and_analyst_forbidden(self):
        path = "/api/v1/writebacks/execute/"
        self._assert_viewer_403_unauth_401("post", path, data={}, format="json")
        self._assert_analyst_403("post", path, data={}, format="json")

    def test_writeback_rollback_viewer_and_analyst_forbidden(self):
        path = "/api/v1/writebacks/rollback/"
        self._assert_viewer_403_unauth_401("post", path, data={}, format="json")
        self._assert_analyst_403("post", path, data={}, format="json")

    def test_writeback_preview_viewer_forbidden(self):
        self._assert_viewer_403_unauth_401(
            "post",
            "/api/v1/writebacks/preview/",
            data={},
            format="json",
        )

    def test_writeback_run_viewer_forbidden_for_all_actions(self):
        path = "/api/v1/writebacks/run/"
        for action in ("preview", "execute", "rollback"):
            with self.subTest(action=action):
                self._assert_viewer_403_unauth_401(
                    "post",
                    path,
                    data={"action": action},
                    format="json",
                )

    def test_writeback_run_viewer_forbidden_before_action_validation(self):
        """Viewer must 403 even with missing/invalid action (no action-name leak)."""
        path = "/api/v1/writebacks/run/"
        for data in ({}, {"action": "not-a-real-action"}, {"action": 123}):
            with self.subTest(data=data):
                response = self.roles.client_viewer.post(path, data, format="json")
                self.assertEqual(
                    response.status_code,
                    403,
                    msg=f"viewer → {response.status_code} {response.data}",
                )
                self.assertNotIn("required_keys", response.data)

    def test_writeback_run_analyst_execute_and_rollback_forbidden(self):
        path = "/api/v1/writebacks/run/"
        # Incomplete body must still 403 (role before required-key validation).
        self._assert_analyst_403(
            "post", path, data={"action": "execute"}, format="json"
        )
        self._assert_analyst_403(
            "post", path, data={"action": "rollback"}, format="json"
        )
        # Must not teach execute payload keys to Analyst.
        response = self.roles.client_analyst.post(
            path, {"action": "execute"}, format="json"
        )
        self.assertEqual(response.status_code, 403)
        self.assertNotIn("required_keys", response.data)

    def test_writeback_approvals_request_viewer_forbidden(self):
        self._assert_viewer_403_unauth_401(
            "post",
            "/api/v1/writebacks/approvals/",
            data={},
            format="json",
        )

    def test_writeback_approvals_approve_reject_viewer_and_analyst_forbidden(self):
        fake_id = str(uuid.uuid4())
        for suffix in ("approve", "reject"):
            path = f"/api/v1/writebacks/approvals/{fake_id}/{suffix}/"
            with self.subTest(path=path):
                self._assert_viewer_403_unauth_401(
                    "post", path, data={}, format="json"
                )
                self._assert_analyst_403("post", path, data={}, format="json")

    def test_architecture_start_viewer_and_analyst_forbidden(self):
        path = "/api/v1/architecture/assessments/"
        self._assert_viewer_403_unauth_401("post", path, data={}, format="json")
        self._assert_analyst_403("post", path, data={}, format="json")

    def test_orch_create_task_viewer_forbidden(self):
        self._assert_viewer_403_unauth_401(
            "post",
            "/api/v1/orchestration/tasks/",
            data={"task_type": "fix"},
            format="json",
        )

    def test_orch_transition_viewer_forbidden(self):
        fake_id = str(uuid.uuid4())
        self._assert_viewer_403_unauth_401(
            "post",
            f"/api/v1/orchestration/tasks/{fake_id}/transition/",
            data={"to_status": "done"},
            format="json",
        )

    def test_report_compose_viewer_forbidden(self):
        self._assert_viewer_403_unauth_401(
            "post",
            "/api/v1/assessment-reports/",
            data={},
            format="json",
        )

    def test_report_pdf_viewer_forbidden(self):
        fake_id = str(uuid.uuid4())
        self._assert_viewer_403_unauth_401(
            "get",
            f"/api/v1/assessment-reports/{fake_id}/pdf/",
        )

    def test_pilot_gates_evaluate_viewer_forbidden(self):
        self._assert_viewer_403_unauth_401(
            "post",
            "/api/v1/dcs/pilot-gates/evaluate/",
            data={},
            format="json",
        )

    def test_use_case_build_package_viewer_forbidden(self):
        self._assert_viewer_403_unauth_401(
            "post",
            "/api/v1/use-cases/uc-fake/build-package/",
            data={},
            format="json",
        )

    def test_build_package_handoff_create_viewer_forbidden(self):
        fake_id = str(uuid.uuid4())
        self._assert_viewer_403_unauth_401(
            "post",
            f"/api/v1/build-packages/{fake_id}/handoff/",
            data={},
            format="json",
        )

    def test_handoff_approve_reject_confirm_viewer_and_analyst_forbidden(self):
        fake_id = str(uuid.uuid4())
        for suffix in ("approve", "reject", "confirm-activated"):
            path = f"/api/v1/handoffs/{fake_id}/{suffix}/"
            with self.subTest(path=path):
                self._assert_viewer_403_unauth_401(
                    "post", path, data={}, format="json"
                )
                self._assert_analyst_403("post", path, data={}, format="json")

    # --- Tenants: workspace / team / connectors ---

    def test_workspace_patch_viewer_forbidden(self):
        self._assert_viewer_403_unauth_401(
            "patch",
            "/api/v1/auth/workspace/",
            data={"tenant_name": "Nope"},
            format="json",
        )
        self._assert_analyst_403(
            "patch",
            "/api/v1/auth/workspace/",
            data={"tenant_name": "Nope"},
            format="json",
        )

    def test_team_member_patch_viewer_and_analyst_forbidden(self):
        path = f"/api/v1/team/members/{self.roles.viewer.id}/"
        self._assert_viewer_403_unauth_401(
            "patch",
            path,
            data={"role": "analyst"},
            format="json",
        )
        self._assert_analyst_403(
            "patch", path, data={"role": "analyst"}, format="json"
        )

    def test_team_invite_create_viewer_forbidden(self):
        self._assert_viewer_403_unauth_401(
            "post",
            "/api/v1/team/invites/",
            data={"email": "x@example.com", "role": "viewer"},
            format="json",
        )
        self._assert_analyst_403(
            "post",
            "/api/v1/team/invites/",
            data={"email": "x@example.com", "role": "viewer"},
            format="json",
        )

    def test_team_invite_resend_revoke_viewer_and_analyst_forbidden(self):
        invite = Invite.objects.create(
            tenant=self.roles.tenant,
            email="invitee@sec01-rbac.test",
            role=User.Role.VIEWER,
            invited_by=self.roles.admin,
        )
        for suffix in ("resend", "revoke"):
            path = f"/api/v1/team/invites/{invite.id}/{suffix}/"
            with self.subTest(path=path):
                self._assert_viewer_403_unauth_401(
                    "post", path, data={}, format="json"
                )
                self._assert_analyst_403("post", path, data={}, format="json")

    def test_connector_create_manago_viewer_forbidden(self):
        self._assert_viewer_403_unauth_401(
            "post",
            "/api/v1/connectors/",
            data={
                "name": "manago_ai",
                "config": {"workspace_id": "c1", "api_key": "x"},
            },
            format="json",
        )

    def test_connector_shopify_start_viewer_forbidden(self):
        self._assert_viewer_403_unauth_401(
            "post",
            "/api/v1/connectors/shopify/start/",
            data={"shop": "example.myshopify.com"},
            format="json",
        )

    def test_connector_fetch_viewer_and_analyst_forbidden(self):
        for path in (
            "/api/v1/connectors/shopify/fetch/",
            "/api/v1/connectors/manago_ai/fetch/",
        ):
            with self.subTest(path=path):
                self._assert_viewer_403_unauth_401(
                    "post", path, data={}, format="json"
                )
                self._assert_analyst_403("post", path, data={}, format="json")

    def test_connector_disconnect_viewer_forbidden(self):
        fake_id = str(uuid.uuid4())
        self._assert_viewer_403_unauth_401(
            "delete", f"/api/v1/connectors/{fake_id}/"
        )

    def test_connector_bootstrap_viewer_and_analyst_forbidden(self):
        # Admin-only; role gate runs before connector lookup (fake id → 403).
        fake_id = str(uuid.uuid4())
        path = f"/api/v1/connectors/{fake_id}/bootstrap/"
        self._assert_viewer_403_unauth_401("get", path)
        self._assert_analyst_403("get", path)

    def test_connector_manago_owners_put_viewer_forbidden(self):
        self._assert_viewer_403_unauth_401(
            "put",
            "/api/v1/connectors/manago_ai/owners/",
            data={"owner": "a@example.com"},
            format="json",
        )

    def test_connector_manago_api_v3_key_viewer_forbidden(self):
        path = "/api/v1/connectors/manago_ai/api-v3-key/"
        self._assert_viewer_403_unauth_401(
            "put",
            path,
            data={"api_v3_key": "shpat_test_key_value_xxxxxxxx"},
            format="json",
        )
        self._assert_viewer_403_unauth_401("delete", path)

    def test_tenant_viewset_patch_viewer_forbidden(self):
        self._assert_viewer_403_unauth_401(
            "patch",
            f"/api/v1/tenants/{self.roles.tenant.slug}/",
            data={"name": "Blocked"},
            format="json",
        )
        self._assert_analyst_403(
            "patch",
            f"/api/v1/tenants/{self.roles.tenant.slug}/",
            data={"name": "Blocked"},
            format="json",
        )

    def test_tenant_viewset_create_destroy_forbidden_for_viewer(self):
        self._assert_viewer_403_unauth_401(
            "post",
            "/api/v1/tenants/",
            data={"name": "Evil", "slug": "evil"},
            format="json",
        )
        self._assert_viewer_403_unauth_401(
            "delete",
            f"/api/v1/tenants/{self.roles.tenant.slug}/",
        )

    def test_tenant_viewset_create_destroy_forbidden_for_analyst(self):
        # Create/destroy always 403 for every product role (no existence leak).
        self._assert_analyst_403(
            "post",
            "/api/v1/tenants/",
            data={"name": "Evil", "slug": "evil-analyst"},
            format="json",
        )
        self._assert_analyst_403(
            "delete",
            f"/api/v1/tenants/{self.roles.tenant.slug}/",
        )
