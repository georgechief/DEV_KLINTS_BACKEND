"""Unit tests for human-readable Grafana → mailer formatting (no Django)."""

from __future__ import annotations

import unittest

from server import _format_alert


class FormatAlertTests(unittest.TestCase):
    def test_firing_nginx_subject_is_human(self):
        subject, _html, text = _format_alert(
            {
                "status": "firing",
                "title": (
                    "[FIRING:1] staging-logs-error-nginx "
                    "M3 OBS-01 (01 nginx warning)"
                ),
                "commonLabels": {
                    "service": "nginx",
                    "severity": "warning",
                    "alertname": "staging-logs-error-nginx",
                },
                "commonAnnotations": {
                    "summary": "Staging nginx is logging ERROR-like lines",
                },
                "alerts": [
                    {
                        "status": "firing",
                        "labels": {"service": "nginx"},
                        "annotations": {
                            "summary": "Staging nginx is logging ERROR-like lines",
                        },
                    }
                ],
            }
        )
        self.assertEqual(
            subject, "[Klints staging] ALERT — nginx error logs"
        )
        self.assertNotIn("[FIRING:1]", subject)
        self.assertNotIn("staging-logs-error-nginx", subject)
        self.assertIn("Status: FIRING", text)
        self.assertIn("service=nginx", text)
        self.assertIn("What happened:", text)
        self.assertIn("What to do:", text)

    def test_resolved_web_subject_is_human(self):
        subject, _html, text = _format_alert(
            {
                "status": "resolved",
                "title": (
                    "[RESOLVED] staging-logs-error-web "
                    "M3 OBS-01 (01 web warning)"
                ),
                "commonLabels": {
                    "service": "web",
                    "alertname": "staging-logs-error-web",
                },
                "commonAnnotations": {
                    "summary": "Staging web (Django API) is logging ERROR-like lines",
                },
                "alerts": [
                    {
                        "status": "resolved",
                        "labels": {"service": "web"},
                        "annotations": {
                            "summary": (
                                "Staging web (Django API) is logging ERROR-like lines"
                            ),
                        },
                    }
                ],
            }
        )
        self.assertEqual(
            subject, "[Klints staging] CLEARED — web (Django API) error logs"
        )
        self.assertNotIn("[RESOLVED]", subject)
        self.assertIn("Status: CLEARED", text)
        self.assertIn("No action needed", text)

    def test_contact_point_test_still_formats(self):
        subject, _html, text = _format_alert(
            {"status": "firing", "title": "Test alert", "message": "ping"}
        )
        self.assertTrue(subject.startswith("[Klints staging]"))
        self.assertIn("Status: FIRING", text)


if __name__ == "__main__":
    unittest.main()
