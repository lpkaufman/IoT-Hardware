# IoT-Hardware

This repository contains a small Python webhook service that syncs Onshape
documents into Jira stories for the IoT Hardware project.

## Behavior

- Onshape document creation creates one Jira story.
- The Jira story summary is the current Onshape document name.
- The configured Jira Investments Category field is set to
  `Planned - Product & Engineering`.
- The Jira description contains the document tab names, one per line, and is
  refreshed with versions, branches, and detected document name changes when
  Onshape sends subsequent document/model lifecycle events.
- The configured Jira workflow field can be set to `IoT Workflows` when your Jira
  instance exposes workflow as a writable custom field. In most Jira projects the
  actual workflow is controlled by the project and issue type scheme, so configure
  the IoT Hardware Story issue type to use the IoT Workflows workflow there.

## Configuration

Set these environment variables before running the service:

| Variable | Purpose |
| --- | --- |
| `JIRA_BASE_URL` | Jira Cloud base URL, for example `https://example.atlassian.net` |
| `JIRA_EMAIL` | Jira API user email |
| `JIRA_API_TOKEN` | Jira API token |
| `JIRA_PROJECT_KEY` | Project key for the IoT Hardware Jira space |
| `JIRA_INVESTMENTS_CATEGORY_FIELD_ID` | Jira custom field id for Investments Category, for example `customfield_12345` |
| `JIRA_INVESTMENTS_CATEGORY_VALUE` | Optional override; defaults to `Planned - Product & Engineering` |
| `JIRA_WORKFLOW_FIELD_ID` | Optional writable custom field id for Workflow |
| `JIRA_WORKFLOW_VALUE` | Optional override; defaults to `IoT Workflows` |
| `ONSHAPE_BASE_URL` | Optional; defaults to `https://cad.onshape.com` |
| `ONSHAPE_ACCESS_KEY` | Onshape API access key |
| `ONSHAPE_SECRET_KEY` | Onshape API secret key |
| `ONSHAPE_COMPANY_ID` | Onshape company id for company-scoped webhook registration |
| `ONSHAPE_WEBHOOK_URL` | Public URL for this service's `/webhook` endpoint |
| `ONSHAPE_WEBHOOK_TOKEN` | Optional shared token checked through `X-Onshape-Jira-Token` or `?token=` |
| `STATE_PATH` | Optional local mapping file path; defaults to `.onshape_jira_state.json` |
| `HOST` / `PORT` | Optional server bind settings; defaults to `0.0.0.0:8080` |

## Running

```bash
python3 -m onshape_jira.server serve
```

The server exposes:

- `GET /health` for health checks.
- `POST /webhook` for Onshape webhook notifications.

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

## Tests

```bash
python3 -m unittest discover
```
