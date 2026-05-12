"""Onshape API client and response normalizers."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from email.utils import formatdate
from typing import Any
from urllib.parse import urlparse

from .http import JsonHttpClient


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
        document = self.get_document(document_id)
        resolved_workspace_id = workspace_id or _document_workspace_id(document)
        workspaces = self.list_workspaces(document_id)
        if not resolved_workspace_id and workspaces:
            resolved_workspace_id = _item_id(workspaces[0])

        tabs = (
            _names(self.list_elements(document_id, resolved_workspace_id))
            if resolved_workspace_id
            else []
        )
        return OnshapeDocumentSnapshot(
            document_id=document_id,
            name=_document_name(document),
            workspace_id=resolved_workspace_id,
            tabs=tabs,
            versions=_names(self.list_versions(document_id)),
            branches=_names(workspaces),
        )

    def get_document(self, document_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/documents/{document_id}")

    def list_elements(self, document_id: str, workspace_id: str) -> list[dict[str, Any]]:
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
        return self.http_client.request_json(method, url, headers=headers, body=body)

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
