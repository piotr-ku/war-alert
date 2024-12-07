#!/usr/bin/env python3

import dotenv
import hashlib
import http.client
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

def get_rss_source(url):
    """
        Return an RSS source in XML format.
    """
    return requests.get(url).text

def get_rss_items(rss_source):
    """
        Return a list of items containing titles and descriptions from an RSS source.
        It parses the RSS source in XML format and returns a list of items.
    """
    # Get the root element of the RSS source
    root = xml.etree.ElementTree.fromstring(rss_source)
    return [f"{item.find("title").text}: {item.find("description").text}" for item in root.findall("./channel/item")]

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
    # Create a connection
    conn = http.client.HTTPSConnection("api.pushover.net:443")

    # Send a POST request
    conn.request("POST", "/1/messages.json",
    urllib.parse.urlencode({
        "token": os.environ.get("PUSHOVER_TOKEN"),
        "user": os.environ.get("PUSHOVER_USER"),
        "title": title,
        "message": message,
        "priority": 1,
    }), { "Content-type": "application/x-www-form-urlencoded" })

    # Check the response
    response = conn.getresponse()
    if response.status != 200:
        logger.error(json.dumps({
            "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
            "status": response.status,
            "info": response.info,
            "response": response.read().decode("utf-8"),
        }, ensure_ascii=False))

    # Close the connection
    conn.close()

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
    hash = calculate_md5_hash(news)
    if search_hash_in_file(hash):
        return
    write_hash_to_file(hash)
    prompt = get_prompt(news)
    answer = openai_request(prompt)

    # Parse the JSON response
    parsed = json.loads(answer)

    # Validate the JSON response, result and justification must be present
    if "result" not in parsed or "justification" not in parsed:
        logger.error(json.dumps({
            "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
            "error": "result or justification not found",
            "news": news,
        }, ensure_ascii=False))
        return

    if parsed["result"] == "no":
        logger.info(json.dumps({
            "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
            "result": parsed["result"],
            "justification": parsed["justification"],
            "news": news,
        }, ensure_ascii=False))
        return

    # Print the result
    logger.warning(json.dumps({
        "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        "result": parsed["result"],
        "justification": parsed["justification"],
        "news": news
    }, ensure_ascii=False))

    # Send a Pushover notification
    pushover_notification("War alert", news + "\n\n" + parsed["justification"])

def signal_handler(sig, frame):
    """
        Handle the SIGKILL, SIGTERM and KeyboardInterrupt signals.
    """
    logger.warning(json.dumps({
        "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        "signal": signal.Signals(sig).name,
    }))
    sys.exit(0)

# Handle the SIGTERM and SIGINT signals
signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)

if __name__ == "__main__":
    # Load the .env file
    dotenv.load_dotenv()

    # Infinite loop
    while True:
        # Process the RSS sources
        for url in os.environ.get("RSS_URLS", "").split(","):
            # Log the RSS source
            logger.info(json.dumps({
                "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
                "url": url
            }))

            # Get the RSS source and extract the titles and descriptions
            source = get_rss_source(url)
            items = get_rss_items(source)

            # Process the news
            for news in items:
                process_news(news)

        # Sleep for the specified delay
        time.sleep(int(os.environ.get("SLEEP_DELAY", 600)))

