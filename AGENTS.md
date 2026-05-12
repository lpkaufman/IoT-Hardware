# AGENTS.md

## Cursor Cloud specific instructions

This is a pure-Python (stdlib only, zero pip dependencies) webhook service that syncs Onshape CAD documents into Jira stories. See `README.md` for full configuration and usage.

### Quick reference

| Task | Command |
|---|---|
| Install (dev) | `pip install -e .` |
| Run tests | `python3 -m unittest discover` |
| Lint | `ruff check .` |
| Type check | `pyright` (pre-existing warnings in test files due to fake/mock objects not matching exact class types — these are expected) |
| Start server | `python3 -m onshape_jira.server serve` (requires env vars; see README) |
| Health check | `curl http://localhost:8080/health` |

### Non-obvious caveats

- The server requires several environment variables to start (`JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN`, `JIRA_PROJECT_KEY`, `JIRA_INVESTMENTS_CATEGORY_FIELD_ID`, `ONSHAPE_ACCESS_KEY`, `ONSHAPE_SECRET_KEY`). For local dev/testing without real credentials, provide dummy values — the server will start and the `/health` endpoint will work, but webhook processing will fail on external API calls.
- Unit tests use fakes/mocks and need no external services or env vars.
- The project uses only the Python standard library — no `requirements.txt` or lock file exists because there are no runtime dependencies.
- `pyright` reports type errors in test files because the test fakes (`FakeOnshapeClient`, `FakeJiraClient`, `RecordingHttpClient`) do not implement the full class interfaces; this is by design and not a bug.
