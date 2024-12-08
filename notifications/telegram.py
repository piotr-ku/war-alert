import json
import os
import requests
import time

# The Telegram Bot API URL
api_url = "https://api.telegram.org/bot"

def notify(title, message, logger):
    """
        Send a message to a Telegram channel using the Telegram Bot API.

        Args:
            title (str): The title of the notification.
            message (str): The message of the notification.
            logger (logging.Logger): The logger to use.
    """
    url = f"{api_url}{os.environ.get('TELEGRAM_BOT_TOKEN')}/sendMessage"
    payload = {
        "chat_id": os.environ.get("TELEGRAM_CHANNEL_ID"),
        "text": f"{title}\n\n{message}",
    }

    # Send a POST request
    try:
        response = requests.post(url, json=payload)
    except Exception as e:
        logger.error(json.dumps({
            "msg": "Error sending Telegram notification",
            "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
            "exception": str(e),
        }, ensure_ascii=False))
        return

    # Check the response
    if response.status_code != 200:
        logger.error(json.dumps({
            "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
            "status": response.status_code,
            "response": response.text,
        }, ensure_ascii=False))