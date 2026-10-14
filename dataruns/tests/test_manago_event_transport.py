"""Manago batchAddContactExtEvent wire shape (contactEvent nesting)."""

from __future__ import annotations

from unittest.mock import patch

from django.test import SimpleTestCase

from dataruns.connectors.manago_ai.client import ManagoClientError
from dataruns.writebacks.adapters.manago_transport import (
    ManagoWriteContext,
    _wrap_batch_contact_event,
    batch_add_external_events,
)


class WrapBatchContactEventTests(SimpleTestCase):
    def test_wraps_flat_payload_under_contact_event(self):
        wrapped = _wrap_batch_contact_event(
            {
                "contactId": "mc-1",
                "email": "both@example.com",
                "externalId": "ord-1",
                "contactExtEventType": "RETURN",
                "value": 12.5,
            }
        )
        self.assertEqual(wrapped.get("contactId"), "mc-1")
        self.assertNotIn("email", wrapped)
        event = wrapped["contactEvent"]
        self.assertEqual(event["contactExtEventType"], "RETURN")
        self.assertEqual(event["externalId"], "ord-1")
        self.assertEqual(event["value"], 12.5)
        self.assertIsInstance(event.get("date"), int)

    def test_email_only_when_no_contact_id(self):
        wrapped = _wrap_batch_contact_event(
            {
                "email": "solo@example.com",
                "externalId": "ord-2",
                "contactExtEventType": "PURCHASE",
                "value": 1,
            }
        )
        self.assertEqual(wrapped.get("email"), "solo@example.com")
        self.assertNotIn("contactId", wrapped)
        self.assertEqual(wrapped["contactEvent"]["contactExtEventType"], "PURCHASE")

    def test_preserves_existing_contact_event_shape(self):
        wrapped = _wrap_batch_contact_event(
            {
                "contactId": "mc-2",
                "contactEvent": {
                    "contactExtEventType": "RETURN",
                    "externalId": "ord-3",
                    "value": 9,
                    "date": 1_700_000_000_000,
                },
            }
        )
        self.assertEqual(wrapped["contactEvent"]["date"], 1_700_000_000_000)

    def test_requires_event_type(self):
        with self.assertRaises(ManagoClientError):
            _wrap_batch_contact_event(
                {"contactId": "mc-3", "externalId": "ord-4", "value": 1}
            )


class BatchAddExternalEventsWireTests(SimpleTestCase):
    @patch("dataruns.writebacks.adapters.manago_transport._post_manago")
    def test_posts_nested_contact_event(self, mock_post):
        mock_post.return_value = {"success": True}
        ctx = ManagoWriteContext(
            endpoint="https://app.manago.ai",
            client_id="cid",
            api_secret="secret",
            owner="owner@test.com",
        )
        batch_add_external_events(
            ctx,
            [
                {
                    "contactId": "mc-9",
                    "externalId": "189",
                    "contactExtEventType": "RETURN",
                    "value": 299.95,
                }
            ],
        )
        payload = mock_post.call_args.kwargs["payload"]
        self.assertEqual(payload["owner"], "owner@test.com")
        event = payload["events"][0]
        self.assertEqual(event["contactId"], "mc-9")
        self.assertEqual(event["contactEvent"]["contactExtEventType"], "RETURN")
        self.assertEqual(event["contactEvent"]["externalId"], "189")
        self.assertNotIn("contactExtEventType", event)
