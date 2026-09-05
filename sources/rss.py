"""
    RSS feed source for war-alert.

    Environment variables:
        RSS_URLS — space-separated feed URLs. One SourceRSS per URL.

    Processors: news_processors() — ProcessorUnique then LLM classification.
"""

import json
import html.parser
import logging
import requests
import time
import xml.etree.ElementTree
from sources.base import Source
from processors.base import Content, Processor
from processors.classify import news_processors

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
        title = self.title or ""
        description = self.description or ""
        # Use whichever field is present when the other is empty
        if description == "":
            return title
        if title == "":
            return description
        return f"{title}: {description}"

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

def _child_text(element, tag: str) -> str | None:
    """
        Return stripped text of a child tag, or None if missing.
    """
    child = element.find(tag)
    if child is None or child.text is None:
        return None
    text = child.text.strip()
    return text or None

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
        return news_processors()

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

        # Parse each item; skip entries with no usable text
        items = []
        for item in root.findall("./channel/item"):
            news = self.get_item(item)
            if news is not None:
                items.append(news)
        return items

    def get_item(self, element) -> News | None:
        """
            Return an RSS item from an XML element.
        """
        try:
            # RSS 2.0 fields are optional; missing tags are normal
            title = _child_text(element, "title") or ""
            description = remove_tags(
                _child_text(element, "description"),
            )
            pub_date = _child_text(element, "pubDate")
            link = _child_text(element, "link") or ""

            # Need title or description to classify the item
            if title == "" and description == "":
                self.logger.error(json.dumps({
                    "time": time.strftime(
                        "%Y-%m-%dT%H:%M:%S",
                        time.localtime(),
                    ),
                    "url": self.url,
                    "msg": "Error parsing RSS item",
                    "reason": "missing title and description",
                }))
                return None

            # Default pubDate when the feed omits it
            if pub_date is None:
                pub_date = time.strftime(
                    "%Y-%m-%dT%H:%M:%S",
                    time.localtime(),
                )

            return News(title, description, pub_date, link)
        except Exception as e:
            self.logger.error(json.dumps({
                "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
                "url": self.url,
                "msg": "Error parsing RSS item",
                "exception": str(e),
            }))
            return None
