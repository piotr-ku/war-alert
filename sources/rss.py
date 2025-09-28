import json
import html.parser
import logging
import requests
import time
import xml.etree.ElementTree
from sources.base import Source
from processors.base import Content, Processor
from processors.unique import ProcessorUnique
from processors.openai import ProcessorOpenAI

class News(Content):
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
        if self.description is None:
            return self.title
        if self.title is None:
            return self.description
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

def remove_tags(text):
    """
        Remove HTML tags from a string.
    """
    if text is None:
        return ""
    parser = TagRemover()
    parser.feed(text)
    return parser.text

class SourceRSS(Source):
    """
        A class to represent an RSS source.
    """
    def __init__(self, url: str, logger: logging.Logger):
        """
            Initialize an RSS source.
        """
        self.url = url
        self.logger = logger

    def processors(self) -> list[Processor]:
        """
            Return a list of processors.
        """
        return [ProcessorUnique, ProcessorOpenAI]

    def fetch(self, logger) -> list[News]:
        """
            Return a list of RSS items from a URL.
        """
        # Log the URL
        self.logger.info(json.dumps({
            "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
            "source": "RSS",
            "url": self.url,
        }))

        # Get the source of the RSS feed
        try:
            source = requests.get(self.url).text
        except Exception as e:
            self.logger.error(json.dumps({
                "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
                "url": self.url,
                "exception": str(e),
            }))
            return []

        # Parse the RSS source in XML format
        try:
            root = xml.etree.ElementTree.fromstring(source)
        except Exception as e:
            self.logger.error(json.dumps({
                "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
                "url": self.url,
                "msg": "Error parsing RSS source",
                "exception": str(e),
            }))
            return []

        # Return a list of items
        return [self.get_item(item) \
            for item in root.findall("./channel/item")]

    def get_item(self, element) -> News:
        """
            Return an RSS item from an XML element.
        """
        try:
            return News(
                element.find("title").text,
                remove_tags(element.find("description").text),
                element.find("pubDate").text,
                element.find("link").text,
            )
        except Exception as e:
            self.logger.error(json.dumps({
                "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
                "url": self.url,
                "msg": "Error parsing RSS item",
                "exception": str(e),
            }))
            return None
