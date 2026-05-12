import tempfile
import unittest
from pathlib import Path

from onshape_jira.onshape import OnshapeDocumentSnapshot
from onshape_jira.state import StateStore
from onshape_jira.sync import OnshapeJiraSync, issue_description_lines


class FakeOnshapeClient:
    def __init__(self, snapshots):
        self.snapshots = list(snapshots)
        self.calls = []

    def document_snapshot(self, document_id, workspace_id=None):
        self.calls.append({"document_id": document_id, "workspace_id": workspace_id})
        return self.snapshots.pop(0)


class FakeJiraClient:
    def __init__(self):
        self.created = []
        self.updated = []

    def create_story(self, *, summary, description_lines, document_id):
        self.created.append(
            {
                "summary": summary,
                "description_lines": description_lines,
                "document_id": document_id,
            }
        )
        return "IOT-100"

    def update_issue(self, issue_key, *, summary, description_lines):
        self.updated.append(
            {
                "issue_key": issue_key,
                "summary": summary,
                "description_lines": description_lines,
            }
        )


class SyncTest(unittest.TestCase):
    def test_description_contains_tabs_versions_branches_and_name_changes(self):
        snapshot = OnshapeDocumentSnapshot(
            document_id="doc-1",
            name="Gateway",
            workspace_id="wid-1",
            tabs=["Part Studio", "Assembly"],
            versions=["v1"],
            branches=["Main", "Prototype"],
        )

        lines = issue_description_lines(snapshot, ["Old Gateway -> Gateway"])

        self.assertEqual(
            lines,
            [
                "Tabs:",
                "Part Studio",
                "Assembly",
                "",
                "Versions:",
                "v1",
                "",
                "Branches:",
                "Main",
                "Prototype",
                "",
                "Name changes:",
                "Old Gateway -> Gateway",
            ],
        )

    def test_webhook_create_then_update_is_idempotent_by_document_id(self):
        first_snapshot = OnshapeDocumentSnapshot(
            document_id="doc-1",
            name="Gateway",
            workspace_id="wid-1",
            tabs=["Part Studio"],
            versions=[],
            branches=["Main"],
        )
        second_snapshot = OnshapeDocumentSnapshot(
            document_id="doc-1",
            name="Gateway Rev B",
            workspace_id="wid-1",
            tabs=["Part Studio", "Assembly"],
            versions=["Release 1"],
            branches=["Main", "Prototype"],
        )
        onshape = FakeOnshapeClient([first_snapshot, second_snapshot])
        jira = FakeJiraClient()

        with tempfile.TemporaryDirectory() as directory:
            sync = OnshapeJiraSync(
                onshape, jira, StateStore(Path(directory) / "state.json")
            )

            created = sync.handle_webhook(
                {
                    "event": "onshape.document.lifecycle.created",
                    "documentId": "doc-1",
                    "workspaceId": "wid-1",
                }
            )
            updated = sync.handle_webhook(
                {
                    "event": "onshape.model.lifecycle.createversion",
                    "documentId": "doc-1",
                    "workspaceId": "wid-1",
                }
            )

        self.assertEqual(created.status, "created")
        self.assertEqual(updated.status, "updated")
        self.assertEqual(len(jira.created), 1)
        self.assertEqual(jira.created[0]["summary"], "Gateway")
        self.assertEqual(len(jira.updated), 1)
        self.assertEqual(jira.updated[0]["issue_key"], "IOT-100")
        self.assertEqual(jira.updated[0]["summary"], "Gateway Rev B")
        self.assertIn("Release 1", jira.updated[0]["description_lines"])
        self.assertIn("Prototype", jira.updated[0]["description_lines"])
        self.assertIn(
            "Gateway -> Gateway Rev B", jira.updated[0]["description_lines"]
        )

    def test_ping_events_are_ignored(self):
        sync = OnshapeJiraSync(FakeOnshapeClient([]), FakeJiraClient(), StateStore(Path("unused")))

        result = sync.handle_webhook({"event": "webhook.ping"})

        self.assertEqual(result.status, "ignored")


if __name__ == "__main__":
    unittest.main()
