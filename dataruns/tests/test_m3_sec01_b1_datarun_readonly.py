"""B1 — /api/v1/dataruns/ is read-only for ALL roles (including Admin).

DCS terminal evidence must come from the scoring pipeline only.
Negatives: POST / PUT / PATCH / DELETE, including forged terminal metadata.
"""

from __future__ import annotations

from django.test import TestCase

from dataruns.dcs.enqueue import DCS_SCORE_DATA_RUN_NAME, DCS_SCORE_KIND
from dataruns.dcs.status import resolve_dcs_app_status
from dataruns.models import DataRun
from dataruns.tests.helpers_m3_sec01 import make_sec01_role_clients


class M3Sec01B1DataRunReadOnlyTests(TestCase):
    """Client B1 — no HTTP forge/delete of DataRun / DCS evidence."""

    def setUp(self):
        self.roles = make_sec01_role_clients(slug_prefix="sec01-b1")
        self.own_run = DataRun.objects.create(
            tenant=self.roles.tenant,
            name="seed-run",
            status=DataRun.Status.PENDING,
            metadata={"seed": True},
        )
        self._forge_body = {
            "name": DCS_SCORE_DATA_RUN_NAME,
            "status": DataRun.Status.SUCCEEDED,
            "metadata": {
                "kind": DCS_SCORE_KIND,
                "company_id": str(self.roles.company.id),
                "headline_score": 97.5,
                "check_results": [
                    {"check_id": "SP-07", "status": "PASS"},
                ],
            },
        }
        # Alternate shape some consumers also read (metadata.dcs_run.*).
        self._forge_nested_body = {
            "name": DCS_SCORE_DATA_RUN_NAME,
            "status": DataRun.Status.SUCCEEDED,
            "metadata": {
                "kind": DCS_SCORE_KIND,
                "company_id": str(self.roles.company.id),
                "dcs_run": {
                    "headline_score": 97.5,
                    "check_results": [
                        {"check_id": "SP-07", "status": "PASS"},
                    ],
                },
            },
        }

    def _clients(self):
        return (
            ("admin", self.roles.client_admin),
            ("analyst", self.roles.client_analyst),
            ("viewer", self.roles.client_viewer),
        )

    def test_get_list_and_retrieve_ok_all_roles(self):
        for role, client in self._clients():
            with self.subTest(role=role, method="list"):
                response = client.get("/api/v1/dataruns/")
                self.assertEqual(response.status_code, 200)
            with self.subTest(role=role, method="retrieve"):
                response = client.get(f"/api/v1/dataruns/{self.own_run.id}/")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data.get("id"), self.own_run.id)

    def test_post_forged_terminal_dcs_rejected_all_roles(self):
        before = DataRun.objects.filter(
            tenant=self.roles.tenant,
            name=DCS_SCORE_DATA_RUN_NAME,
        ).count()
        for role, client in self._clients():
            for label, body in (
                ("flat", self._forge_body),
                ("nested_dcs_run", self._forge_nested_body),
            ):
                with self.subTest(role=role, shape=label):
                    response = client.post(
                        "/api/v1/dataruns/",
                        body,
                        format="json",
                    )
                    self.assertEqual(
                        response.status_code,
                        405,
                        msg=(
                            f"{role} POST forge ({label}) → "
                            f"{response.status_code} {response.data}"
                        ),
                    )
        self.assertEqual(
            DataRun.objects.filter(
                tenant=self.roles.tenant,
                name=DCS_SCORE_DATA_RUN_NAME,
            ).count(),
            before,
        )

    def test_forged_post_does_not_unlock_app_status(self):
        """Client repro: forged 97.5 must not flip app_access / score ready."""
        before = resolve_dcs_app_status(company=self.roles.company)
        self.assertNotEqual(before.get("app_access"), "unlocked")

        response = self.roles.client_viewer.post(
            "/api/v1/dataruns/",
            self._forge_body,
            format="json",
        )
        self.assertEqual(response.status_code, 405)

        after = resolve_dcs_app_status(company=self.roles.company)
        self.assertEqual(after.get("app_access"), before.get("app_access"))
        self.assertNotEqual(after.get("app_access"), "unlocked")
        self.assertFalse(
            DataRun.objects.filter(
                tenant=self.roles.tenant,
                name=DCS_SCORE_DATA_RUN_NAME,
                status=DataRun.Status.SUCCEEDED,
            ).exists()
        )

    def test_put_patch_delete_own_run_rejected_all_roles(self):
        for role, client in self._clients():
            with self.subTest(role=role, method="put"):
                response = client.put(
                    f"/api/v1/dataruns/{self.own_run.id}/",
                    {
                        "name": DCS_SCORE_DATA_RUN_NAME,
                        "status": DataRun.Status.SUCCEEDED,
                        "metadata": self._forge_body["metadata"],
                    },
                    format="json",
                )
                self.assertEqual(response.status_code, 405)
            with self.subTest(role=role, method="patch"):
                response = client.patch(
                    f"/api/v1/dataruns/{self.own_run.id}/",
                    {
                        "status": DataRun.Status.SUCCEEDED,
                        "metadata": self._forge_body["metadata"],
                    },
                    format="json",
                )
                self.assertEqual(response.status_code, 405)
            with self.subTest(role=role, method="delete"):
                response = client.delete(f"/api/v1/dataruns/{self.own_run.id}/")
                self.assertEqual(response.status_code, 405)

        self.own_run.refresh_from_db()
        self.assertEqual(self.own_run.name, "seed-run")
        self.assertEqual(self.own_run.status, DataRun.Status.PENDING)
        self.assertEqual(self.own_run.metadata, {"seed": True})
        self.assertTrue(DataRun.objects.filter(pk=self.own_run.id).exists())

    def test_admin_dcs_runs_post_still_allowed_method(self):
        """Legitimate score start stays on /dcs/runs/ (not removed by B1)."""
        response = self.roles.client_admin.post(
            "/api/v1/dcs/runs/",
            {},
            format="json",
        )
        # Must not be method-not-allowed; empty body may 400/422 — still proves path exists.
        self.assertNotEqual(response.status_code, 405)
        self.assertLess(response.status_code, 500)

    def test_unauthenticated_mutate_401_or_405(self):
        """Anon must not create; DRF may 401 before method check."""
        response = self.roles.client_anon.post(
            "/api/v1/dataruns/",
            self._forge_body,
            format="json",
        )
        self.assertIn(response.status_code, (401, 405))
        self.assertFalse(
            DataRun.objects.filter(
                tenant=self.roles.tenant,
                name=DCS_SCORE_DATA_RUN_NAME,
            ).exists()
        )
