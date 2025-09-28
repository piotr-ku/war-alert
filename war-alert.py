#!/usr/bin/env python3

import ai.openai
import dotenv
import hashlib
import json
import logging
import notifications.email
import notifications.telegram
import notifications.pushover
import os
import sources.rss
import signal
import sys
import time

# Create a logger and set stdout as a handler
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
logger.addHandler(logging.StreamHandler(sys.stdout))

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
    answer = ai.openai.query(prompt, logger)

    # Parse the JSON response
    try:
        parsed = json.loads(answer)
    except Exception as e:
        logger.error(json.dumps({
            "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
            "error": str(e),
            "title": news.title,
            "description": news.description,
            "pubDate": news.pubDate,
            "link": news.link,
        }, ensure_ascii=False))
        return

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
        notifications.pushover.notify(
            f"War alert: {news.title}",
            f"{parsed['justification']}\n\n{news.link}",
            logger
        )

    # Send a Telegram notification
    if os.getenv("TELEGRAM_BOT_TOKEN") is not None:
        notifications.telegram.notify(
            f"War alert: {news.title}",
            f"{parsed['justification']}\n\n{news.link}",
            logger
        )

    # Send an email notification
    if os.environ.get("EMAIL_TO") is not None:
        for email in os.getenv("EMAIL_TO", "").split(" "):
            notifications.email.notify(
                email,
                f"War alert: {news.title}",
                f"{parsed['justification']}\n\n{news.link}",
                logger
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
    process_news(sources.rss.News(
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

            # Validate the RSS source
            if url == "":
                continue

            # Get the RSS items
            items = sources.rss.get_items(url, logger)

            # Process the news
            for news in items:
                if news is None:
                    continue
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
