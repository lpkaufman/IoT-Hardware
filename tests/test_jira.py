import unittest

from onshape_jira.config import JiraConfig
from onshape_jira.jira import JiraClient, plain_text_from_adf


class RecordingHttpClient:
    def __init__(self):
        self.requests = []

    def request_json(self, method, url, *, headers=None, body=None):
        self.requests.append(
            {"method": method, "url": url, "headers": headers or {}, "body": body}
        )
        if method == "POST":
            return {"key": "IOT-123"}
        return None


class JiraClientTest(unittest.TestCase):
    def test_create_story_sets_required_fields(self):
        http = RecordingHttpClient()
        config = JiraConfig(
            base_url="https://example.atlassian.net",
            email="robot@example.com",
            api_token="secret",
            project_key="IOT",
            investments_category_field_id="customfield_10010",
            workflow_field_id="customfield_10011",
        )
        client = JiraClient(config, http_client=http)

        issue_key = client.create_story(
            summary="Gateway Controller",
            description_lines=["Tabs:", "Part Studio", "Assembly"],
            document_id="doc-1",
        )

        self.assertEqual(issue_key, "IOT-123")
        request = http.requests[0]
        self.assertEqual(request["method"], "POST")
        fields = request["body"]["fields"]
        self.assertEqual(fields["project"], {"key": "IOT"})
        self.assertEqual(fields["issuetype"], {"name": "Story"})
        self.assertEqual(fields["summary"], "Gateway Controller")
        self.assertEqual(
            fields["customfield_10010"],
            {"value": "Planned - Product & Engineering"},
        )
        self.assertEqual(fields["customfield_10011"], {"value": "IoT Workflows"})
        self.assertEqual(
            plain_text_from_adf(fields["description"]),
            "Tabs:\nPart Studio\nAssembly",
        )
        self.assertEqual(
            request["body"]["properties"],
            [{"key": "onshape", "value": {"documentId": "doc-1"}}],
        )

    def test_update_issue_does_not_send_project_or_issue_type(self):
        http = RecordingHttpClient()
        config = JiraConfig(
            base_url="https://example.atlassian.net",
            email="robot@example.com",
            api_token="secret",
            project_key="IOT",
            investments_category_field_id="customfield_10010",
        )
        client = JiraClient(config, http_client=http)

        client.update_issue(
            "IOT-123",
            summary="Renamed",
            description_lines=["Tabs:", "Sketches"],
        )

        fields = http.requests[0]["body"]["fields"]
        self.assertNotIn("project", fields)
        self.assertNotIn("issuetype", fields)
        self.assertEqual(fields["summary"], "Renamed")


if __name__ == "__main__":
    unittest.main()
