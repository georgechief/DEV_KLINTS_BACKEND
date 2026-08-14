"""Batch size and diff hash unit tests."""

from django.test import TestCase, override_settings

from dataruns.writebacks.hashing import compute_diff_hash
from dataruns.writebacks.pipeline import _execute_intents
from dataruns.writebacks.types import WriteIntent
from tenants.models import Company, Tenant


class WritebackBatchTests(TestCase):
    def setUp(self):
        tenant = Tenant.objects.create(name="T", slug="wb-batch")
        self.company = Company.objects.create(
            tenant=tenant,
            name="Co",
            domain="wb-batch.test",
        )

    def test_compute_diff_hash_stable(self):
        intent = WriteIntent(
            check_id="CI-01",
            op_kind="contact_upsert",
            operation="manago.contact_upsert.shopify_only",
            target_system="manago",
            entity_type="contact",
            entity_key="a@b.com",
            payload={"email": "a@b.com"},
        )
        first = compute_diff_hash([intent])
        second = compute_diff_hash([intent])
        self.assertEqual(first, second)
        self.assertEqual(len(first), 64)

    @override_settings(WRITEBACK_MANAGO_BATCH_MAX=1000)
    def test_execute_chunks_by_batch_size(self):
        intents = [
            WriteIntent(
                check_id="CI-01",
                op_kind="contact_upsert",
                operation=f"op-{index}",
                target_system="manago",
                entity_type="contact",
                entity_key=f"user{index}@example.com",
                payload={"email": f"user{index}@example.com"},
                status="ready",
                capability_id="RESTV2.CONTACT.UPSERT",
            )
            for index in range(3)
        ]

        calls: list[int] = []

        class FakeAdapter:
            def execute(self, company, group, *, approval_id, idempotency_key):
                calls.append(len(group))
                for row in group:
                    row.status = "executed"
                return group

        with patch_adapter(FakeAdapter()):
            merged, status = _execute_intents(
                company=self.company,
                check_id="CI-01",
                intents=intents,
                batch_size=2,
                diff_hash="abc",
                approval_id=None,
            )

        self.assertEqual(status, "executed")
        self.assertEqual(calls, [2, 1])
        self.assertEqual(sum(1 for row in merged if row.status == "executed"), 3)

    @override_settings(WRITEBACK_MANAGO_BATCH_MAX=1000)
    def test_execute_stops_on_chunk_failure_partial(self):
        intents = [
            WriteIntent(
                check_id="CI-01",
                op_kind="contact_upsert",
                operation=f"op-{index}",
                target_system="manago",
                entity_type="contact",
                entity_key=f"user{index}@example.com",
                payload={"email": f"user{index}@example.com"},
                status="ready",
                capability_id="RESTV2.CONTACT.UPSERT",
            )
            for index in range(3)
        ]

        class FlakyAdapter:
            def __init__(self):
                self.calls = 0

            def execute(self, company, group, *, approval_id, idempotency_key):
                self.calls += 1
                if self.calls == 1:
                    group[0].status = "executed"
                    group[1].status = "error"
                    group[1].error_reason = "manago_write_failed"
                    return group
                for row in group:
                    row.status = "executed"
                return group

        adapter = FlakyAdapter()
        with patch_adapter(adapter):
            merged, status = _execute_intents(
                company=self.company,
                check_id="CI-01",
                intents=intents,
                batch_size=2,
                diff_hash="abc",
                approval_id=None,
            )

        self.assertEqual(status, "partial")
        self.assertEqual(sum(1 for row in merged if row.status == "executed"), 1)
        self.assertEqual(adapter.calls, 1)


class patch_adapter:
    def __init__(self, adapter):
        self.adapter = adapter

    def __enter__(self):
        from unittest.mock import patch

        self._patch = patch(
            "dataruns.writebacks.pipeline.get_adapter",
            return_value=self.adapter,
        )
        return self._patch.start()

    def __exit__(self, *args):
        self._patch.stop()
