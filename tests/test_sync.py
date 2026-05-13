import hashlib
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from onshape_jira.onshape import OnshapeDocumentSnapshot
from onshape_jira.state import DocumentRecord, StateStore
from onshape_jira.sync import (
    OnshapeJiraSync,
    issue_description_lines,
    issue_summary,
    snapshot_fingerprint,
)


class FakeOnshapeClient:
    def __init__(self, snapshots):
        self.snapshots = list(snapshots)
        self.calls = []
        self.lock = threading.Lock()

    def document_snapshot(self, document_id, workspace_id=None):
        with self.lock:
            self.calls.append(
                {"document_id": document_id, "workspace_id": workspace_id}
            )
            return self.snapshots.pop(0)


class BarrierOnshapeClient(FakeOnshapeClient):
    def __init__(self, snapshots, parties):
        super().__init__(snapshots)
        self.barrier = threading.Barrier(parties)

    def document_snapshot(self, document_id, workspace_id=None):
        with self.lock:
            self.calls.append(
                {"document_id": document_id, "workspace_id": workspace_id}
            )
        self.barrier.wait(timeout=5)
        with self.lock:
            return self.snapshots.pop(0)


class FakeJiraClient:
    def __init__(self, *, create_delay=0):
        self.created = []
        self.updated = []
        self.create_delay = create_delay
        self.lock = threading.Lock()

    def create_story(self, *, summary, description_lines, document_id):
        if self.create_delay:
            time.sleep(self.create_delay)
        with self.lock:
            self.created.append(
                {
                    "summary": summary,
                    "description_lines": description_lines,
                    "document_id": document_id,
                }
            )
        return "IOT-100"

    def update_issue(self, issue_key, *, summary, description_lines):
        with self.lock:
            self.updated.append(
                {
                    "issue_key": issue_key,
                    "summary": summary,
                    "description_lines": description_lines,
                }
            )


