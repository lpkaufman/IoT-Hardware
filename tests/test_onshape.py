import unittest

from onshape_jira.onshape import (
    DOCUMENT_LIST_SEARCH_MAX_LIMIT,
    OnshapeClient,
    _document_list_item_id,
    _document_parent_folder_id,
    _global_treenodes_folder_path_segments,
    _join_folder_path_segments,
    webhook_registration_payload,
)


class OnshapeClientTest(unittest.TestCase):
    def test_company_search_request_limit_is_capped_at_api_max(self) -> None:
        self.assertEqual(DOCUMENT_LIST_SEARCH_MAX_LIMIT, 20)
        client = OnshapeClient("https://cad.onshape.com", "access-key", "secret-key")
        captured: list[str] = []

        def fake_request(method: str, path: str, *, body=None):  # type: ignore[no-untyped-def]
            captured.append(path)
            return {"items": []}

        client._request = fake_request  # type: ignore[method-assign]

        with self.assertLogs("onshape_jira.onshape", level="WARNING") as log_ctx:
            client.list_company_document_ids("company-1", page_limit=100)
        self.assertTrue(any("capping" in m for m in log_ctx.output))

        self.assertEqual(len(captured), 1)
        self.assertIn("limit=20", captured[0])
        self.assertNotIn("limit=100", captured[0])

    def test_authorization_header_uses_onshape_hmac_scheme(self):
        client = OnshapeClient("https://cad.onshape.com", "access-key", "secret-key")

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
        payload = webhook_registration_payload(
            "company-1", "https://app.example/webhook"
        )

        self.assertEqual(payload["companyId"], "company-1")
        self.assertEqual(payload["url"], "https://app.example/webhook")
        self.assertFalse(payload["isTransient"])
        self.assertIn("onshape.document.lifecycle.created", payload["events"])
        self.assertIn("onshape.model.lifecycle.createversion", payload["events"])
        self.assertIn("onshape.model.lifecycle.createworkspace", payload["events"])

    def test_list_company_document_ids_paginates_and_deduplicates(self):
        client = OnshapeClient("https://cad.onshape.com", "access-key", "secret-key")
        payloads = [
            {"items": [{"id": "d1"}, {"id": "d2"}]},
            {"items": [{"id": "d3"}]},
        ]
        captured: list[str] = []

        def fake_request(method: str, path: str, *, body=None):  # type: ignore[no-untyped-def]
            self.assertEqual(method, "GET")
            captured.append(path)
            idx = len(captured) - 1
            return payloads[idx] if idx < len(payloads) else {"items": []}

        client._request = fake_request  # type: ignore[method-assign]

        ids = client.list_company_document_ids("company-1", page_limit=2)

        self.assertEqual(ids, ["d1", "d2", "d3"])
        self.assertEqual(len(captured), 2)
        self.assertIn("offset=0", captured[0])
        self.assertIn("offset=2", captured[1])

    def test_document_list_item_id_prefers_top_level_id(self):
        self.assertEqual(
            _document_list_item_id({"id": "top", "document": {"id": "nested"}}),
            "top",
        )

    def test_document_parent_reads_parent_folder_keys(self):
        doc = {"name": "D", "parentId": "f-1"}
        self.assertEqual(_document_parent_folder_id(doc), "f-1")
        nested = {"document": {"parentFolderId": " f-2 ", "name": "Inner"}}
        self.assertEqual(_document_parent_folder_id(nested), "f-2")

    def test_global_treenodes_path_to_root_reorders_leaf_to_company(self):
        segments = _global_treenodes_folder_path_segments(
            {
                "pathToRoot": [
                    {"name": "Foxglove"},
                    {"name": "Team"},
                    {"name": "My Onshape"},
                ]
            }
        )
        joined = _join_folder_path_segments(segments)
        self.assertEqual(joined, "Team/Foxglove")

    def test_global_treenodes_path_from_root_keeps_order(self):
        segments = _global_treenodes_folder_path_segments(
            {
                "pathFromRoot": [
                    {"name": "Programs"},
                    {"name": "Foxglove"},
                ]
            }
        )
        joined = _join_folder_path_segments(segments)
        self.assertEqual(joined, "Programs/Foxglove")

    def test_global_treenodes_nested_node_payload(self):
        segments = _global_treenodes_folder_path_segments(
            {
                "node": {
                    "pathToRoot": [
                        {"name": "Inner"},
                        {"name": "Outer"},
                    ]
                }
            }
        )
        joined = _join_folder_path_segments(segments)
        self.assertEqual(joined, "Outer/Inner")


if __name__ == "__main__":
    unittest.main()
