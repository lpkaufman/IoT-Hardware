"""Small JSON HTTP client used by the integration clients."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.error import HTTPError
from urllib.request import Request, urlopen


class HttpClientError(RuntimeError):
    """Raised when a remote API returns a non-success response."""

    def __init__(self, method: str, url: str, status: int, body: str) -> None:
        super().__init__(f"{method} {url} failed with HTTP {status}: {body}")
        self.method = method
        self.url = url
        self.status = status
        self.body = body


@dataclass(frozen=True)
class BasicAuth:
    username: str
    token: str

    def header_value(self) -> str:
        raw = f"{self.username}:{self.token}".encode("utf-8")
        return "Basic " + base64.b64encode(raw).decode("ascii")


class JsonHttpClient:
    """Thin wrapper around urllib for JSON REST calls."""

    def request_json(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        body: Mapping[str, Any] | None = None,
    ) -> Any:
        data = None
        request_headers = {"Accept": "application/json"}
        if headers:
            request_headers.update(headers)
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")

        request = Request(url, data=data, headers=request_headers, method=method)
        try:
            with urlopen(request, timeout=30) as response:
                response_body = response.read().decode("utf-8")
                if not response_body:
                    return None
                return json.loads(response_body)
        except HTTPError as exc:
            body_text = exc.read().decode("utf-8", errors="replace")
            raise HttpClientError(method, url, exc.code, body_text) from exc
