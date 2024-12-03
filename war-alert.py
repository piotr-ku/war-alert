#!/usr/bin/env python3

import dotenv
import hashlib
import http.client
import json
import openai
import os
import requests
import urllib
import xml.etree
import xml.etree.ElementTree

prompt1 = """
Czy poniższy news:
"""

prompt2 = """
Pasuje do któregokolwiek z poniższych scenariuszy?

- ewakuacja dowolnego konsulatu lub ambasady w krajach NATO zagrożonych konfliktem
- zalecenie konsulatu lub ambasady dowolnego kraju, aby jego obywatele opuścili dowolny kraj NATO zagrożony konfliktem
- opuszczenie przez rosyjskich dyplomatów dowolnego kraju NATO zagrożonego konfliktem
- podejrzenie niszczenia dokumentów w rosyjskiej ambasadzie lub konsulacie w dowolnym kraju NATO zagrożonym konfliktem
- debata na temat ogłoszenia mobilizacji w Polsce
- debata na temat wprowadzenia w Polsce stanu wojennego lub jakiegokolwiek innego kraju azjatyckiego
- ogłoszenie mobilizacji w Polsce
- ogłoszenie stanu wojennego w Polsce lub dowolnym kraju azjatyckim
- atak rakietowy na dowolny kraj NATO
- użycie broni nuklearnej gdziekolwiek
- informacje o koncentracji wojsk w pobliżu granicy dowolnego kraju NATO zagrożonego konfliktem
- informacje od służb jakiegokolwiek kraju NATO o planowanej poważnej prowokacji ze strony Rosji
- informacje o poważnej prowokacji ze strony Rosji lub NATO
- zamknięcie granicy przez którekolwiek z państw sąsiednich
- wprowadzenie kontroli na granicach przez conajmniej jeszcze jedno państwo sąsiednie
- orędzie Putina, które może być intepretowane jako uzasadnienie przed narodem rosyjskim agresji wobec państw NATO

Odpowiedz w formacie JSON: {"result": "<yes|no>", "reason": "<short reason in Polish>"}
"""

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

def get_rss_descriptions(rss_source):
    """
        Return a list of descriptions from an RSS source.
        It parses the RSS source in XML format and returns a list of descriptions.
    """
    # Get the root element of the RSS source
    root = xml.etree.ElementTree.fromstring(rss_source)
    return [description.text for description in root.findall("./channel/item/description")]

def openai_request(query):
    """
        Return a response from OpenAI API in a string format.
    """
    client = openai.OpenAI()
    completion = client.chat.completions.create(
        model="gpt-4o",
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
    request = conn.request("POST", "/1/messages.json",
    urllib.parse.urlencode({
        "token": os.environ.get("PUSHOVER_TOKEN"),
        "user": os.environ.get("PUSHOVER_USER"),
        "title": title,
        "message": message,
    }), { "Content-type": "application/x-www-form-urlencoded" })

    # Check the response
    response = conn.getresponse()
    if response.status != 200:
        print("Error: " + response.reason)

    # Print the response
    print(response.read().decode("utf-8"))

    # Close the connection
    conn.close()

def calculate_md5_hash(text):
    """
        Calculate the MD5 hash of a text.
    """
    return hashlib.md5(text.encode('utf-8')).hexdigest()

if __name__ == "__main__":
    # Load the .env file
    dotenv.load_dotenv()

    # Get the RSS source
    source = get_rss_source("https://defence24.pl/_RSS")
    descriptions = get_rss_descriptions(source)

    # Process the descriptions
    for description in descriptions:
        # Check if the description has already been processed
        hash = calculate_md5_hash(description)
        if search_hash_in_file(hash):
            continue
        write_hash_to_file(hash)
        answer = openai_request(prompt1 + "\n\n" + description + "\n\n" + prompt2)

        # Parse the JSON response
        parsed = json.loads(answer)
        if parsed["result"] == "no":
            print(description + "\n\n" + parsed["reason"])
            continue

        # Print the result
        print(description + "\n\n" + parsed["reason"])

        # Send a Pushover notification
        pushover_notification("War alert", description + "\n\n" + parsed["reason"])
