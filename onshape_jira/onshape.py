"""Onshape API client and response normalizers."""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets
import time
from dataclasses import dataclass
from email.utils import formatdate
from typing import Any
from urllib.parse import urlencode, urlparse

from .http import JsonHttpClient


_LOGGER = logging.getLogger(__name__)


def _truncate_for_log(text: str, max_chars: int = 260) -> str:
    stripped = text.replace("\n", " ").strip()
    if len(stripped) <= max_chars:
        return stripped
    return stripped[: max_chars - 3] + "..."


# Matches Onshape Documents search: company-owned docs for a given owner (company ID).
DOCUMENT_SEARCH_COMPANY_OWNED_FILTER = 7
DOCUMENT_OWNER_TYPE_COMPANY = 1
# Onshape GET /api/documents rejects limit > 20 (BTRestDocument.getDocuments).
DOCUMENT_LIST_SEARCH_MAX_LIMIT = 20


DEFAULT_WEBHOOK_EVENTS = (
    "onshape.document.lifecycle.created",
    "onshape.model.lifecycle.createversion",
    "onshape.model.lifecycle.createworkspace",
    "onshape.model.lifecycle.createelement",
    "onshape.model.lifecycle.deleteelement",
    "onshape.model.lifecycle.metadata",
    "onshape.model.lifecycle.changed",
)


@dataclass(frozen=True)
class OnshapeDocumentSnapshot:
    document_id: str
    name: str
    workspace_id: str
    tabs: list[str]
    versions: list[str]
    branches: list[str]
    folder_path: str = ""


