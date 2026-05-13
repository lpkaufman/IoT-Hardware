# IoT-Hardware

This repository contains a small Python webhook service that syncs Onshape
documents into Jira stories for the IoT Hardware project.

## Behavior

- Onshape document creation creates one Jira story.
- The Jira story summary is the current Onshape document name.
- The default Investment Category value must match Jira’s option **character-for-character**. In this org the label uses an **en dash** (`U+2013`) in `Planned – Product & Engineering`, not an ASCII hyphen (`-`). Confirm with `scripts/inspect_jira_issue.py` or createmeta; you can also set **`JIRA_INVESTMENTS_CATEGORY_OPTION_ID`** to the option **`id`** returned by the API.
- The Jira description contains the document tab names, one per line, and is
  refreshed with versions, branches, and detected document name changes when
  Onshape sends subsequent document/model lifecycle events.
- The configured Jira workflow field can be set to **Simple 3 state workflow**
  when your Jira instance exposes workflow as a writable custom field (`JIRA_WORKFLOW_FIELD_ID`).
  The default **`JIRA_WORKFLOW_VALUE`** is `Simple 3 state workflow` (not vtrack / IoT Workflows).
  In many Jira projects the workflow is driven by project and issue type scheme; sync still
  sets the writable workflow field whenever it is configured.

## Configuration

Set these environment variables before running the service:

| Variable | Purpose |
| --- | --- |
| `JIRA_BASE_URL` | Jira Cloud base URL, for example `https://example.atlassian.net` |
| `JIRA_EMAIL` | Jira API user email |
| `JIRA_API_TOKEN` | Jira API token |
| `JIRA_PROJECT_KEY` | Project key for the IoT Hardware Jira space |
| `JIRA_INVESTMENTS_CATEGORY_FIELD_ID` | Jira custom field id for Investments Category, for example `customfield_12345` |
| `JIRA_INVESTMENTS_CATEGORY_VALUE` | Option **label** for that field (`{"value": "..."}`). Must match Jira **exactly**, including punctuation (many sites use **en dash** `–` in “Planned – Product…”); defaults match cmtelematics `inspect_jira_issue` output |
| `JIRA_INVESTMENTS_CATEGORY_OPTION_ID` | If set, overrides value and sends `{"id": "..."}` (recommended for stability). Otherwise, for **`customfield_11822`** with the Planned default label, the client automatically uses option id **`11740`** (cmtelematics IoT Hardware; see **`scripts/inspect_jira_issue.py`**) |
| `JIRA_WORKFLOW_FIELD_ID` | Optional writable custom field id for Workflow |
| `JIRA_WORKFLOW_VALUE` | Optional override for the Workflow field label; defaults to **`Simple 3 state workflow`** |
| `ONSHAPE_BASE_URL` | Optional; defaults to `https://cad.onshape.com` |
| `ONSHAPE_ACCESS_KEY` | Onshape API access key |
| `ONSHAPE_SECRET_KEY` | Onshape API secret key |
| `ONSHAPE_COMPANY_ID` | Onshape company id (webhook registration, polling, webhook payload tooling) |
| `ONSHAPE_WEBHOOK_URL` | Public URL for this service's `/webhook` endpoint |
| `ONSHAPE_WEBHOOK_TOKEN` | Optional shared token checked through `X-Onshape-Jira-Token` or `?token=` |
| `STATE_PATH` | Optional local mapping file path; defaults to `.onshape_jira_state.json` |
| `POLL_INTERVAL_SECONDS` | Seconds between polls when using `poll` subcommand; defaults to `300` |
| `ONSHAPE_DOCUMENT_LIST_PAGE_LIMIT` | Page size for `GET /api/documents` when polling (Onshape caps this at **20**; larger values are reduced to 20); defaults to `20` |
| `HOST` / `PORT` | Optional server bind settings; defaults to `0.0.0.0:8080` |
| `LOG_LEVEL` | Python log level (`DEBUG`, `INFO`, etc.) for stderr diagnostics; defaults to `INFO` |

HTTP **400** on create with **`Specify a valid value for Investment Category`** means the Investments field does not recognize your configured label. Align **`JIRA_INVESTMENTS_CATEGORY_VALUE`** with an option **`value`** shown in issue createmeta, or set **`JIRA_INVESTMENTS_CATEGORY_OPTION_ID`** from an **`allowedValues`** **`id`** (see **`GET`** `/rest/api/3/issue/createmeta/{projectKeyOrId}/issuetypes/{issueTypeId}`).

Outbound HTTPS requests use **`certifi`’s CA bundle** so macOS/Python.org installs succeed without running “Install Certificates”. Set **`HTTPS_SKIP_VERIFY=1`** only for debugging behind misconfigured proxies (disables TLS verification).

Verbosity:

- Logs go to **stderr**. Use **`LOG_LEVEL=DEBUG`** or pass **`-v` / `--verbose` before the subcommand** (`python3 -m onshape_jira.server -v poll-once`) to force DEBUG and include webhook payloads plus per-request API timings (`-v` overrides `LOG_LEVEL`).
- `poll-once` / `poll` still print JSON summaries on **stdout** for scripting.

## Running

```bash
python3 -m onshape_jira.server serve
```

The server exposes:

- `GET /health` for health checks.
- `POST /webhook` for Onshape webhook notifications.

Startup, each request path, webhook outcomes, sync steps, and Onshape/Jira API timing (at DEBUG) are written to stderr.

## Registering the Onshape webhook

After the service is reachable at `ONSHAPE_WEBHOOK_URL`, register a company
webhook:

```bash
python3 -m onshape_jira.server register-webhook
```

To inspect the registration payload without calling Onshape:

```bash
python3 -m onshape_jira.server print-webhook-payload
```

The webhook listens for document creation, version creation, workspace/branch
creation, tab create/delete, metadata, and model change events.

## Optional: polling (no public webhook)

Crawl **all documents owned by the company** (`ONSHAPE_COMPANY_ID`) via the Onshape Documents search API, sync each document to Jira like the webhook path does, and skip Jira updates when nothing changed:

```bash
python3 -m onshape_jira.server poll-once
python3 -m onshape_jira.server poll
python3 -m onshape_jira.server poll --interval 120
```

Use this when Onshape cannot reach a public `/webhook` URL while your runner has outbound HTTPS to Onshape and Jira.

## Tests

```bash
python3 -m unittest discover
```
