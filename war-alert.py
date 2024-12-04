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

prompt1 = """
Czy poniższy news:
"""

prompt2 = """
Opisuje którykolwiek z poniższych scenariuszy?

- ewakuacja dowolnego konsulatu lub ambasady w krajach NATO zagrożonych konfliktem
- zalecenie konsulatu lub ambasady dowolnego kraju, aby jego obywatele opuścili dowolny kraj NATO zagrożony konfliktem
- opuszczenie przez rosyjskich dyplomatów dowolnego kraju NATO zagrożonego konfliktem
- podejrzenie niszczenia dokumentów w rosyjskiej ambasadzie lub konsulacie w dowolnym kraju NATO zagrożonym konfliktem
- debata na temat ogłoszenia mobilizacji w Polsce
- debata na temat wprowadzenia w Polsce stanu wojennego lub jakiegokolwiek innego kraju NATO
- ogłoszenie mobilizacji w Polsce
- ogłoszenie stanu wojennego w Polsce lub dowolnym kraju NATO
- atak rakietowy na dowolny kraj NATO
- użycie broni nuklearnej gdziekolwiek na świecie
- informacje o koncentracji wojsk w pobliżu granicy dowolnego kraju NATO
- informacje od służb jakiegokolwiek kraju NATO o planowanej poważnej prowokacji ze strony Rosji
- informacje o poważnej prowokacji ze strony Rosji lub NATO
- zamknięcie granicy z Polską przez którekolwiek z państw NATO
- wprowadzenie kontroli na granicach z Polską przez co najmniej jeszcze jedno państwo NATO
- orędzie Putina, które może być intepretowane jako uzasadnienie przed narodem rosyjskim agresji wobec państw NATO

Przyjmij, że kraje NATO zagrożone konfliktem to: Polska, Szwecja, Finlandia, Litwa, Łotwa, Estonia.

Odpowiedz w formacie JSON: {"result": "<yes|no>", "reason": "<short reason in Polish>"}
"""

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

def process_news(description):
    """
        Process a news.
    """
    # Check if the description has already been processed
    hash = calculate_md5_hash(description)
    if search_hash_in_file(hash):
        return
    write_hash_to_file(hash)
    answer = openai_request(prompt1 + "\n\n" + description + "\n\n" + prompt2)

    # Parse the JSON response
    parsed = json.loads(answer)
    if parsed["result"] == "no":
        logger.info(json.dumps({
            "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
            "result": parsed["result"],
            "reason": parsed["reason"],
            "description": description
        }, ensure_ascii=False))
        return

    # Print the result
    logger.warning(json.dumps({
        "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        "result": parsed["result"],
        "reason": parsed["reason"],
        "description": description
    }, ensure_ascii=False))

    # Send a Pushover notification
    pushover_notification("War alert", description + "\n\n" + parsed["reason"])

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

            # Process the descriptions
            for description in items:
                process_news(description)

        # Sleep for 10 minutes
        time.sleep(os.environ.get("SLEEP_DELAY", 600))

