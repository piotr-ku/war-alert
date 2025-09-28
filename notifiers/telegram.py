import json
import os
import logging
import requests
import time
from notifiers.base import Notifier
from processors.base import Content

class NotifierTelegram(Notifier):
    """
        A base class for all Telegram notifiers.
    """
    def __init__(self):
        """
            Initialize a Telegram notifier.
        """
        self.api_url = "https://api.telegram.org/bot"

    def notify(self, content: Content, logger: logging.Logger) -> None:
        """
            Send a message to a Telegram channel using the Telegram Bot API.
        """
        url = f"{self.api_url}{os.environ.get('TELEGRAM_BOT_TOKEN')}/sendMessage"
        payload = {
            "chat_id": os.environ.get("TELEGRAM_CHANNEL_ID"),
            "text": f"{content.title}\n\n{content.description}\n\n{content.link}",
        }

        # Send a POST request
        try:
            response = requests.post(url, json=payload)
        except Exception as e:
            logger.error(json.dumps({
                "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
                "msg": "Error sending Telegram notification",
                "exception": str(e),
            }, ensure_ascii=False))
            return

        # Check the response
        if response.status_code != 200:
            logger.error(json.dumps({
                "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
                "msg": "Error sending Telegram notification",
                "status": response.status_code,
                "response": response.text,
            }, ensure_ascii=False))

        return
