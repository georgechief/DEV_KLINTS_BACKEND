"""Manago upsert wire format — singular ``contact`` + root properties."""

from __future__ import annotations

from unittest.mock import patch

from django.test import SimpleTestCase

from dataruns.writebacks.adapters.manago_transport import (
    ManagoWriteContext,
    _upsert_request_payload,
    upsert_contacts,
)


class ManagoUpsertPayloadTests(SimpleTestCase):
    def test_detail_set_uses_singular_contact_and_root_properties(self):
        payload = _upsert_request_payload(
            owner="owner@test.com",
            contact={
                "email": "consent@example.com",
                "contactId": "mc-1",
                "properties": {"klints_consent_evidence": "shopify_verified"},
            },
        )
        self.assertNotIn("contacts", payload)
        self.assertEqual(payload["contact"]["email"], "consent@example.com")
        self.assertEqual(
            payload["properties"]["klints_consent_evidence"],
            "shopify_verified",
        )
        self.assertNotIn("properties", payload["contact"])

    def test_blank_email_is_omitted(self):
        payload = _upsert_request_payload(
            owner="owner@test.com",
            contact={"email": "", "contactId": "mc-1", "properties": {"k": "v"}},
        )
        self.assertNotIn("email", payload["contact"])
        self.assertEqual(payload["contact"]["contactId"], "mc-1")

    def test_empty_string_property_value_is_preserved(self):
        """Rollback clears absent priors with "" — transport must not drop it."""
        payload = _upsert_request_payload(
            owner="owner@test.com",
            contact={
                "email": "consent@example.com",
                "contactId": "mc-1",
                "properties": {"klints_consent_evidence": ""},
            },
        )
        self.assertEqual(payload["properties"]["klints_consent_evidence"], "")

    @patch("dataruns.writebacks.adapters.manago_transport._post_manago")
    def test_upsert_contacts_posts_contact_not_contacts(self, mock_post):
        mock_post.return_value = {"success": True}
        ctx = ManagoWriteContext(
            endpoint="https://app2.manago.ai",
            client_id="c",
            api_secret="s",
            owner="o@test.com",
        )
        upsert_contacts(
            ctx,
            [{"email": "a@b.com", "properties": {"klints_x": "1"}}],
        )
        sent = mock_post.call_args.kwargs["payload"]
        self.assertIn("contact", sent)
        self.assertNotIn("contacts", sent)
        self.assertEqual(sent["contact"]["email"], "a@b.com")
        self.assertEqual(sent["properties"]["klints_x"], "1")
