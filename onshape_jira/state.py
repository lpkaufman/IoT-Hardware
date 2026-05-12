"""File-backed mapping between Onshape documents and Jira issues."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class DocumentRecord:
    issue_key: str
    document_name: str = ""
    name_changes: list[str] = field(default_factory=list)


class StateStore:
    """Persist idempotency state for webhook processing."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def get(self, document_id: str) -> DocumentRecord | None:
        raw_record = self._load().get(document_id)
        if not isinstance(raw_record, dict):
            return None
        issue_key = raw_record.get("issue_key")
        if not isinstance(issue_key, str) or not issue_key:
            return None
        name_changes = raw_record.get("name_changes", [])
        if not isinstance(name_changes, list):
            name_changes = []
        return DocumentRecord(
            issue_key=issue_key,
            document_name=str(raw_record.get("document_name", "")),
            name_changes=[str(change) for change in name_changes],
        )

    def upsert(self, document_id: str, record: DocumentRecord) -> None:
        state = self._load()
        state[document_id] = {
            "issue_key": record.issue_key,
            "document_name": record.document_name,
            "name_changes": record.name_changes,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary_path.write_text(json.dumps(state, indent=2, sort_keys=True), "utf-8")
        temporary_path.replace(self.path)

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text("utf-8"))
