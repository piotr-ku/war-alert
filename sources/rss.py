import json
import html.parser
import requests
import time
import xml.etree.ElementTree

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

def get_items(url, logger):
    """
        Return a list of RSS items from a URL.
    """
    # Get the source of the RSS feed
    source = requests.get(url).text

    # Parse the RSS source in XML format
    try:
        root = xml.etree.ElementTree.fromstring(source)
    except Exception as e:
        logger.error(json.dumps({
            "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
            "msg": "Error parsing RSS source",
            "exception": str(e),
        }))
        return []

    # Return a list of items
    return [get_item(item, logger) for item in root.findall("./channel/item")]

def get_item(element, logger):
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
        logger.error(json.dumps({
            "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
            "msg": "Error parsing RSS item",
            "exception": str(e),
        }))
        return None
