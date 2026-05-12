"""Environment-backed configuration for the integration service."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


DEFAULT_INVESTMENTS_CATEGORY = "Planned - Product & Engineering"
DEFAULT_WORKFLOW = "IoT Workflows"


@dataclass(frozen=True)
class JiraConfig:
    base_url: str
    email: str
    api_token: str
    project_key: str
    issue_type: str = "Story"
    investments_category_field_id: str = ""
    investments_category_value: str = DEFAULT_INVESTMENTS_CATEGORY
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


def _required(env: Mapping[str, str], name: str) -> str:
    value = env.get(name, "").strip()
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def _optional(env: Mapping[str, str], name: str, default: str = "") -> str:
    return env.get(name, default).strip()


def load_config(env: Mapping[str, str] | None = None) -> AppConfig:
    """Load configuration from environment variables."""

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
        investments_category_value=_optional(
            source, "JIRA_INVESTMENTS_CATEGORY_VALUE", DEFAULT_INVESTMENTS_CATEGORY
        ),
        workflow_field_id=_optional(source, "JIRA_WORKFLOW_FIELD_ID"),
        workflow_value=_optional(source, "JIRA_WORKFLOW_VALUE", DEFAULT_WORKFLOW),
    )
    onshape = OnshapeConfig(
        base_url=_optional(source, "ONSHAPE_BASE_URL", "https://cad.onshape.com").rstrip(
            "/"
        ),
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
    )