class SyncTest(unittest.TestCase):
    def test_issue_summary_prefixes_optional_folder_path(self):
        base = dict(
            document_id="doc-1",
            name="Sentry",
            workspace_id="wid",
            tabs=[],
            versions=[],
            branches=[],
        )
        bare = OnshapeDocumentSnapshot(**base)
        nested = OnshapeDocumentSnapshot(folder_path="//Foxglove/WIP/", **base)

        self.assertEqual(issue_summary(bare), "Sentry")
        self.assertEqual(issue_summary(nested), "Foxglove/WIP/Sentry")

    def test_issue_summary_strips_company_breadcrumb_only_when_leading(self):
        base = dict(
            document_id="doc-1",
            name="Sentry",
            workspace_id="wid",
            tabs=[],
            versions=[],
            branches=[],
        )

        corp = OnshapeDocumentSnapshot(
            folder_path="Cambridge Mobile Telematics/Foxglove", **base
        )
        self.assertEqual(issue_summary(corp), "Foxglove/Sentry")

        corp_upper = OnshapeDocumentSnapshot(
            folder_path="CAMBRIDGE  MOBILE TELEMATICS/Foxglove", **base
        )
        self.assertEqual(issue_summary(corp_upper), "Foxglove/Sentry")

        inner_only = OnshapeDocumentSnapshot(folder_path="Foxglove/Product", **base)
        self.assertEqual(issue_summary(inner_only), "Foxglove/Product/Sentry")

    def test_jira_refresh_when_stored_summary_differs_despite_same_fingerprint(self):
        """For example summary rules strip a company prefix without changing the folder tree."""

        snap = OnshapeDocumentSnapshot(
            document_id="doc-1",
            name="Sentry",
            workspace_id="wid",
            tabs=["T"],
            versions=[],
            branches=["Main"],
            folder_path="Cambridge Mobile Telematics/Foxglove",
        )
        fp = snapshot_fingerprint(snap)
        onshape = FakeOnshapeClient([snap])
        jira = FakeJiraClient()

        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(Path(directory) / "state.json")
            store.upsert(
                "doc-1",
                DocumentRecord(
                    issue_key="IOT-99",
                    document_name="Sentry",
                    last_issue_summary="Cambridge Mobile Telematics/Foxglove/Sentry",
                    snapshot_fingerprint=fp,
                ),
            )
            sync = OnshapeJiraSync(onshape, jira, store)
            result = sync.sync_document("doc-1")

        self.assertEqual(result.status, "updated")
        self.assertEqual(len(jira.updated), 1)
        self.assertEqual(jira.updated[0]["summary"], "Foxglove/Sentry")

    def test_snapshot_fingerprint_depends_on_folder_path(self):
        common = dict(
            document_id="doc-1",
            name="Sentry",
            workspace_id="wid-1",
            tabs=["Asm"],
            versions=["v1"],
            branches=["Main"],
        )
        sans = OnshapeDocumentSnapshot(**common)
        with_folder = OnshapeDocumentSnapshot(folder_path="Foxglove", **common)
        self.assertNotEqual(
            snapshot_fingerprint(sans), snapshot_fingerprint(with_folder)
        )

    def test_legacy_preflight_state_renamed_when_folder_introduced(self):
        legacy_normalized = json.dumps(
            {
                "branches": ["Main"],
                "name": "Gateway",
                "tabs": ["Studio"],
                "versions": [],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        legacy_fp = hashlib.sha256(legacy_normalized.encode("utf-8")).hexdigest()

        snapshot = OnshapeDocumentSnapshot(
            document_id="doc-1",
            name="Gateway",
            workspace_id="wid-1",
            tabs=["Studio"],
            versions=[],
            branches=["Main"],
            folder_path="Foxglove",
        )
        onshape = FakeOnshapeClient([snapshot])
        jira = FakeJiraClient()

        with tempfile.TemporaryDirectory() as directory:
            store_path = Path(directory) / "state.json"
            store = StateStore(store_path)
            store.upsert(
                "doc-1",
                DocumentRecord(
                    issue_key="IOT-100",
                    document_name="Gateway",
                    snapshot_fingerprint=legacy_fp,
                ),
            )

            sync = OnshapeJiraSync(onshape, jira, store)
            result = sync.sync_document("doc-1")

        self.assertEqual(result.status, "updated")
        self.assertEqual(len(jira.updated), 1)
        self.assertEqual(jira.updated[0]["summary"], "Foxglove/Gateway")
        self.assertIn(
            "Gateway -> Foxglove/Gateway",
            "\n".join(jira.updated[0]["description_lines"]),
        )

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
        self.assertIn("Gateway -> Gateway Rev B", jira.updated[0]["description_lines"])

    def test_concurrent_same_document_events_create_single_story(self):
        snapshots = [
            OnshapeDocumentSnapshot(
                document_id="doc-1",
                name="Gateway",
                workspace_id="wid-1",
                tabs=["Part Studio"],
                versions=[],
                branches=["Main"],
            ),
            OnshapeDocumentSnapshot(
                document_id="doc-1",
                name="Gateway",
                workspace_id="wid-1",
                tabs=["Part Studio"],
                versions=[],
                branches=["Main"],
            ),
        ]
        onshape = BarrierOnshapeClient(snapshots, parties=2)
        jira = FakeJiraClient(create_delay=0.05)
        results = []
        errors = []

        with tempfile.TemporaryDirectory() as directory:
            sync = OnshapeJiraSync(
                onshape, jira, StateStore(Path(directory) / "state.json")
            )

            def handle_created_webhook():
                try:
                    results.append(
                        sync.handle_webhook(
                            {
                                "event": "onshape.document.lifecycle.created",
                                "documentId": "doc-1",
                                "workspaceId": "wid-1",
                            }
                        )
                    )
                except Exception as exc:
                    errors.append(exc)

            threads = [
                threading.Thread(target=handle_created_webhook),
                threading.Thread(target=handle_created_webhook),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

        if errors:
            raise errors[0]
        self.assertEqual(len(jira.created), 1)
        self.assertEqual(len(jira.updated), 0)
        self.assertCountEqual(
            [result.status for result in results], ["created", "unchanged"]
        )

    def test_ping_events_are_ignored(self):
        sync = OnshapeJiraSync(
            FakeOnshapeClient([]), FakeJiraClient(), StateStore(Path("unused"))
        )

        result = sync.handle_webhook({"event": "webhook.ping"})

        self.assertEqual(result.status, "ignored")

    def test_duplicate_webhooks_skip_jira_updates_when_snapshot_unchanged(self):
        snapshot = OnshapeDocumentSnapshot(
            document_id="doc-1",
            name="Gateway",
            workspace_id="wid-1",
            tabs=["Part Studio"],
            versions=[],
            branches=["Main"],
        )
        onshape = FakeOnshapeClient([snapshot, snapshot])
        jira = FakeJiraClient()

        with tempfile.TemporaryDirectory() as directory:
            sync = OnshapeJiraSync(
                onshape, jira, StateStore(Path(directory) / "state.json")
            )

            payload = {
                "event": "onshape.model.lifecycle.changed",
                "documentId": "doc-1",
                "workspaceId": "wid-1",
            }
            first = sync.handle_webhook(payload)
            second = sync.handle_webhook(payload)

        self.assertEqual(first.status, "created")
        self.assertEqual(second.status, "unchanged")
        self.assertEqual(len(jira.updated), 0)

    def test_poll_continues_after_one_document_raises(self):
        snapshot = OnshapeDocumentSnapshot(
            document_id="ignored",
            name="Doc",
            workspace_id="w",
            tabs=["T"],
            versions=[],
            branches=["Main"],
        )
        onshape = FakeOnshapeClient([snapshot, snapshot])
        onshape.list_company_document_ids = lambda cid, page_limit=20: [  # type: ignore[method-assign]
            "alpha",
            "bravo",
        ]
        jira = FakeJiraClient()

        with tempfile.TemporaryDirectory() as directory:
            sync = OnshapeJiraSync(
                onshape, jira, StateStore(Path(directory) / "state.json")
            )
            attempts = {"n": 0}
            real_sync = sync.sync_document

            def flaky(document_id: str, *, workspace_id=None):
                attempts["n"] += 1
                if attempts["n"] == 1:
                    raise TimeoutError("[Errno 60] simulated network hang")
                return real_sync(document_id, workspace_id=workspace_id)

            sync.sync_document = flaky  # type: ignore[method-assign]
            counts = sync.poll_company_documents("company-1")

        self.assertEqual(counts.get("error"), 1)
        self.assertEqual(counts.get("created"), 1)
        self.assertEqual(attempts["n"], 2)

    def test_snapshot_fingerprint_is_stable_across_constructors(self):
        snap = OnshapeDocumentSnapshot(
            document_id="x",
            name="Gateway",
            workspace_id="wid-1",
            tabs=["Assembly"],
            versions=["V1"],
            branches=["Branch A"],
        )
        dup = OnshapeDocumentSnapshot(
            document_id="y",
            name="Gateway",
            workspace_id="wid-999",
            tabs=["Assembly"],
            versions=["V1"],
            branches=["Branch A"],
        )
        self.assertEqual(snapshot_fingerprint(snap), snapshot_fingerprint(dup))


if __name__ == "__main__":
    unittest.main()
