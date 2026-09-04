"""
    HTTP health check and inbound webhook server for war-alert.
"""

import json
import logging
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from typing import Callable

from processors.base import Content, Processor
from processors.openai import ProcessorOpenAI
from processors.unique import ProcessorUnique
from sources.alertsua import Alert
from sources.rss import News

ProcessAndNotify = Callable[
    [Content, list[type[Processor]], logging.Logger],
    bool,
]

ALERT_PROCESSORS = [ProcessorUnique]
NEWS_PROCESSORS = [ProcessorUnique, ProcessorOpenAI]


def start_http_server(
    logger: logging.Logger,
    process_and_notify: ProcessAndNotify,
    port: int,
) -> None:
    """
        Start the HTTP server in a background thread.
        /health is always available; webhook endpoints require WEBHOOK_SECRET.
    """
    secret = os.environ.get("WEBHOOK_SECRET", "")
    webhooks_enabled = secret != ""
    notify_fn = process_and_notify
    app_logger = logger
    webhook_secret = secret

    class WebhookHandler(BaseHTTPRequestHandler):
        secret = webhook_secret

        def log_message(self, format, *args):
            # Use structured app logs instead of BaseHTTPRequestHandler noise
            return

        def _send_json(self, status: int, body: dict) -> None:
            payload = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _check_auth(self) -> bool:
            """
                Verify the Bearer token matches WEBHOOK_SECRET.
            """
            auth = self.headers.get("Authorization", "")
            if not auth.startswith("Bearer "):
                return False
            token = auth[7:]
            return token == self.secret and self.secret != ""

        def _read_json(self) -> dict | None:
            """
                Read and parse a JSON request body.
            """
            content_length = self.headers.get("Content-Length")
            if content_length is None:
                return None
            try:
                length = int(content_length)
            except ValueError:
                return None
            if length == 0:
                return None
            try:
                body = self.rfile.read(length)
                return json.loads(body.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                return None

        def _parse_content(
            self,
            data: dict,
            content_class: type,
        ) -> Content | None:
            """
                Build a Content object from webhook JSON fields.
            """
            title = data.get("title")
            if not title or not isinstance(title, str):
                return None
            description = data.get("description", "")
            if description is None:
                description = ""
            pub_date = data.get("pubDate")
            if pub_date is None:
                pub_date = time.strftime(
                    "%Y-%m-%dT%H:%M:%S",
                    time.localtime(),
                )
            link = data.get("link", "")
            if link is None:
                link = ""
            return content_class(title, description, pub_date, link)

        def _handle_webhook(
            self,
            content_class: type,
            processors: list[type[Processor]],
            source: str,
        ) -> None:
            """
                Authenticate, parse, and process one webhook request.
            """
            if not self._check_auth():
                app_logger.warning(json.dumps({
                    "time": time.strftime(
                        "%Y-%m-%dT%H:%M:%S",
                        time.localtime(),
                    ),
                    "source": "webhook",
                    "endpoint": self.path,
                    "msg": "Unauthorized",
                }))
                self._send_json(401, {"error": "Unauthorized"})
                return

            data = self._read_json()
            if data is None:
                self._send_json(400, {"error": "Invalid JSON"})
                return

            content = self._parse_content(data, content_class)
            if content is None:
                self._send_json(400, {"error": "Missing or invalid title"})
                return

            app_logger.info(json.dumps({
                "time": time.strftime(
                    "%Y-%m-%dT%H:%M:%S",
                    time.localtime(),
                ),
                "source": source,
                "title": content.title,
            }))

            notified = notify_fn(content, processors, app_logger)
            status = "notified" if notified else "ignored"
            self._send_json(200, {"status": status})

        def do_GET(self) -> None:
            """
                Serve the health check endpoint.
            """
            if self.path == "/health":
                self._send_json(200, {"status": "ok"})
                return
            self._send_json(404, {"error": "Not found"})

        def do_POST(self) -> None:
            """
                Dispatch webhook routes when WEBHOOK_SECRET is configured.
            """
            if not webhooks_enabled:
                self._send_json(503, {"error": "Webhooks not configured"})
                return
            if self.path == "/webhook/alert":
                self._handle_webhook(
                    Alert,
                    ALERT_PROCESSORS,
                    "webhook/alert",
                )
                return
            if self.path == "/webhook/news":
                self._handle_webhook(
                    News,
                    NEWS_PROCESSORS,
                    "webhook/news",
                )
                return
            self._send_json(404, {"error": "Not found"})

    server = ThreadingHTTPServer(("", port), WebhookHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()

    logger.info(json.dumps({
        "time": time.strftime(
            "%Y-%m-%dT%H:%M:%S",
            time.localtime(),
        ),
        "source": "http",
        "msg": "HTTP server started",
        "port": port,
        "webhooks": webhooks_enabled,
    }))


start_webhook_server = start_http_server