class OnshapeClient:
    """Client for the Onshape endpoints needed by the Jira sync."""

    def __init__(
        self,
        base_url: str,
        access_key: str,
        secret_key: str,
        *,
        http_client: JsonHttpClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.access_key = access_key
        self.secret_key = secret_key
        self.http_client = http_client or JsonHttpClient()

    def document_snapshot(
        self, document_id: str, workspace_id: str | None = None
    ) -> OnshapeDocumentSnapshot:
        _LOGGER.debug(
            "document_snapshot fetching document_id=%s workspace_hint=%s",
            document_id,
            workspace_id or "(default)",
        )
        document = self.get_document(document_id)
        folder_path = self.folder_path_display(document)
        resolved_workspace_id = workspace_id or _document_workspace_id(document)
        workspaces = self.list_workspaces(document_id)
        if not resolved_workspace_id and workspaces:
            resolved_workspace_id = _item_id(workspaces[0])

        tabs = (
            _names(self.list_elements(document_id, resolved_workspace_id))
            if resolved_workspace_id
            else []
        )
        snapshot = OnshapeDocumentSnapshot(
            document_id=document_id,
            name=_document_name(document),
            workspace_id=resolved_workspace_id,
            tabs=tabs,
            versions=_names(self.list_versions(document_id)),
            branches=_names(workspaces),
            folder_path=folder_path,
        )
        _LOGGER.debug(
            "document_snapshot ready document_id=%s name=%s folder_path=%s workspace=%s "
            "tabs=%d versions=%d branches=%d",
            document_id,
            snapshot.name,
            snapshot.folder_path or "(none)",
            snapshot.workspace_id or "(none)",
            len(snapshot.tabs),
            len(snapshot.versions),
            len(snapshot.branches),
        )
        return snapshot

    def folder_path_display(self, document: dict[str, Any]) -> str:
        parent_id = _document_parent_folder_id(document)
        if not parent_id:
            return ""
        return self._global_tree_folder_chain(parent_id)

    def _global_tree_folder_chain(self, folder_id: str) -> str:
        query = urlencode({"getPathToRoot": "true"})
        try:
            enriched: Any = self._request(
                "GET",
                f"/api/globaltreenodes/folder/{folder_id}?{query}",
            )
        except Exception:
            _LOGGER.debug(
                "Onshape globaltreenodes folder getPathToRoot failed folder_id=%s",
                folder_id,
                exc_info=True,
            )
            enriched = {}
        segments = _global_treenodes_folder_path_segments(enriched)
        joined = _join_folder_path_segments(segments)
        if joined:
            return joined
        try:
            minimal: Any = self._request(
                "GET", f"/api/globaltreenodes/folder/{folder_id}"
            )
        except Exception:
            _LOGGER.debug(
                "Onshape globaltreenodes folder lookup failed folder_id=%s",
                folder_id,
                exc_info=True,
            )
            return ""
        return _join_folder_path_segments(
            _single_global_treenodes_folder_label_candidates(minimal)
        )

    def get_document(self, document_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/documents/{document_id}")

    def list_elements(
        self, document_id: str, workspace_id: str
    ) -> list[dict[str, Any]]:
        response = self._request(
            "GET", f"/api/documents/d/{document_id}/w/{workspace_id}/elements"
        )
        return _items(response)

    def list_versions(self, document_id: str) -> list[dict[str, Any]]:
        response = self._request("GET", f"/api/documents/d/{document_id}/versions")
        return _items(response)

    def list_workspaces(self, document_id: str) -> list[dict[str, Any]]:
        response = self._request("GET", f"/api/documents/d/{document_id}/workspaces")
        return _items(response)

    def list_company_document_ids(
        self,
        company_id: str,
        *,
        page_limit: int = DOCUMENT_LIST_SEARCH_MAX_LIMIT,
    ) -> list[str]:
        """Return unique document IDs for all documents owned by the company."""

        if page_limit < 1:
            raise ValueError("page_limit must be at least 1")
        if page_limit > DOCUMENT_LIST_SEARCH_MAX_LIMIT:
            _LOGGER.warning(
                "page_limit=%s exceeds Onshape getDocuments maximum (%s); capping",
                page_limit,
                DOCUMENT_LIST_SEARCH_MAX_LIMIT,
            )
            page_limit = DOCUMENT_LIST_SEARCH_MAX_LIMIT

        ids: list[str] = []
        seen: set[str] = set()
        offset = 0
        while True:
            query = urlencode(
                {
                    # Empty query returns all docs matching filters (same as Documents page search UI).
                    "q": "",
                    "filter": DOCUMENT_SEARCH_COMPANY_OWNED_FILTER,
                    "owner": company_id,
                    "ownerType": DOCUMENT_OWNER_TYPE_COMPANY,
                    "sortColumn": "modifiedAt",
                    "sortOrder": "desc",
                    "offset": offset,
                    "limit": page_limit,
                }
            )
            response = self._request("GET", f"/api/documents?{query}")
            items = _items(response)
            if not items:
                _LOGGER.debug(
                    "documents search finished: empty page at offset=%s", offset
                )
                break
            page_new = 0
            for item in items:
                doc_id = _document_list_item_id(item)
                if doc_id and doc_id not in seen:
                    seen.add(doc_id)
                    ids.append(doc_id)
                    page_new += 1
            _LOGGER.info(
                "Onshape documents search offset=%s limit=%s: %s results "
                "(new doc ids=%s total unique=%s)",
                offset,
                page_limit,
                len(items),
                page_new,
                len(ids),
            )
            _LOGGER.debug(
                "Onshape documents search page sample_ids=%s",
                [_document_list_item_id(i) for i in items[:10]],
            )
            if len(items) < page_limit:
                break
            offset += page_limit
        _LOGGER.info(
            "listed %d unique company-owned document IDs (company_id=%s)",
            len(ids),
            company_id,
        )
        return ids

    def create_company_webhook(
        self,
        *,
        company_id: str,
        url: str,
        events: tuple[str, ...] = DEFAULT_WEBHOOK_EVENTS,
        collapse_events: bool = False,
    ) -> dict[str, Any]:
        body = {
            "companyId": company_id,
            "events": list(events),
            "options": {"collapseEvents": collapse_events},
            "url": url,
            "isTransient": False,
        }
        return self._request("POST", "/api/v6/webhooks", body=body)

    def _request(
        self, method: str, path: str, *, body: dict[str, Any] | None = None
    ) -> Any:
        url = self.base_url + path
        api_path = _truncate_for_log(path)
        content_type = "application/json"
        auth_date = formatdate(timeval=None, localtime=False, usegmt=True)
        nonce = secrets.token_hex(16)
        headers = {
            "Authorization": self._authorization_header(
                method, url, nonce, auth_date, content_type
            ),
            "Date": auth_date,
            "On-Nonce": nonce,
            "Content-Type": content_type,
        }
        started = time.perf_counter()

        try:
            response = self.http_client.request_json(
                method, url, headers=headers, body=body
            )
        except Exception:
            elapsed_ms = (time.perf_counter() - started) * 1000
            _LOGGER.exception(
                "Onshape API request failed method=%s path=%s elapsed_ms=%.1f",
                method,
                api_path,
                elapsed_ms,
            )
            raise

        elapsed_ms = (time.perf_counter() - started) * 1000
        _LOGGER.debug(
            "Onshape API %s path=%s elapsed_ms=%.1f",
            method,
            api_path,
            elapsed_ms,
        )
        return response

    def _authorization_header(
        self, method: str, url: str, nonce: str, auth_date: str, content_type: str
    ) -> str:
        parsed = urlparse(url)
        signature_input = (
            f"{method}\n{nonce}\n{auth_date}\n{content_type}\n"
            f"{parsed.path}\n{parsed.query or ''}\n"
        ).lower()
        digest = hmac.new(
            self.secret_key.encode("utf-8"),
            signature_input.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        signature = base64.b64encode(digest).decode("ascii")
        return f"On {self.access_key}:HmacSHA256:{signature}"


def webhook_registration_payload(company_id: str, url: str) -> dict[str, Any]:
    """Return the webhook body for docs or runbook-driven registration."""

    return {
        "companyId": company_id,
        "events": list(DEFAULT_WEBHOOK_EVENTS),
        "options": {"collapseEvents": False},
        "url": url,
        "isTransient": False,
    }


def _document_list_item_id(item: dict[str, Any]) -> str:
    for key in ("id", "documentId"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    document = item.get("document")
    if isinstance(document, dict):
        nested = _document_list_item_id(document)
        if nested:
            return nested
    return ""


def _items(response: Any) -> list[dict[str, Any]]:
    if isinstance(response, list):
        return [item for item in response if isinstance(item, dict)]
    if isinstance(response, dict):
        for key in ("items", "documents", "versions", "workspaces", "elements"):
            value = response.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def _names(items: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for item in items:
        name = item.get("name") or item.get("title")
        if isinstance(name, str) and name.strip():
            names.append(name.strip())
    return names


def _document_name(document: dict[str, Any]) -> str:
    name = document.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    document_info = document.get("document")
    if isinstance(document_info, dict):
        nested_name = document_info.get("name")
        if isinstance(nested_name, str) and nested_name.strip():
            return nested_name.strip()
    return "Untitled Onshape Document"


def _document_workspace_id(document: dict[str, Any]) -> str:
    for key in ("defaultWorkspaceId", "workspaceId"):
        value = document.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    default_workspace = document.get("defaultWorkspace")
    if isinstance(default_workspace, dict):
        value = _item_id(default_workspace)
        if value:
            return value
    return ""


def _item_id(item: dict[str, Any]) -> str:
    for key in ("id", "workspaceId", "versionId"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


_SKIP_ONSHAPE_TREE_ROOT_LABELS_LOWER = frozenset({"my onshape", "enterprise"})


def _document_parent_folder_id(document: dict[str, Any]) -> str:
    for key in ("parentId", "parentFolderId", "folderId"):
        value = document.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    nested = document.get("document")
    if isinstance(nested, dict):
        inherited = _document_parent_folder_id(nested)
        if inherited:
            return inherited

    location = document.get("location")
    if isinstance(location, dict):
        for key in ("parentId", "parentFolderId", "folderId"):
            nested_value = location.get(key)
            if isinstance(nested_value, str) and nested_value.strip():
                return nested_value.strip()

    home = document.get("homeBookmarkInfo")
    if isinstance(home, dict):
        for key in ("parentId", "parentFolderId", "folderId"):
            bookmark_value = home.get(key)
            if isinstance(bookmark_value, str) and bookmark_value.strip():
                return bookmark_value.strip()

    return ""


def _filter_tree_path_labels(labels: list[str]) -> list[str]:
    out: list[str] = []
    for label in labels:
        text = label.strip().strip("/").replace("\\", "/")
        if not text:
            continue
        if text.lower() in _SKIP_ONSHAPE_TREE_ROOT_LABELS_LOWER:
            continue
        out.append(text)
    return out


def _node_list_to_path_labels(nodes: list[Any]) -> list[str]:
    labels: list[str] = []
    for node in nodes:
        if isinstance(node, str) and node.strip():
            labels.append(node.strip())
            continue
        if not isinstance(node, dict):
            continue
        raw = node.get("name") or node.get("title")
        if isinstance(raw, str) and raw.strip():
            labels.append(raw.strip())
    return labels


def _global_tree_path_carrier(resp: dict[str, Any]) -> dict[str, Any]:
    nested = resp.get("node")
    if isinstance(nested, dict) and any(
        isinstance(nested.get(field), list)
        for field in (
            "pathToRoot",
            "pathFromRoot",
            "path",
            "pathItems",
            "ancestors",
        )
    ):
        return nested
    return resp


def _global_treenodes_folder_path_segments(resp: Any) -> list[str]:
    if not isinstance(resp, dict):
        return []
    carrier = _global_tree_path_carrier(resp)

    path_fields: tuple[tuple[str, bool], ...] = (
        ("pathFromRoot", False),
        ("pathItems", False),
        ("pathToRoot", True),
        ("path", True),
        ("ancestors", False),
    )

    for key, reverse_leaf_to_display in path_fields:
        candidate = carrier.get(key)
        if not isinstance(candidate, list) or not candidate:
            continue
        labeled = _node_list_to_path_labels(candidate)
        filtered = _filter_tree_path_labels(labeled)
        oriented = list(reversed(filtered)) if reverse_leaf_to_display else filtered
        if oriented:
            return oriented
    return []


def _join_folder_path_segments(segments: list[str]) -> str:
    normalized: list[str] = []
    for segment in segments:
        if not isinstance(segment, str):
            continue
        cleaned = segment.replace("\\", "/").strip().strip("/")
        if not cleaned:
            continue
        for fragment in cleaned.split("/"):
            part = fragment.strip()
            if part:
                normalized.append(part)
    return "/".join(normalized)


def _single_global_treenodes_folder_label_candidates(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return []
    node_obj = payload.get("node") if isinstance(payload.get("node"), dict) else None
    scoped: dict[str, Any] = node_obj if node_obj else payload

    raw = scoped.get("name") or scoped.get("title")
    if isinstance(raw, str) and raw.strip():
        stripped = raw.strip()
        filt = _filter_tree_path_labels([stripped])
        return filt if filt else [stripped]
    return []
