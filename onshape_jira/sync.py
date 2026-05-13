"""Orchestrates Onshape document events into Jira stories."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from threading import Lock
from typing import Any

from .jira import JiraClient
from .onshape import (
    DOCUMENT_LIST_SEARCH_MAX_LIMIT,
    OnshapeClient,
    OnshapeDocumentSnapshot,
)
from .state import DocumentRecord, StateStore


_LOGGER = logging.getLogger(__name__)


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
        self._locks_guard = Lock()
        self._document_locks: dict[str, Lock] = {}

    def handle_webhook(self, payload: dict[str, Any]) -> SyncResult:
        event = str(payload.get("event", ""))
        if event in IGNORED_EVENTS:
            _LOGGER.debug(
                "webhook ignored: event=%s documentId=%s",
                event,
                payload.get("documentId", ""),
            )
            return SyncResult(status="ignored")

        document_id = str(payload.get("documentId", "")).strip()
        if not document_id:
            _LOGGER.warning("webhook missing documentId event=%s", event)
            return SyncResult(status="ignored")

        workspace_id = str(payload.get("workspaceId", "")).strip() or None
        _LOGGER.debug("webhook raw payload: %s", payload)
        _LOGGER.info(
            "webhook: event=%s document_id=%s workspace_id=%s",
            event,
            document_id,
            workspace_id or "(default)",
        )
        result = self.sync_document(document_id, workspace_id=workspace_id)
        _LOGGER.info(
            "webhook handled: status=%s document_id=%s issue_key=%s",
            result.status,
            document_id,
            result.issue_key or "",
        )
        return result

    def poll_company_documents(
        self, company_id: str, *, page_limit: int = DOCUMENT_LIST_SEARCH_MAX_LIMIT
    ) -> dict[str, int]:
        """Fetch every company-owned document from Onshape and sync each into Jira."""

        _LOGGER.info(
            "poll: fetching company-owned document IDs company_id=%s page_limit=%s",
            company_id,
            page_limit,
        )
        document_ids = self.onshape.list_company_document_ids(
            company_id, page_limit=page_limit
        )
        _LOGGER.info(
            "poll: found %d unique documents to sync order=modified-desc",
            len(document_ids),
        )
        counts: dict[str, int] = {}
        for index, document_id in enumerate(document_ids, start=1):
            try:
                result = self.sync_document(document_id)
            except Exception:
                _LOGGER.exception(
                    "poll: sync_document failed document_id=%s (%d/%d)",
                    document_id,
                    index,
                    len(document_ids),
                )
                result = SyncResult(status="error", document_id=document_id)
            counts[result.status] = counts.get(result.status, 0) + 1
            _LOGGER.info(
                "poll [%d/%d] document_id=%s -> %s issue_key=%s",
                index,
                len(document_ids),
                document_id,
                result.status,
                result.issue_key or "",
            )
        _LOGGER.info(
            "poll: finished summary counts=%s",
            ", ".join(f"{status}={count}" for status, count in sorted(counts.items())),
        )
        return counts

    def sync_document(
        self, document_id: str, *, workspace_id: str | None = None
    ) -> SyncResult:
        snapshot = self.onshape.document_snapshot(document_id, workspace_id)
        fingerprint = snapshot_fingerprint(snapshot)
        summary = issue_summary(snapshot)
        _LOGGER.debug(
            "sync_document snapshot document_id=%s summary=%s name=%s folder_path=%s "
            "workspace_id=%s fingerprint_prefix=%s tabs=%d versions=%d branches=%d",
            document_id,
            summary,
            snapshot.name,
            snapshot.folder_path or "(none)",
            snapshot.workspace_id or "(none)",
            fingerprint[:12],
            len(snapshot.tabs),
            len(snapshot.versions),
            len(snapshot.branches),
        )
        with self._lock_for_document(document_id):
            record = self.state_store.get(document_id)
            if record is None:
                _LOGGER.info(
                    "creating Jira story for Onshape doc document_id=%s summary=%s",
                    document_id,
                    summary,
                )
                description_lines = issue_description_lines(snapshot, [])
                issue_key = self.jira.create_story(
                    summary=summary,
                    description_lines=description_lines,
                    document_id=document_id,
                )
                self.state_store.upsert(
                    document_id,
                    DocumentRecord(
                        issue_key=issue_key,
                        document_name=snapshot.name,
                        last_issue_summary=summary,
                        snapshot_fingerprint=fingerprint,
                    ),
                )
                _LOGGER.info(
                    "created Jira issue document_id=%s issue_key=%s",
                    document_id,
                    issue_key,
                )
                return SyncResult(
                    status="created", document_id=document_id, issue_key=issue_key
                )

            if record.snapshot_fingerprint == fingerprint:
                previous_summary = (record.last_issue_summary or "").strip()
                if previous_summary == summary:
                    _LOGGER.debug(
                        "unchanged skipping Jira update document_id=%s issue_key=%s",
                        document_id,
                        record.issue_key,
                    )
                    return SyncResult(
                        status="unchanged",
                        document_id=document_id,
                        issue_key=record.issue_key,
                    )
                _LOGGER.info(
                    "Jira summary out of date vs stored (format or manual edit) "
                    "document_id=%s issue_key=%s refreshing",
                    document_id,
                    record.issue_key,
                )

            updated_record = _record_with_summary_change(record, snapshot)
            description_lines = issue_description_lines(
                snapshot, updated_record.name_changes
            )
            _LOGGER.info(
                "updating Jira issue issue_key=%s document_id=%s summary=%s",
                record.issue_key,
                document_id,
                summary,
            )
            self.jira.update_issue(
                record.issue_key,
                summary=summary,
                description_lines=description_lines,
            )
            self.state_store.upsert(
                document_id,
                DocumentRecord(
                    issue_key=record.issue_key,
                    document_name=updated_record.document_name,
                    name_changes=updated_record.name_changes,
                    last_issue_summary=updated_record.last_issue_summary,
                    snapshot_fingerprint=fingerprint,
                ),
            )
            _LOGGER.info(
                "updated Jira issue issue_key=%s document_id=%s",
                record.issue_key,
                document_id,
            )
            _LOGGER.debug(
                "persisted fingerprint_prefix=%s for document_id=%s",
                fingerprint[:12],
                document_id,
            )
            return SyncResult(
                status="updated", document_id=document_id, issue_key=record.issue_key
            )

    def _lock_for_document(self, document_id: str) -> Lock:
        with self._locks_guard:
            lock = self._document_locks.get(document_id)
            if lock is None:
                lock = Lock()
                self._document_locks[document_id] = lock
            return lock


_REDUNDANT_JIRA_SUMMARY_FOLDER_PREFIX_LOWER = frozenset(
    {
        "cambridge mobile telematics",
    }
)


def _collapse_folder_label(fragment: str) -> str:
    return " ".join(fragment.split()).lower().strip()


def _drop_redundant_issue_path_segments(segments: list[str]) -> list[str]:
    """Strip leading breadcrumbs that only repeat the company name on every document."""

    out = list(segments)
    while out:
        collapsed = _collapse_folder_label(out[0])
        if collapsed not in _REDUNDANT_JIRA_SUMMARY_FOLDER_PREFIX_LOWER:
            break
        out.pop(0)
    return out


def issue_summary(snapshot: OnshapeDocumentSnapshot) -> str:
    """Jira summary: ``Ancestor/LeafFolder/DocumentTitle`` plus document title."""

    title = snapshot.name.strip() or "Untitled Onshape Document"
    folders = snapshot.folder_path.strip().strip("/").replace("\\", "/")
    if not folders:
        return title

    crumbs = [segment.strip() for segment in folders.split("/") if segment.strip()]
    crumbs = _drop_redundant_issue_path_segments(crumbs)
    prefix = "/".join(crumbs)
    return f"{prefix}/{title}" if prefix else title


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


def _record_with_summary_change(
    record: DocumentRecord, snapshot: OnshapeDocumentSnapshot
) -> DocumentRecord:
    new_plain_name = snapshot.name
    new_summary = issue_summary(snapshot)
    name_changes = list(record.name_changes)

    prev = (record.last_issue_summary or "").strip()
    if not prev:
        prev = (record.document_name or "").strip()

    if prev and prev != new_summary:
        name_changes.append(f"{prev} -> {new_summary}")

    return DocumentRecord(
        issue_key=record.issue_key,
        document_name=new_plain_name,
        name_changes=name_changes,
        last_issue_summary=new_summary,
    )


def snapshot_fingerprint(snapshot: OnshapeDocumentSnapshot) -> str:
    """Stable hash of synced fields so redundant polls skip Jira updates."""

    normalized = json.dumps(
        {
            "branches": list(snapshot.branches),
            "folder_path": snapshot.folder_path.strip(),
            "name": snapshot.name,
            "tabs": list(snapshot.tabs),
            "versions": list(snapshot.versions),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
