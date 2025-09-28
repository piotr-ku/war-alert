import json
import os
import logging
import requests
import time
from notifiers.base import Notifier
from processors.base import Content

class NotifierPushover(Notifier):
    """
        A base class for all Pushover notifiers.
    """
    def __init__(self):
        """
            Initialize a Pushover notifier.
        """
        self.api_url = "https://api.pushover.net/1/messages.json"

    def notify(self, content: Content, logger: logging.Logger) -> None:
        """
            Send a Pushover notification.
        """
        # Send a POST request
        try:
            response = requests.post(self.api_url, data={
                "token": os.environ.get("PUSHOVER_TOKEN"),
                "user": os.environ.get("PUSHOVER_USER"),
                "title": content.title,
                "message": f"{content.description}\n\n{content.link}",
                "priority": 1,
            })
        except Exception as e:
            logger.error(json.dumps({
                "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
                "msg": "Error sending Pushover notification",
                "exception": str(e),
            }, ensure_ascii=False))
            return

        # Check the response
        if response.status_code != 200:
            logger.error(json.dumps({
                "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
                "status": response.status_code,
                "info": response.headers,
                "response": response.text,
            }, ensure_ascii=False))

        return
