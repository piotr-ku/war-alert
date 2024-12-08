#!/usr/bin/env python3

import dotenv
import hashlib
import html.parser
import json
import logging
import openai
import os
import requests
import signal
import sys
import time
import urllib
import xml.etree
import xml.etree.ElementTree

# Create a logger and set stdout as a handler
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
logger.addHandler(logging.StreamHandler(sys.stdout))

class News:
    """
        A class to represent a news.
    """
    def __init__(self, title, description, pubDate, link):
        """
            Initialize a news.
        """
        self.title = title
        self.description = description
        self.pubDate = pubDate
        self.link = link

    def __str__(self):
        """
            Return a string representation of a news.
        """
        return f"{self.title}: {self.description}"

class TagRemover(html.parser.HTMLParser):
    """
        A class to remove HTML tags from a string.
    """
    def __init__(self):
        """
            Initialize a tag remover.
        """
        super().__init__()
        self.text = ""

    def handle_data(self, data):
        """
            Handle data.
        """
        self.text += data

def tmp_file_name():
    """
        Return a temporary file name using $TMPDIR environment variable.
    """
    return os.environ.get("TMPDIR", "/tmp") + "/war-alert.txt"

def search_hash_in_file(hash):
    """
        Search a hash in a temporary file. Create a temporary file if it doesn't exist.
    """
    # Create a temporary file
    if not os.path.exists(tmp_file_name()):
        with open(tmp_file_name(), "w") as file:
            file.write("")

    with open(tmp_file_name(), "r") as file:
        for line in file:
            if line.startswith(hash):
                return True
    return False

def write_hash_to_file(hash):
    """
        Write a hash to a temporary file.
    """
    with open(tmp_file_name(), "a") as file:
        file.write(hash + "\n")

def remove_tags(text):
    """
        Remove HTML tags from a string.
    """
    parser = TagRemover()
    parser.feed(text)
    return parser.text

def get_rss_items(url):
    """
        Return a list of RSS items from a URL.
    """
    # Get the source of the RSS feed
    source = requests.get(url).text

    # Parse the RSS source in XML format
    root = xml.etree.ElementTree.fromstring(source)

    # Return a list of items
    return [News(
        item.find("title").text,
        remove_tags(item.find("description").text),
        item.find("pubDate").text,
        item.find("link").text,
    ) for item in root.findall("./channel/item")]

def openai_request(query):
    """
        Return a response from OpenAI API in a string format.
    """
    client = openai.OpenAI()
    completion = client.chat.completions.create(
        model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        messages=[
            {
                "role": "user",
                "content": query,
            }
        ],
        response_format={ "type": "json_object" }
    )
    return completion.choices[0].message.content

def pushover_notification(title, message):
    """
        Send a Pushover notification.
    """
    # Send a POST request
    response = requests.post("https://api.pushover.net:443/1/messages.json", data={
        "token": os.environ.get("PUSHOVER_TOKEN"),
        "user": os.environ.get("PUSHOVER_USER"),
        "title": title,
        "message": message,
        "priority": 1,
    })

    # Check the response
    if response.status_code != 200:
        logger.error(json.dumps({
            "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
            "status": response.status_code,
            "info": response.headers,
            "response": response.text,
        }, ensure_ascii=False))

def telegram_notification(title, message):
    """
    Send a message to a Telegram channel using the Telegram Bot API.
    """
    url = f"https://api.telegram.org/bot{os.environ.get('TELEGRAM_BOT_TOKEN')}/sendMessage"
    payload = {
        "chat_id": os.environ.get("TELEGRAM_CHANNEL_ID"),
        "text": f"{title}\n\n{message}",
    }
    response = requests.post(url, json=payload)

    # Check the response
    if response.status_code != 200:
        logger.error(json.dumps({
            "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
            "status": response.status_code,
            "response": response.text,
        }, ensure_ascii=False))

def calculate_md5_hash(text):
    """
        Calculate the MD5 hash of a text.
    """
    return hashlib.md5(text.encode('utf-8')).hexdigest()

def get_prompt(news):
    """
        Return the prompt.
    """
    with open(os.environ.get("PROMPT_FILE", "./prompt.txt"), "r") as file:
        return file.read().replace("<news>", news)

def process_news(news):
    """
        Process a news.
    """
    # Check if the news has already been processed
    hash = calculate_md5_hash(str(news))
    if search_hash_in_file(hash):
        return
    write_hash_to_file(hash)
    prompt = get_prompt(str(news))
    answer = openai_request(prompt)

    # Parse the JSON response
    parsed = json.loads(answer)

    # Validate the JSON response, result and justification must be present
    if "result" not in parsed or "justification" not in parsed:
        logger.error(json.dumps({
            "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
            "error": "result or justification not found",
            "title": news.title,
            "description": news.description,
            "pubDate": news.pubDate,
            "link": news.link,
        }, ensure_ascii=False))
        return

    if parsed["result"] == "no":
        logger.info(json.dumps({
            "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
            "result": parsed["result"],
            "justification": parsed["justification"],
            "title": news.title,
            "description": news.description,
            "pubDate": news.pubDate,
            "link": news.link,
        }, ensure_ascii=False))
        return

    # Print the result
    logger.warning(json.dumps({
        "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        "result": parsed["result"],
        "justification": parsed["justification"],
        "title": news.title,
        "description": news.description,
        "pubDate": news.pubDate,
        "link": news.link,
    }, ensure_ascii=False))

    if os.getenv("PUSHOVER_TOKEN") is not None:
        # Send a Pushover notification
        pushover_notification(
            f"War alert: {news.title}",
            f"{news.description}\n\n{parsed['justification']}\n\n{news.link}",
        )

    # Send a Telegram notification
    if os.getenv("TELEGRAM_BOT_TOKEN") is not None:
        telegram_notification(
            f"War alert: {news.title}",
            f"{news.description}\n\n{parsed['justification']}\n\n{news.link}",
        )

def signal_handler(sig, frame):
    """
        Handle the SIGKILL, SIGTERM and KeyboardInterrupt signals.
    """
    logger.warning(json.dumps({
        "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        "signal": signal.Signals(sig).name,
    }))
    sys.exit(0)

def usr1_handler(sig, frame):
    """
        Handle the SIGUSR1 signal.
    """
    logger.warning(json.dumps({
        "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        "signal": signal.Signals(sig).name,
    }))

    # Process the news
    process_news(News(
        "Everything is fine, it's just a test.",
        "We are testing the system. Please do not panic. Test time: " +
            time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        "System test"))

# Handle the SIGTERM, SIGINT and SIGUSR1 signals
signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGUSR1, usr1_handler)

if __name__ == "__main__":
    # Load the .env file
    dotenv.load_dotenv()

    # Infinite loop
    while True:
        # Process the RSS sources
        for url in os.environ.get("RSS_URLS", "").split(" "):
            # Log the RSS source
            logger.info(json.dumps({
                "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
                "url": url
            }))

            # Get the RSS items
            try:
                items = get_rss_items(url)
            except Exception as e:
                logger.error(json.dumps({
                    "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
                    "url": url,
                    "exception": str(e)
                }))
                continue

            # Process the news
            for news in items:
                try:
                    process_news(news)
                except Exception as e:
                    logger.error(json.dumps({
                        "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
                        "url": url,
                        "exception": str(e)
                    }))

        # Sleep for the specified delay
        time.sleep(int(os.environ.get("SLEEP_DELAY", 600)))
