"""Webhook HTTP server entrypoint."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from .config import AppConfig, load_config
from .http import JsonHttpClient
from .jira import JiraClient
from .logging_config import configure_logging
from .onshape import OnshapeClient, webhook_registration_payload
from .state import StateStore
from .sync import OnshapeJiraSync


_LOG = logging.getLogger(__name__)


def build_sync(config: AppConfig) -> OnshapeJiraSync:
    http_client = JsonHttpClient(timeout_seconds=config.http_timeout_seconds)
    onshape = OnshapeClient(
        config.onshape.base_url,
        config.onshape.access_key,
        config.onshape.secret_key,
        http_client=http_client,
    )
    jira = JiraClient(config.jira, http_client=http_client)
    return OnshapeJiraSync(onshape, jira, StateStore(config.state_path))


def make_handler(
    sync: OnshapeJiraSync, webhook_token: str = ""
) -> type[BaseHTTPRequestHandler]:
    handler_log = logging.getLogger("onshape_jira.server.webhook")

    class WebhookHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - http.server API
            if self.path == "/health":
                handler_log.debug("GET /health from %s", self.client_address[0])
                self._send_json(200, {"status": "ok"})
                return
            handler_log.info("GET %s -> 404 from %s", self.path, self.client_address[0])
            self._send_json(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802 - http.server API
            parsed = urlparse(self.path)
            content_length_raw = self.headers.get("Content-Length") or "0"
            handler_log.info(
                "POST %s Content-Length=%s from=%s query=%s",
                parsed.path,
                content_length_raw,
                self.client_address[0],
                parsed.query or "(none)",
            )
            if parsed.path != "/webhook":
                self._send_json(404, {"error": "not found"})
                return
            if not self._authorized(parsed.query):
                handler_log.warning(
                    "webhook rejected (unauthorized token) client=%s",
                    self.client_address[0],
                )
                self._send_json(401, {"error": "unauthorized"})
                return

            try:
                payload = self._read_json()
                result = sync.handle_webhook(payload)
                handler_log.info(
                    "webhook responded 200 status=%s document_id=%s",
                    result.status,
                    result.document_id,
                )
            except Exception as exc:  # pragma: no cover - kept visible in server logs
                self.log_error("webhook processing failed: %s", exc)
                _LOG.exception(
                    "webhook processing raised from client=%s", self.client_address[0]
                )
                self._send_json(500, {"error": str(exc)})
                return
            self._send_json(200, result.__dict__)

        def log_message(self, format: str, *args: Any) -> None:
            logging.getLogger("onshape_jira.server.http").info(
                "%s %s", self.address_string(), format % args if args else format
            )

        def _authorized(self, query: str) -> bool:
            if not webhook_token:
                return True
            if self.headers.get("X-Onshape-Jira-Token") == webhook_token:
                return True
            token_values = parse_qs(query).get("token", [])
            return bool(token_values and token_values[0] == webhook_token)

        def _read_json(self) -> dict[str, Any]:
            content_length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(content_length).decode("utf-8")
            payload = json.loads(raw_body or "{}")
            if not isinstance(payload, dict):
                raise ValueError("Webhook body must be a JSON object")
            return payload

        def _send_json(self, status_code: int, body: dict[str, Any]) -> None:
            encoded = json.dumps(body).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    return WebhookHandler


def poll_company_documents(config: AppConfig) -> dict[str, int]:
    """One full crawl of company-owned Onshape documents; updates Jira as needed."""

    if not config.onshape.company_id:
        raise ValueError("ONSHAPE_COMPANY_ID is required for company polling")

    sync = build_sync(config)
    return sync.poll_company_documents(
        config.onshape.company_id,
        page_limit=config.onshape_document_list_page_limit,
    )


def poll_forever(config: AppConfig, interval_seconds: int) -> None:
    if interval_seconds < 1:
        raise ValueError("poll interval must be at least 1 second")

    sync = build_sync(config)
    if not config.onshape.company_id:
        raise ValueError("ONSHAPE_COMPANY_ID is required for company polling")

    page_limit = config.onshape_document_list_page_limit
    company_id = config.onshape.company_id
    _LOG.info(
        "Polling started company_id=%s interval=%ss page_limit=%s (Ctrl+C to stop)",
        company_id,
        interval_seconds,
        page_limit,
    )

    try:
        while True:
            summary = sync.poll_company_documents(company_id, page_limit=page_limit)
            _LOG.info("poll cycle complete summary=%s", summary)
            print(json.dumps({"summary": summary}), flush=True)
            time.sleep(interval_seconds)
    except KeyboardInterrupt:
        _LOG.info("Polling stopped by user (KeyboardInterrupt).")


def serve(config: AppConfig) -> None:
    _LOG.info(
        "HTTP server binding host=%s port=%s webhook_path=/webhook",
        config.host,
        config.port,
    )
    server = ThreadingHTTPServer(
        (config.host, config.port),
        make_handler(build_sync(config), config.onshape.webhook_token),
    )
    _LOG.info(
        "Listening http://%s:%s/webhook (GET /health for probes)",
        config.host,
        config.port,
    )
    server.serve_forever()


def register_webhook(config: AppConfig) -> dict[str, Any]:
    if not config.onshape.company_id:
        raise ValueError("ONSHAPE_COMPANY_ID is required to register a company webhook")
    if not config.onshape.webhook_url:
        raise ValueError("ONSHAPE_WEBHOOK_URL is required to register a webhook")

    client = OnshapeClient(
        config.onshape.base_url,
        config.onshape.access_key,
        config.onshape.secret_key,
    )
    _LOG.info(
        "Registering company webhook via Onshape API company_id=%s url=%s",
        config.onshape.company_id,
        config.onshape.webhook_url,
    )
    return client.create_company_webhook(
        company_id=config.onshape.company_id,
        url=config.onshape.webhook_url,
    )


def print_webhook_payload(config: AppConfig) -> None:
    if not config.onshape.company_id:
        raise ValueError("ONSHAPE_COMPANY_ID is required to render a webhook payload")
    if not config.onshape.webhook_url:
        raise ValueError("ONSHAPE_WEBHOOK_URL is required to render a webhook payload")
    print(
        json.dumps(
            webhook_registration_payload(
                config.onshape.company_id, config.onshape.webhook_url
            ),
            indent=2,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Onshape to Jira webhook service")
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Log at DEBUG including raw webhook payloads and per-API timings",
    )
    subcommands = parser.add_subparsers(dest="command")
    subcommands.add_parser("serve", help="Run the webhook HTTP server")
    subcommands.add_parser(
        "register-webhook", help="Create the Onshape company webhook"
    )
    subcommands.add_parser(
        "print-webhook-payload", help="Print the webhook registration JSON"
    )
    subcommands.add_parser(
        "poll-once",
        help="List all company-owned Onshape documents and sync them to Jira once",
    )
    poll_parser = subcommands.add_parser(
        "poll",
        help="Run poll-once repeatedly at POLL_INTERVAL_SECONDS (overridable)",
    )
    poll_parser.add_argument(
        "--interval",
        type=int,
        default=None,
        metavar="SECONDS",
        help="Seconds between polls; defaults to POLL_INTERVAL_SECONDS env",
    )

    args = parser.parse_args()

    config = load_config()
    configure_logging(verbose=args.verbose, log_level_env=config.log_level)
    _LOG.info(
        "log level=%s verbose_flag=%s (stderr); JSON summaries remain on stdout for poll-*",
        logging.getLevelName(logging.getLogger().getEffectiveLevel()),
        args.verbose,
    )

    if args.command in (None, "serve"):
        serve(config)
    elif args.command == "register-webhook":
        result = register_webhook(config)
        _LOG.info("register-webhook REST response OK")
        print(json.dumps(result, indent=2))
    elif args.command == "print-webhook-payload":
        print_webhook_payload(config)
    elif args.command == "poll-once":
        try:
            summary = poll_company_documents(config)
        except ValueError as exc:
            _LOG.error("poll-once aborted: %s", exc)
            print(f"poll-once failed: {exc}", file=sys.stderr)
            sys.exit(1)
        _LOG.info("poll-once stdout summary=%s", summary)
        print(json.dumps({"summary": summary}, indent=2))
    elif args.command == "poll":
        interval = (
            args.interval if args.interval is not None else config.poll_interval_seconds
        )
        try:
            poll_forever(config, interval)
        except ValueError as exc:
            _LOG.error("poll aborted: %s", exc)
            print(f"poll failed: {exc}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
