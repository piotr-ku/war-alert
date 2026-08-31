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
    raw = os.environ.get("TELEGRAM_MIN_INTERVAL")
    if raw is None or raw.strip() == "":
        return DEFAULT_MIN_INTERVAL
    try:
        return max(float(raw), 0.0)
    except ValueError:
        return DEFAULT_MIN_INTERVAL


def _retry_after_seconds(response: requests.Response) -> float:
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
        A base class for all Telegram notifiers.
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

        url = f"{self.api_url}{os.environ.get('TELEGRAM_BOT_TOKEN')}/sendMessage"
        payload = {
            "chat_id": os.environ.get("TELEGRAM_CHANNEL_ID"),
            "text": f"{content.title}\n\n{content.description}\n\n{content.link}",
        }

        for attempt in range(MAX_ATTEMPTS):
            with _send_lock:
                wait = _min_interval() - (time.time() - _last_send_time)
            if wait > 0:
                time.sleep(wait)

            try:
                response = requests.post(url, json=payload)
            except Exception as e:
                logger.error(json.dumps({
                    "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
                    "msg": "Error sending Telegram notification",
                    "exception": str(e),
                }, ensure_ascii=False))
                return False

            if response.status_code == 200:
                try:
                    if response.json().get("ok"):
                        with _send_lock:
                            _last_send_time = time.time()
                        return True
                except json.JSONDecodeError:
                    pass
                logger.error(json.dumps({
                    "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
                    "msg": "Error sending Telegram notification",
                    "status": response.status_code,
                    "response": response.text,
                }, ensure_ascii=False))
                return False

            if response.status_code == 429 and attempt < MAX_ATTEMPTS - 1:
                sleep_for = _retry_after_seconds(response) + 0.5
                logger.warning(json.dumps({
                    "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
                    "msg": "Telegram rate limit hit, retrying",
                    "retry": attempt + 1,
                    "sleep": sleep_for,
                }, ensure_ascii=False))
                time.sleep(sleep_for)
                continue

            logger.error(json.dumps({
                "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
                "msg": "Error sending Telegram notification",
                "status": response.status_code,
                "response": response.text,
            }, ensure_ascii=False))
            return False

        return False
