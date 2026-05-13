"""Environment-backed configuration for the integration service."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .onshape import DOCUMENT_LIST_SEARCH_MAX_LIMIT


DEFAULT_INVESTMENTS_CATEGORY = "Planned \u2013 Product & Engineering"
DEFAULT_WORKFLOW = "Simple 3 state workflow"

_INVESTMENTS_LABEL_ASCII_HYPHEN = "Planned - Product & Engineering"
# Resolved from REST on cmtelematics IOTHW; used only when field id matches and label is DEFAULT.
KNOWN_CMTELEMATICS_IOTHW_INVESTMENTS_CATEGORY_FIELD_ID = "customfield_11822"
KNOWN_CMTELEMATICS_IOTHW_DEFAULT_INVESTMENTS_OPTION_ID = "11740"


@dataclass(frozen=True)
class JiraConfig:
    base_url: str
    email: str
    api_token: str
    project_key: str
    issue_type: str = "Story"
    investments_category_field_id: str = ""
    investments_category_value: str = DEFAULT_INVESTMENTS_CATEGORY
    # If set, sent as {"id": ...} instead of {"value": ...}; use when labels do not match.
    investments_category_option_id: str = ""
    workflow_field_id: str = ""
    workflow_value: str = DEFAULT_WORKFLOW


@dataclass(frozen=True)
class OnshapeConfig:
    base_url: str = "https://cad.onshape.com"
    access_key: str = ""
    secret_key: str = ""
    company_id: str = ""
    webhook_url: str = ""
    webhook_token: str = ""


@dataclass(frozen=True)
class AppConfig:
    jira: JiraConfig
    onshape: OnshapeConfig
    state_path: Path
    host: str = "0.0.0.0"
    port: int = 8080
    poll_interval_seconds: int = 300
    onshape_document_list_page_limit: int = DOCUMENT_LIST_SEARCH_MAX_LIMIT
    log_level: str = "INFO"
    http_timeout_seconds: float = 60.0


def _required(env: Mapping[str, str], name: str) -> str:
    value = env.get(name, "").strip()
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def _optional(env: Mapping[str, str], name: str, default: str = "") -> str:
    return env.get(name, default).strip()


def _optional_cat_value(env: Mapping[str, str]) -> str:
    raw = env.get(
        "JIRA_INVESTMENTS_CATEGORY_VALUE", DEFAULT_INVESTMENTS_CATEGORY
    ).strip()
    return raw if raw else DEFAULT_INVESTMENTS_CATEGORY


def _normalize_investment_category_value(raw: str) -> str:
    """Jira rejects labels that differ by dash style; coerce common hyphen typo to canonical."""

    trimmed = raw.strip()
    collapsed = re.sub(r"[\u2012\u2013\u2014\u2212\-]", "-", trimmed)
    if collapsed.strip() == _INVESTMENTS_LABEL_ASCII_HYPHEN.strip():
        return DEFAULT_INVESTMENTS_CATEGORY
    return trimmed


def _positive_int(env: Mapping[str, str], name: str, default: str) -> int:
    raw = _optional(env, name, default)
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if value < 1:
        raise ValueError(f"{name} must be at least 1")
    return value


def _http_timeout_seconds(env: Mapping[str, str]) -> float:
    raw = _optional(env, "HTTP_TIMEOUT_SECONDS", "60")
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError("HTTP_TIMEOUT_SECONDS must be a positive number") from exc
    if value <= 0:
        raise ValueError("HTTP_TIMEOUT_SECONDS must be positive")
    if value > 600:
        raise ValueError("HTTP_TIMEOUT_SECONDS must be at most 600")
    return value


def load_config(env: Mapping[str, str] | None = None) -> AppConfig:
    """Load configuration from environment variables."""

    if env is None:
        try:
            from dotenv import load_dotenv

            load_dotenv()
        except ImportError:
            pass
    source = os.environ if env is None else env
    jira = JiraConfig(
        base_url=_required(source, "JIRA_BASE_URL").rstrip("/"),
        email=_required(source, "JIRA_EMAIL"),
        api_token=_required(source, "JIRA_API_TOKEN"),
        project_key=_required(source, "JIRA_PROJECT_KEY"),
        issue_type=_optional(source, "JIRA_ISSUE_TYPE", "Story"),
        investments_category_field_id=_required(
            source, "JIRA_INVESTMENTS_CATEGORY_FIELD_ID"
        ),
        investments_category_value=_normalize_investment_category_value(
            _optional_cat_value(source)
        ),
        investments_category_option_id=_optional(
            source, "JIRA_INVESTMENTS_CATEGORY_OPTION_ID"
        ),
        workflow_field_id=_optional(source, "JIRA_WORKFLOW_FIELD_ID"),
        workflow_value=_optional(source, "JIRA_WORKFLOW_VALUE", DEFAULT_WORKFLOW),
    )
    onshape = OnshapeConfig(
        base_url=_optional(
            source, "ONSHAPE_BASE_URL", "https://cad.onshape.com"
        ).rstrip("/"),
        access_key=_required(source, "ONSHAPE_ACCESS_KEY"),
        secret_key=_required(source, "ONSHAPE_SECRET_KEY"),
        company_id=_optional(source, "ONSHAPE_COMPANY_ID"),
        webhook_url=_optional(source, "ONSHAPE_WEBHOOK_URL"),
        webhook_token=_optional(source, "ONSHAPE_WEBHOOK_TOKEN"),
    )

    return AppConfig(
        jira=jira,
        onshape=onshape,
        state_path=Path(_optional(source, "STATE_PATH", ".onshape_jira_state.json")),
        host=_optional(source, "HOST", "0.0.0.0"),
        port=int(_optional(source, "PORT", "8080")),
        poll_interval_seconds=_positive_int(source, "POLL_INTERVAL_SECONDS", "300"),
        onshape_document_list_page_limit=min(
            _positive_int(
                source,
                "ONSHAPE_DOCUMENT_LIST_PAGE_LIMIT",
                str(DOCUMENT_LIST_SEARCH_MAX_LIMIT),
            ),
            DOCUMENT_LIST_SEARCH_MAX_LIMIT,
        ),
        log_level=_optional(source, "LOG_LEVEL", "INFO"),
        http_timeout_seconds=_http_timeout_seconds(source),
    )
