"""Orchestrates Onshape document events into Jira stories."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .jira import JiraClient
from .onshape import OnshapeClient, OnshapeDocumentSnapshot
from .state import DocumentRecord, StateStore


IGNORED_EVENTS = {
    "webhook.register",
    "webhook.unregister",
    "webhook.ping",
}


@dataclass(frozen=True)
class SyncResult:
    status: str
    document_id: str = ""
    issue_key: str = ""


class OnshapeJiraSync:
    """Synchronize a single Onshape document to a Jira story."""

    def __init__(
        self, onshape: OnshapeClient, jira: JiraClient, state_store: StateStore
    ) -> None:
        self.onshape = onshape
        self.jira = jira
        self.state_store = state_store

    def handle_webhook(self, payload: dict[str, Any]) -> SyncResult:
        event = str(payload.get("event", ""))
        if event in IGNORED_EVENTS:
            return SyncResult(status="ignored")

        document_id = str(payload.get("documentId", "")).strip()
        if not document_id:
            return SyncResult(status="ignored")

        workspace_id = str(payload.get("workspaceId", "")).strip() or None
        return self.sync_document(document_id, workspace_id=workspace_id)

    def sync_document(
        self, document_id: str, *, workspace_id: str | None = None
    ) -> SyncResult:
        snapshot = self.onshape.document_snapshot(document_id, workspace_id)
        record = self.state_store.get(document_id)
        if record is None:
            description_lines = issue_description_lines(snapshot, [])
            issue_key = self.jira.create_story(
                summary=snapshot.name,
                description_lines=description_lines,
                document_id=document_id,
            )
            self.state_store.upsert(
                document_id,
                DocumentRecord(issue_key=issue_key, document_name=snapshot.name),
            )
            return SyncResult(status="created", document_id=document_id, issue_key=issue_key)

        updated_record = _record_with_name_change(record, snapshot.name)
        description_lines = issue_description_lines(snapshot, updated_record.name_changes)
        self.jira.update_issue(
            record.issue_key,
            summary=snapshot.name,
            description_lines=description_lines,
        )
        self.state_store.upsert(document_id, updated_record)
        return SyncResult(
            status="updated", document_id=document_id, issue_key=record.issue_key
        )


def issue_description_lines(
    snapshot: OnshapeDocumentSnapshot, name_changes: list[str]
) -> list[str]:
    """Build the Jira issue description as plain lines before ADF conversion."""

    lines: list[str] = ["Tabs:"]
    lines.extend(snapshot.tabs or ["No tabs found"])
    lines.append("")
    lines.append("Versions:")
    lines.extend(snapshot.versions or ["No versions found"])
    lines.append("")
    lines.append("Branches:")
    lines.extend(snapshot.branches or ["No branches found"])
    if name_changes:
        lines.append("")
        lines.append("Name changes:")
        lines.extend(name_changes)
    return lines


def _record_with_name_change(record: DocumentRecord, new_name: str) -> DocumentRecord:
    name_changes = list(record.name_changes)
    old_name = record.document_name
    if old_name and old_name != new_name:
        name_changes.append(f"{old_name} -> {new_name}")
    return DocumentRecord(
        issue_key=record.issue_key,
        document_name=new_name,
        name_changes=name_changes,
    )
