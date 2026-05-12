import unittest

from onshape_jira.onshape import OnshapeClient, webhook_registration_payload


class OnshapeClientTest(unittest.TestCase):
    def test_authorization_header_uses_onshape_hmac_scheme(self):
        client = OnshapeClient(
            "https://cad.onshape.com", "access-key", "secret-key"
        )

        header = client._authorization_header(
            "GET",
            "https://cad.onshape.com/api/documents/doc-1?b=2",
            "0123456789abcdef",
            "Tue, 12 May 2026 20:41:00 GMT",
            "application/json",
        )

        self.assertTrue(header.startswith("On access-key:HmacSHA256:"))
        self.assertGreater(len(header.split(":")[-1]), 20)

    def test_company_webhook_payload_contains_document_events(self):
        payload = webhook_registration_payload("company-1", "https://app.example/webhook")

        self.assertEqual(payload["companyId"], "company-1")
        self.assertEqual(payload["url"], "https://app.example/webhook")
        self.assertFalse(payload["isTransient"])
        self.assertIn("onshape.document.lifecycle.created", payload["events"])
        self.assertIn("onshape.model.lifecycle.createversion", payload["events"])
        self.assertIn("onshape.model.lifecycle.createworkspace", payload["events"])


if __name__ == "__main__":
    unittest.main()
