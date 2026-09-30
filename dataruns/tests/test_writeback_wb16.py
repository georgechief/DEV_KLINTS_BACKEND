"""PRD-WB-16 — CI-03 contact merge plan (Phase A) tests."""

from __future__ import annotations

from decimal import Decimal

from django.test import SimpleTestCase, TestCase, override_settings

from dataruns.dcs.executors.identity import _ci03_mismatches, evaluate_ci_03
from dataruns.dcs.identity_join import build_identity_snapshot
from dataruns.models import Contact, Order
from dataruns.tests.test_identity_checks import _base_snapshot, _ctx
from dataruns.writebacks.messages import writeback_execute_denial_detail
from dataruns.writebacks.pipeline import run_writeback_pipeline
from dataruns.writebacks.registry import get_check_mapping
from dataruns.writebacks.rollback_strategy import rollback_supported
from dataruns.writebacks.transform import (
    _ci03_evidence_rows,
    build_intents_from_mapping,
)
from tenants.models import Company, Connector, Tenant


class Ci03MismatchHelperTests(SimpleTestCase):
    def test_drivers_survive_full_merge_sample(self):
        candidates = [
            {
                "side": "merge_candidate",
                "cluster_kind": "externalId",
                "cluster_key": str(i),
                "survivor_manago_id": f"s{i}",
                "loser_manago_ids": [f"l{i}"],
                "safety_class": "SAFE_DELETE",
            }
            for i in range(50)
        ]
        mismatches = _ci03_mismatches(
            {
                "merge_candidates": candidates,
                "manago_contacts": 200,
                "duplicate_extra_contacts_total": 80,
            }
        )
        self.assertEqual(
            sum(1 for m in mismatches if m.get("side") == "merge_candidate"), 50
        )
        drivers = [m.get("driver") for m in mismatches if m.get("side") == "driver"]
        self.assertIn("duplicate_rate", drivers)
        self.assertIn("cluster_cap_note", drivers)


class EvaluateCi03ProvenanceTests(SimpleTestCase):
    def test_fail_attaches_merge_candidates(self):
        result = evaluate_ci_03(
            _ctx(
                _base_snapshot(
                    manago_contacts=100,
                    duplicate_cluster_counts={"email": 0, "phone": 0, "externalId": 12},
                    duplicate_extra_contacts_total=12,
                    merge_candidates=[
                        {
                            "side": "merge_candidate",
                            "cluster_kind": "externalId",
                            "cluster_key": "1001",
                            "survivor_manago_id": "a",
                            "loser_manago_ids": ["b"],
                            "safety_class": "SAFE_DELETE",
                        }
                    ],
                )
            )
        )
        self.assertEqual(result.status, "FAIL")
        mismatches = (result.provenance or {}).get("mismatches") or []
        self.assertTrue(
            any(m.get("side") == "merge_candidate" for m in mismatches)
        )


