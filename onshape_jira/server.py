"""Webhook HTTP server entrypoint."""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from .config import AppConfig, load_config
from .http import JsonHttpClient
from .jira import JiraClient
from .onshape import OnshapeClient, webhook_registration_payload
from .state import StateStore
from .sync import OnshapeJiraSync


def build_sync(config: AppConfig) -> OnshapeJiraSync:
    http_client = JsonHttpClient()
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
    class WebhookHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - http.server API
            if self.path == "/health":
                self._send_json(200, {"status": "ok"})
                return
            self._send_json(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802 - http.server API
            parsed = urlparse(self.path)
            if parsed.path != "/webhook":
                self._send_json(404, {"error": "not found"})
                return
            if not self._authorized(parsed.query):
                self._send_json(401, {"error": "unauthorized"})
                return

            try:
                payload = self._read_json()
                result = sync.handle_webhook(payload)
            except Exception as exc:  # pragma: no cover - kept visible in server logs
                self.log_error("webhook processing failed: %s", exc)
                self._send_json(500, {"error": str(exc)})
                return
            self._send_json(200, result.__dict__)

        def log_message(self, format: str, *args: Any) -> None:
            # Preserve default stderr logging format while satisfying type checkers.
            super().log_message(format, *args)

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


def serve(config: AppConfig) -> None:
    server = ThreadingHTTPServer(
        (config.host, config.port), make_handler(build_sync(config), config.onshape.webhook_token)
    )
    print(f"Listening for Onshape webhooks on {config.host}:{config.port}/webhook")
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
    subcommands = parser.add_subparsers(dest="command")
    subcommands.add_parser("serve", help="Run the webhook HTTP server")
    subcommands.add_parser("register-webhook", help="Create the Onshape company webhook")
    subcommands.add_parser("print-webhook-payload", help="Print the webhook registration JSON")
    args = parser.parse_args()

    config = load_config()
    if args.command in (None, "serve"):
        serve(config)
    elif args.command == "register-webhook":
        print(json.dumps(register_webhook(config), indent=2))
    elif args.command == "print-webhook-payload":
        print_webhook_payload(config)


if __name__ == "__main__":
    main()
