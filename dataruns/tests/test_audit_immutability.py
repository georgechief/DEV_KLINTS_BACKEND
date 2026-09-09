"""Postgres immutability triggers for audit_logs (PRD-POLISH-01 §2.4)."""

from __future__ import annotations

from django.db import connection, transaction
from django.db.utils import DatabaseError, IntegrityError, ProgrammingError
from django.test import TransactionTestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from dataruns.audit import append_audit_event, verify_audit_chain_for_company
from dataruns.audit_views import AuditEventMarkReadView
from dataruns.models import AuditLog
from tenants.models import Company, Tenant, User


class AuditLogImmutabilityTests(TransactionTestCase):
    """Triggers require TransactionTestCase so migrations apply per connection."""

    def setUp(self):
        self.tenant = Tenant.objects.create(name="Immutability Co", slug="immut-co")
        self.company = Company.objects.create(
            tenant=self.tenant,
            name="Immutability Co",
            domain="immut.co",
        )
        self.user = User.objects.create_user(
            email="admin@immut.co",
            password="TestPass123!",
            name="Admin",
            tenant=self.tenant,
            role=User.Role.ADMIN,
            email_verified=True,
            is_active=True,
        )
        self.factory = APIRequestFactory()

    def _append_pair(self) -> tuple[AuditLog, AuditLog]:
        first = append_audit_event(
            company=self.company,
            action="connector.connected",
            summary="Shopify connected",
            performed_by=self.user.email,
            metadata={"platform": "shopify"},
        )
        second = append_audit_event(
            company=self.company,
            action="workspace.updated",
            summary="Workspace updated",
            performed_by=self.user.email,
            metadata={"fields": ["name"]},
        )
        return first, second

    def test_append_two_events_chain_links_and_verify_clean(self):
        first, second = self._append_pair()
        self.assertEqual(second.prev_hash, first.entry_hash)
        self.assertEqual(verify_audit_chain_for_company(company=self.company), [])

    def test_update_audit_read_persists_and_hash_unchanged(self):
        _, second = self._append_pair()
        before_hash = second.entry_hash
        AuditLog.objects.filter(pk=second.pk).update(audit_read=True)
        second.refresh_from_db()
        self.assertTrue(second.audit_read)
        self.assertEqual(second.entry_hash, before_hash)
        self.assertEqual(verify_audit_chain_for_company(company=self.company), [])

    def test_update_summary_is_reverted(self):
        _, second = self._append_pair()
        original_summary = second.summary
        AuditLog.objects.filter(pk=second.pk).update(summary="tampered")
        second.refresh_from_db()
        self.assertEqual(second.summary, original_summary)

    def test_update_entry_hash_is_reverted(self):
        _, second = self._append_pair()
        original_hash = second.entry_hash
        AuditLog.objects.filter(pk=second.pk).update(entry_hash="0" * 64)
        second.refresh_from_db()
        self.assertEqual(second.entry_hash, original_hash)
        self.assertEqual(verify_audit_chain_for_company(company=self.company), [])

    def test_delete_raises_and_row_remains(self):
        _, second = self._append_pair()
        entry_id = second.id
        with self.assertRaises((IntegrityError, DatabaseError, ProgrammingError)):
            with transaction.atomic():
                AuditLog.objects.filter(pk=entry_id).delete()
        self.assertTrue(AuditLog.objects.filter(pk=entry_id).exists())

    def test_raw_sql_delete_raises(self):
        _, second = self._append_pair()
        entry_id = second.id
        with self.assertRaises((IntegrityError, DatabaseError, ProgrammingError)):
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(
                        "DELETE FROM audit_logs WHERE id = %s",
                        [str(entry_id)],
                    )
        self.assertTrue(AuditLog.objects.filter(pk=entry_id).exists())

    def test_raw_sql_summary_tamper_is_reverted(self):
        _, second = self._append_pair()
        original_summary = second.summary
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE audit_logs SET summary = %s WHERE id = %s",
                ["hacked", str(second.id)],
            )
        second.refresh_from_db()
        self.assertEqual(second.summary, original_summary)

    def test_mark_read_api_still_works(self):
        _, second = self._append_pair()
        before_hash = second.entry_hash
        request = self.factory.post(
            f"/api/v1/audit/events/{second.id}/mark-read/",
            {},
            format="json",
        )
        force_authenticate(request, user=self.user)
        response = AuditEventMarkReadView.as_view()(
            request,
            event_id=str(second.id),
        )
        self.assertEqual(response.status_code, 200)
        second.refresh_from_db()
        self.assertTrue(second.audit_read)
        self.assertEqual(second.entry_hash, before_hash)
        self.assertEqual(verify_audit_chain_for_company(company=self.company), [])