class Ci03EmitAndTransformTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="WB16T", slug="wb16-emit")
        self.company = Company.objects.create(
            tenant=self.tenant, name="WB16 Co", domain="wb16-emit.test"
        )

    def test_survivor_prefers_purchase_spine_over_oldest(self):
        Contact.objects.create(
            company=self.company,
            source="manago_ai",
            external_id="old-uuid",
            email="dup@example.com",
            link_key="9001",
        )
        newer = Contact.objects.create(
            company=self.company,
            source="manago_ai",
            external_id="new-uuid",
            email="dup@example.com",
            link_key="9001",
        )
        Contact.objects.create(
            company=self.company,
            source="shopify",
            external_id="9001",
            email="dup@example.com",
        )
        Order.objects.create(
            company=self.company,
            contact=newer,
            source="manago_ai",
            external_id="evt-1",
            amount=Decimal("10.00"),
            currency="USD",
            status="paid",
        )
        identity = build_identity_snapshot(company=self.company)["identity"]
        candidates = identity.get("merge_candidates") or []
        self.assertTrue(candidates)
        row = next(
            c
            for c in candidates
            if c.get("cluster_kind") == "externalId" and c.get("cluster_key") == "9001"
        )
        self.assertEqual(row["survivor_manago_id"], "new-uuid")
        self.assertEqual(row["loser_manago_ids"], ["old-uuid"])
        self.assertEqual(row["safety_class"], "SAFE_DELETE")
        self.assertEqual(row["survivor_purchase_count"], 1)
        self.assertEqual(row["loser_purchase_count"], 0)

    def test_phone_cluster_quarantine(self):
        Contact.objects.create(
            company=self.company,
            source="manago_ai",
            external_id="p1",
            phone="+15550101",
            email="a@x.com",
        )
        Contact.objects.create(
            company=self.company,
            source="manago_ai",
            external_id="p2",
            phone="+15550101",
            email="b@x.com",
        )
        identity = build_identity_snapshot(company=self.company)["identity"]
        phone_rows = [
            c
            for c in (identity.get("merge_candidates") or [])
            if c.get("cluster_kind") == "phone"
        ]
        self.assertTrue(phone_rows)
        self.assertEqual(phone_rows[0]["safety_class"], "QUARANTINE")

    def test_loser_with_purchases_migrate(self):
        a = Contact.objects.create(
            company=self.company,
            source="manago_ai",
            external_id="m-a",
            email="both@example.com",
            link_key="8001",
        )
        b = Contact.objects.create(
            company=self.company,
            source="manago_ai",
            external_id="m-b",
            email="both@example.com",
            link_key="8001",
        )
        Contact.objects.create(
            company=self.company,
            source="shopify",
            external_id="8001",
            email="both@example.com",
        )
        Order.objects.create(
            company=self.company,
            contact=a,
            source="manago_ai",
            external_id="pa",
            amount=Decimal("5"),
            currency="USD",
            status="paid",
        )
        Order.objects.create(
            company=self.company,
            contact=b,
            source="manago_ai",
            external_id="pb",
            amount=Decimal("7"),
            currency="USD",
            status="paid",
        )
        identity = build_identity_snapshot(company=self.company)["identity"]
        row = next(
            c
            for c in (identity.get("merge_candidates") or [])
            if c.get("cluster_key") == "8001"
        )
        self.assertEqual(row["safety_class"], "MIGRATE_THEN_DELETE")

    def test_transform_builds_plan_intents(self):
        mapping = get_check_mapping("CI-03")
        intents = build_intents_from_mapping(
            company=self.company,
            mapping=mapping,
            evidence_rows=[
                {
                    "side": "merge_candidate",
                    "cluster_kind": "externalId",
                    "cluster_key": "1001",
                    "survivor_manago_id": "surv",
                    "loser_manago_ids": ["lose"],
                    "safety_class": "SAFE_DELETE",
                    "safety_reason": "loser_events_0_survivor_holds_link_key",
                    "person.email": "x@y.com",
                    "link_key": "1001",
                },
                {"side": "driver", "driver": "duplicate_rate", "rate": 0.1},
            ],
        )
        writeable = [i for i in intents if i.status in ("ready", "skipped", "error")]
        self.assertEqual(len(writeable), 1)
        intent = writeable[0]
        self.assertEqual(intent.op_kind, "contact_merge")
        self.assertEqual(intent.payload.get("mode"), "plan")
        self.assertEqual(intent.payload.get("survivor_id"), "surv")
        self.assertEqual(intent.payload.get("loser_ids"), ["lose"])
        ok, reason = rollback_supported(intent)
        self.assertFalse(ok)
        self.assertEqual(reason, "rollback_not_supported")

    def test_ci03_evidence_live_rebuild(self):
        Contact.objects.create(
            company=self.company,
            source="manago_ai",
            external_id="lr1",
            email="live@example.com",
            link_key="7001",
        )
        Contact.objects.create(
            company=self.company,
            source="manago_ai",
            external_id="lr2",
            email="live@example.com",
            link_key="7001",
        )
        Contact.objects.create(
            company=self.company,
            source="shopify",
            external_id="7001",
            email="live@example.com",
        )
        rows = _ci03_evidence_rows(company=self.company, rows=[], max_rows=50)
        self.assertTrue(rows)
        self.assertEqual(rows[0]["side"], "merge_candidate")


@override_settings(WRITEBACKS_ENABLED=False)
class Ci03PipelinePlanOnlyTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="WB16P", slug="wb16-pipe")
        self.company = Company.objects.create(
            tenant=self.tenant, name="WB16 Pipe", domain="wb16-pipe.test"
        )
        Connector.objects.create(
            company=self.company,
            name="manago_ai",
            type="cdp",
            status="connected",
        )
        Contact.objects.create(
            company=self.company,
            source="manago_ai",
            external_id="pipe-a",
            email="pipe@example.com",
            link_key="6001",
        )
        Contact.objects.create(
            company=self.company,
            source="manago_ai",
            external_id="pipe-b",
            email="pipe@example.com",
            link_key="6001",
        )
        Contact.objects.create(
            company=self.company,
            source="shopify",
            external_id="6001",
            email="pipe@example.com",
        )

    def test_execute_blocked_plan_only(self):
        result = run_writeback_pipeline(
            company=self.company,
            check_id="CI-03",
            mode="dry_run",
        )
        self.assertGreaterEqual(result.summary.ready, 1)
        blocked = run_writeback_pipeline(
            company=self.company,
            check_id="CI-03",
            mode="execute",
            approval_id="fake",
        )
        self.assertEqual(blocked.blocked_reason, "ci03_plan_only")
        detail = writeback_execute_denial_detail("ci03_plan_only")
        self.assertIn("plan-only", detail.lower())
