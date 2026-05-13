import logging
import os
import ssl
import unittest
from unittest import mock
from urllib.error import URLError

import onshape_jira.http as http_mod
from onshape_jira.http import HttpClientError, JsonHttpClient


class HttpTlsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        lg = logging.getLogger("onshape_jira.http")
        cls._orig_level = lg.level
        lg.setLevel(logging.CRITICAL + 1)

    @classmethod
    def tearDownClass(cls) -> None:
        lg = logging.getLogger("onshape_jira.http")
        lg.setLevel(cls._orig_level)

    def tearDown(self) -> None:
        http_mod._HttpsSkipVerifyState.warned = False
        http_mod._MissingCertifiState.warned = False

    def test_non_https_returns_no_context(self) -> None:
        self.assertIsNone(http_mod._https_ssl_context("http://localhost/foo"))

    def test_https_without_skip_uses_explicit_context(self) -> None:
        ctx = http_mod._https_ssl_context("https://cad.onshape.com/api/foo")
        self.assertIsNotNone(ctx)
        self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED)

    def test_https_skip_verify_env(self) -> None:
        with mock.patch.dict(os.environ, {"HTTPS_SKIP_VERIFY": "1"}, clear=False):
            http_mod._HttpsSkipVerifyState.warned = False
            ctx = http_mod._https_ssl_context("https://example.com/")
            self.assertIsNotNone(ctx)
            self.assertEqual(ctx.verify_mode, ssl.CERT_NONE)

    def test_request_json_passes_timeout_to_urlopen(self) -> None:
        with mock.patch("onshape_jira.http.urlopen") as mocked:
            enter = mocked.return_value.__enter__.return_value
            enter.read.return_value = b"{}"

            JsonHttpClient(timeout_seconds=42.5).request_json(
                "GET", "https://example.com/foo", headers={}
            )

            mocked.assert_called_once()
            self.assertEqual(mocked.call_args.kwargs["timeout"], 42.5)

    def test_urlerror_maps_to_http_client_error(self) -> None:
        underlying = TimeoutError("[Errno 60] boom")
        with mock.patch(
            "onshape_jira.http.urlopen",
            side_effect=URLError(reason=underlying),
        ):
            client = JsonHttpClient(timeout_seconds=5)
            with self.assertRaises(HttpClientError) as ctx:
                client.request_json("GET", "https://example.com/x", headers={})
            self.assertEqual(ctx.exception.status, 0)


if __name__ == "__main__":
    unittest.main()
