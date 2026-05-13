"""Small JSON HTTP client used by the integration clients."""

from __future__ import annotations

import base64
import json
import logging
import os
import ssl
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

try:
    import certifi
except ImportError:
    certifi = None  # type: ignore[assignment, misc]


_LOG = logging.getLogger(__name__)


class _HttpsSkipVerifyState:
    warned = False


class _MissingCertifiState:
    warned = False


def _https_ssl_context(url: str) -> ssl.SSLContext | None:
    """TLS context for HTTPS. Returns None only for non-HTTPS URLs."""

    if not url.lower().startswith("https://"):
        return None

    raw = os.environ.get("HTTPS_SKIP_VERIFY", "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        if not _HttpsSkipVerifyState.warned:
            _HttpsSkipVerifyState.warned = True
            _LOG.warning(
                "HTTPS_SKIP_VERIFY is set: outbound TLS verification disabled (unsafe)."
            )
        return ssl._create_unverified_context()

    if certifi is not None:
        return ssl.create_default_context(cafile=certifi.where())

    if not _MissingCertifiState.warned:
        _MissingCertifiState.warned = True
        _LOG.warning(
            "Package certifi not installed — TLS verification uses Python's default CA store; "
            "install dependencies (pip install -e '.') so macOS/python.org setups work reliably."
        )
    return ssl.create_default_context()


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

    def __init__(self, *, timeout_seconds: float = 60.0) -> None:
        self.timeout_seconds = timeout_seconds

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
            context = _https_ssl_context(url)
            opener_kwargs: dict[str, Any] = {"timeout": self.timeout_seconds}
            if context is not None:
                opener_kwargs["context"] = context
            with urlopen(request, **opener_kwargs) as response:
                response_body = response.read().decode("utf-8")
                if not response_body:
                    return None
                return json.loads(response_body)
        except HTTPError as exc:
            body_text = exc.read().decode("utf-8", errors="replace")
            raise HttpClientError(method, url, exc.code, body_text) from exc
        except URLError as exc:
            reason = exc.reason
            detail = str(reason) if reason is not None else str(exc)
            raise HttpClientError(method, url, 0, detail) from exc
