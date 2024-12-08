import json
import os
import requests
import time

# The Pushover API URL
api_url = "https://api.pushover.net/1/messages.json"

def notify(title, message, logger):
    """
        Send a Pushover notification.

        Args:
            title (str): The title of the notification.
            message (str): The message of the notification.
            logger (logging.Logger): The logger to use.
    """
    # Send a POST request
    try:
        response = requests.post(api_url, data={
            "token": os.environ.get("PUSHOVER_TOKEN"),
            "user": os.environ.get("PUSHOVER_USER"),
            "title": title,
            "message": message,
            "priority": 1,
        })
    except Exception as e:
        logger.error(json.dumps({
            "msg": "Error sending Pushover notification",
            "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
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