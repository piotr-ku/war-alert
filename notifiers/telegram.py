"""
    Telegram Bot API notifier for war-alert.
"""

import json
import os
import logging
import requests
import threading
import time
from notifiers.base import Notifier
from processors.base import Content

_send_lock = threading.Lock()
_last_send_time = 0.0
DEFAULT_MIN_INTERVAL = 1.0
MAX_ATTEMPTS = 3


def _min_interval() -> float:
    """
        Return the minimum seconds between Telegram API sends.
    """
    raw = os.environ.get("TELEGRAM_MIN_INTERVAL")
    if raw is None or raw.strip() == "":
        return DEFAULT_MIN_INTERVAL
    try:
        return max(float(raw), 0.0)
    except ValueError:
        return DEFAULT_MIN_INTERVAL


def _retry_after_seconds(response: requests.Response) -> float:
    """
        Parse retry_after from a Telegram 429 response.
    """
    try:
        payload = response.json()
        parameters = payload.get("parameters", {})
        if isinstance(parameters, dict):
            return float(parameters.get("retry_after", 1))
    except (TypeError, ValueError, json.JSONDecodeError):
        pass
    return 1.0


class NotifierTelegram(Notifier):
    """
        Send alert notifications via the Telegram Bot API.
    """
    def __init__(self):
        """
            Initialize a Telegram notifier.
        """
        self.api_url = "https://api.telegram.org/bot"

    def notify(self, content: Content, logger: logging.Logger) -> bool:
        """
            Send a message to a Telegram channel using the Telegram Bot API.
        """
        global _last_send_time

        token = os.environ.get("TELEGRAM_BOT_TOKEN")
        url = f"{self.api_url}{token}/sendMessage"
        payload = {
            "chat_id": os.environ.get("TELEGRAM_CHANNEL_ID"),
            "text": (
                f"{content.title}\n\n"
                f"{content.description}\n\n"
                f"{content.link}"
            ),
        }

        for attempt in range(MAX_ATTEMPTS):
            # Enforce a minimum interval between sends
            with _send_lock:
                wait = _min_interval() - (time.time() - _last_send_time)
            if wait > 0:
                time.sleep(wait)

            # POST the message to the Bot API
            try:
                response = requests.post(url, json=payload)
            except Exception as e:
                logger.error(json.dumps({
                    "time": time.strftime(
                        "%Y-%m-%dT%H:%M:%S",
                        time.localtime(),
                    ),
                    "msg": "Error sending Telegram notification",
                    "exception": str(e),
                }, ensure_ascii=False))
                return False

            # Check for a successful API response
            if response.status_code == 200:
                try:
                    if response.json().get("ok"):
                        with _send_lock:
                            _last_send_time = time.time()
                        return True
                except json.JSONDecodeError:
                    pass
                logger.error(json.dumps({
                    "time": time.strftime(
                        "%Y-%m-%dT%H:%M:%S",
                        time.localtime(),
                    ),
                    "msg": "Error sending Telegram notification",
                    "status": response.status_code,
                    "response": response.text,
                }, ensure_ascii=False))
                return False

            # Retry after a rate-limit response
            if response.status_code == 429 and attempt < MAX_ATTEMPTS - 1:
                sleep_for = _retry_after_seconds(response) + 0.5
                logger.warning(json.dumps({
                    "time": time.strftime(
                        "%Y-%m-%dT%H:%M:%S",
                        time.localtime(),
                    ),
                    "msg": "Telegram rate limit hit, retrying",
                    "retry": attempt + 1,
                    "sleep": sleep_for,
                }, ensure_ascii=False))
                time.sleep(sleep_for)
                continue

            logger.error(json.dumps({
                "time": time.strftime(
                    "%Y-%m-%dT%H:%M:%S",
                    time.localtime(),
                ),
                "msg": "Error sending Telegram notification",
                "status": response.status_code,
                "response": response.text,
            }, ensure_ascii=False))
            return False

        return False
