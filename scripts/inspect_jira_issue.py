#!/usr/bin/env python3
"""Fetch one Jira Cloud issue via REST API and print its fields.

Use this to inspect how custom fields are stored (e.g. Investment Category id/value).

  cd /path/to/IoT-Hardware
  source .venv/bin/activate   # optional
  export JIRA_BASE_URL=https://cmtelematics.atlassian.net
  export JIRA_EMAIL=you@company.com
  export JIRA_API_TOKEN=...

  python3 scripts/inspect_jira_issue.py IOTHW-1
  python3 scripts/inspect_jira_issue.py IOTHW-1 --compact
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlencode


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env")
except ImportError:
    pass

from onshape_jira.http import BasicAuth, JsonHttpClient  # noqa: E402


def _require_env(name: str) -> str:
    value = (os.environ.get(name, "") or "").strip()
    if not value:
        print(f"missing env {name}", file=sys.stderr)
        sys.exit(1)
    return value


def fetch_issue(
    base_url: str,
    email: str,
    token: str,
    issue_key: str,
    *,
    fields: str | None,
) -> dict:
    base = base_url.rstrip("/")
    params: dict[str, str] = {
        "expand": "names,schema,renderedFields",
    }
    if fields:
        params["fields"] = fields
    query = urlencode(params)
    path = f"/rest/api/3/issue/{issue_key}?{query}"
    url = base + path

    auth = BasicAuth(email, token).header_value()
    client = JsonHttpClient()
    return client.request_json(
        "GET",
        url,
        headers={
            "Authorization": auth,
            "Accept": "application/json",
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Print Jira issue JSON (fields + schema + names)."
    )
    parser.add_argument(
        "issue_key",
        nargs="?",
        default="IOTHW-1",
        help='Issue key (default: "IOTHW-1")',
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Single-line JSON (easier to pipe)",
    )
    parser.add_argument(
        "--fields",
        metavar="CSV",
        default=None,
        help=(
            "REST `fields=` list (comma-separated). Example: "
            "`summary,customfield_11822`. Omit for Jira's default/navigable set."
        ),
    )
    args = parser.parse_args()

    base_url = _require_env("JIRA_BASE_URL")
    email = _require_env("JIRA_EMAIL")
    token = _require_env("JIRA_API_TOKEN")

    try:
        body = fetch_issue(
            base_url,
            email,
            token,
            args.issue_key,
            fields=args.fields,
        )
    except Exception as exc:
        print(f"request failed: {exc}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(body, dict):
        print("unexpected response (not an object)", file=sys.stderr)
        sys.exit(1)

    if args.compact:
        text = json.dumps(body, separators=(",", ":"), sort_keys=True)
    else:
        text = json.dumps(body, indent=2, sort_keys=True)
    print(text)

    fields = body.get("fields") if isinstance(body.get("fields"), dict) else {}
    names = body.get("names") if isinstance(body.get("names"), dict) else {}
    hr = "=" * 72
    print("\n" + hr, file=sys.stderr)
    print("Quick field summary (stderr):", file=sys.stderr)
    print(hr, file=sys.stderr)
    for fid, label in sorted(names.items()):
        raw = fields.get(fid)
        if raw is None:
            continue
        preview = repr(raw)
        if len(preview) > 200:
            preview = preview[:197] + "..."
        print(f"  {fid} ({label}): {preview}", file=sys.stderr)


if __name__ == "__main__":
    main()
