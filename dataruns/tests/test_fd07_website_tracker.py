"""FD-07 website scrape + marker tests; FD-03 optional assemble."""

from __future__ import annotations

import io
import unittest
from types import SimpleNamespace

from dataruns.dcs.assemble import assemble_dcs_score
from dataruns.dcs.executors.foundation import (
    ConnectorGateInput,
    FoundationGateContext,
    evaluate_fd_07,
)
from dataruns.dcs.master import load_check_master_from_json
from dataruns.dcs.scrapers.company_website import (
    find_salesmanago_markers,
    normalize_company_domain,
)
from dataruns.dcs.types import CheckResult


SAMPLE_SM_HTML = """
<html><head></head><body>
<script type="text/javascript">
    var _smid = "58b12a8ce6013316";
    var _smapp = 1;
    (function(w, r, a, sm, s) {
        w['SalesmanagoObject'] = r;
        sm = document.createElement('script');
        sm.src = a;
    })(window, 'sm', 'https://www.salesmanago.pl/static/sm.js');
</script>
</body></html>
"""

PLAIN_HTML = "<html><body><h1>Hello</h1></body></html>"


class FakeHTTPResponse:
    def __init__(self, body: bytes, *, status: int = 200, url: str = "https://example.com/"):
        self._body = body
        self.status = status
        self._url = url
        self.headers = SimpleNamespace(get_content_charset=lambda: "utf-8")

    def read(self, n: int = -1) -> bytes:
        if n < 0:
            return self._body
        return self._body[:n]

    def getcode(self) -> int:
        return self.status

    def geturl(self) -> str:
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _opener_for(html: str):
    body = html.encode("utf-8")

    def opener(request, timeout=12):
        return FakeHTTPResponse(body, url=request.full_url)

    return opener


class MarkerAndDomainTests(unittest.TestCase):
    def test_normalize_domain(self):
        self.assertEqual(normalize_company_domain("https://Lumera.skin/"), "lumera.skin")
        self.assertIsNone(normalize_company_domain("localhost"))
        self.assertIsNone(normalize_company_domain(""))

    def test_markers_on_sample_snippet(self):
        matched = find_salesmanago_markers(SAMPLE_SM_HTML)
        self.assertIn("_smid", matched)
        self.assertIn("www.salesmanago.pl", matched)
        self.assertIn("SalesmanagoObject", matched)

    def test_no_markers_on_plain_html(self):
        self.assertEqual(find_salesmanago_markers(PLAIN_HTML), [])


class Fd07ScrapeTests(unittest.TestCase):
    def test_scrape_pass_with_markers(self):
        ctx = FoundationGateContext(
            manago=ConnectorGateInput(
                platform="manago_ai", connected=True, connector_status="connected"
            ),
            company_website_domain="example.com",
            website_scrape_opener=_opener_for(SAMPLE_SM_HTML),
        )
        result = evaluate_fd_07(ctx)
        self.assertEqual(result.status, "PASS")

    def test_scrape_fail_without_markers(self):
        ctx = FoundationGateContext(
            manago=ConnectorGateInput(
                platform="manago_ai", connected=True, connector_status="connected"
            ),
            company_website_domain="example.com",
            website_scrape_opener=_opener_for(PLAIN_HTML),
        )
        result = evaluate_fd_07(ctx)
        self.assertEqual(result.status, "FAIL")
        self.assertEqual(result.reason_code, "RC-12")

    def test_signals_pass_even_if_scrape_fails(self):
        ctx = FoundationGateContext(
            manago=ConnectorGateInput(
                platform="manago_ai",
                connected=True,
                connector_status="connected",
                visit_events_recent=True,
                smclient_cookie_seen=True,
            ),
            company_website_domain="example.com",
            website_scrape_opener=_opener_for(PLAIN_HTML),
        )
        result = evaluate_fd_07(ctx)
        self.assertEqual(result.status, "PASS")

    def test_storefront_scrape_pass_when_company_domain_missing(self):
        ctx = FoundationGateContext(
            manago=ConnectorGateInput(
                platform="manago_ai",
                connected=True,
                connector_status="connected",
                visit_events_recent=False,
                smclient_cookie_seen=False,
                tracking_active=False,
                tracking_measurable=True,
            ),
            company_website_domain=None,
            storefront_scrape_hosts=["shop.myshopify.com"],
            website_scrape_opener=_opener_for(SAMPLE_SM_HTML),
        )
        result = evaluate_fd_07(ctx)
        self.assertEqual(result.status, "PASS")

    def test_password_wall_is_unknown_not_fail(self):
        password_html = (
            "<html><body><form action=/password>"
            '<input name="password"/>shopify storefront_password</form></body></html>'
        )

        def opener(request, timeout=12):
            return FakeHTTPResponse(
                password_html.encode("utf-8"),
                url="https://shop.myshopify.com/password",
            )

        ctx = FoundationGateContext(
            manago=ConnectorGateInput(
                platform="manago_ai",
                connected=True,
                connector_status="connected",
                tracking_measurable=False,
            ),
            company_website_domain=None,
            storefront_scrape_hosts=["shop.myshopify.com"],
            website_scrape_opener=opener,
        )
        result = evaluate_fd_07(ctx)
        self.assertEqual(result.status, "UNKNOWN")
        self.assertEqual(result.reason_code, "MISSING_INPUT:tracking")

    def test_unknown_without_domain_or_signals(self):
        ctx = FoundationGateContext(
            manago=ConnectorGateInput(
                platform="manago_ai", connected=True, connector_status="connected"
            ),
            company_website_domain=None,
            skip_website_scrape=True,
        )
        result = evaluate_fd_07(ctx)
        self.assertEqual(result.status, "UNKNOWN")
        self.assertEqual(result.reason_code, "MISSING_INPUT:tracking")


class Fd03OptionalAssembleTests(unittest.TestCase):
    def test_fd03_optional_in_master(self):
        master = load_check_master_from_json()
        self.assertTrue(master.by_id()["FD-03"].is_optional)
        self.assertFalse(master.by_id()["FD-07"].is_optional)

    def test_fd03_fail_does_not_block_when_optional(self):
        master = load_check_master_from_json()
        results = []
        for check in master.checks:
            if check.check_id == "FD-03":
                status = "FAIL"
                reason = "RC-12"
            else:
                status = "PASS"
                reason = None
            results.append(
                CheckResult(
                    check_id=check.check_id,
                    status=status,
                    reason_code=reason,
                    numeric_weight=check.numeric_weight,
                )
            )
        dcs = assemble_dcs_score(results, master=master, erp_in_scope=True)
        self.assertNotEqual(dcs.run_state, "BLOCKED")
        self.assertEqual(dcs.blocking_gates_failed, 0)


if __name__ == "__main__":
    unittest.main()
