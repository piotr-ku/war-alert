"""
    ntfy.sh notifier for war-alert.
"""

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
            "Title": content.title,
            "Priority": _priority(),
        }
        if content.link:
            headers["Click"] = content.link

        tags = os.environ.get("NTFY_TAGS")
        if tags is not None and tags.strip() != "":
            headers["Tags"] = tags.strip()

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
