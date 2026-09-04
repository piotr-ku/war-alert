"""
    ntfy.sh notifier for war-alert.
"""

import base64
import json
import os
import logging
import requests
import time
from notifiers.base import Notifier
from processors.base import Content

DEFAULT_SERVER = "https://ntfy.sh"
DEFAULT_PRIORITY = "high"


def _server_url() -> str:
    """
        Return the ntfy server URL without a trailing slash.
    """
    raw = os.environ.get("NTFY_URL", DEFAULT_SERVER)
    if raw is None or raw.strip() == "":
        return DEFAULT_SERVER
    return raw.strip().rstrip("/")


def _priority() -> str:
    """
        Return the ntfy message priority header value.
    """
    raw = os.environ.get("NTFY_PRIORITY")
    if raw is None or raw.strip() == "":
        return DEFAULT_PRIORITY
    return raw.strip()


def _http_header(value: str) -> str:
    """
        Return a latin-1-safe HTTP header value.

        requests encodes headers as latin-1. Non-latin-1 text is sent as
        RFC 2047 encoded-words, which ntfy supports.
    """
    try:
        value.encode("latin-1")
        return value
    except UnicodeEncodeError:
        encoded = base64.b64encode(
            value.encode("utf-8"),
        ).decode("ascii")
        return f"=?UTF-8?B?{encoded}?="


class NotifierNtfy(Notifier):
    """
        Send alert notifications via the ntfy HTTP API.
    """
    def notify(self, content: Content, logger: logging.Logger) -> bool:
        """
            Send an ntfy notification.
        """
        topic = os.environ.get("NTFY_TOPIC", "").strip()
        if topic == "":
            return False

        url = f"{_server_url()}/{topic}"
        message = f"{content.description}\n\n{content.link}"
        headers = {
            "Title": _http_header(content.title),
            "Priority": _priority(),
        }
        if content.link:
            headers["Click"] = _http_header(content.link)

        tags = os.environ.get("NTFY_TAGS")
        if tags is not None and tags.strip() != "":
            headers["Tags"] = _http_header(tags.strip())

        token = os.environ.get("NTFY_TOKEN")
        if token is not None and token.strip() != "":
            headers["Authorization"] = f"Bearer {token.strip()}"

        try:
            response = requests.post(url, data=message, headers=headers)
        except Exception as e:
            logger.error(json.dumps({
                "time": time.strftime(
                    "%Y-%m-%dT%H:%M:%S",
                    time.localtime(),
                ),
                "msg": "Error sending ntfy notification",
                "exception": str(e),
            }, ensure_ascii=False))
            return False

        if response.status_code != 200:
            logger.error(json.dumps({
                "time": time.strftime(
                    "%Y-%m-%dT%H:%M:%S",
                    time.localtime(),
                ),
                "msg": "Error sending ntfy notification",
                "status": response.status_code,
                "info": response.headers,
                "response": response.text,
            }, ensure_ascii=False))
            return False

        return True
