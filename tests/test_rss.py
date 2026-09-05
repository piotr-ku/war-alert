import json
import logging
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import Mock, patch

from sources.rss import News, SourceRSS


class RecordingHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)

    def payloads(self, level=None):
        result = []
        for record in self.records:
            if level is not None and record.levelno != level:
                continue
            result.append(json.loads(record.getMessage()))
        return result


def _item_xml(
    title=None,
    description=None,
    pub_date=None,
    link=None,
) -> str:
    parts = ["<item>"]
    if title is not None:
        parts.append(f"<title>{title}</title>")
    if description is not None:
        parts.append(f"<description>{description}</description>")
    if pub_date is not None:
        parts.append(f"<pubDate>{pub_date}</pubDate>")
    if link is not None:
        parts.append(f"<link>{link}</link>")
    parts.append("</item>")
    return "".join(parts)


def _element(xml: str):
    return ET.fromstring(xml)


def _feed(*items: str) -> str:
    return (
        '<?xml version="1.0"?>'
        "<rss><channel>"
        f"{''.join(items)}"
        "</channel></rss>"
    )


class TestNewsStr(unittest.TestCase):
    def test_title_and_description(self):
        news = News("Title", "Body", "2026-01-01", "http://example.com")
        self.assertEqual(str(news), "Title: Body")

    def test_title_only(self):
        news = News("Title", "", "2026-01-01", "http://example.com")
        self.assertEqual(str(news), "Title")

    def test_description_only(self):
        news = News("", "Body", "2026-01-01", "http://example.com")
        self.assertEqual(str(news), "Body")


class TestSourceRSSGetItem(unittest.TestCase):
    def setUp(self):
        self.handler = RecordingHandler()
        self.logger = logging.getLogger("test_rss")
        self.logger.handlers = [self.handler]
        self.logger.setLevel(logging.DEBUG)
        self.logger.propagate = False
        self.source = SourceRSS("https://example.com/feed.rss", self.logger)

    def test_full_item(self):
        element = _element(_item_xml(
            title="Headline",
            description="Summary",
            pub_date="Sat, 05 Sep 2026 16:58:30 +0300",
            link="https://example.com/a",
        ))
        news = self.source.get_item(element)

        self.assertIsNotNone(news)
        self.assertEqual(news.title, "Headline")
        self.assertEqual(news.description, "Summary")
        self.assertEqual(
            news.pubDate,
            "Sat, 05 Sep 2026 16:58:30 +0300",
        )
        self.assertEqual(news.link, "https://example.com/a")
        self.assertEqual(self.handler.payloads(logging.ERROR), [])

    def test_missing_description_keeps_item(self):
        element = _element(_item_xml(
            title="US destroyed three Iranian tankers",
            pub_date="Sat, 05 Sep 2026 16:58:30 +0300",
            link="https://yle.fi/a/74-20244761?origin=rss",
        ))
        news = self.source.get_item(element)

        self.assertIsNotNone(news)
        self.assertEqual(news.title, "US destroyed three Iranian tankers")
        self.assertEqual(news.description, "")
        self.assertEqual(
            news.pubDate,
            "Sat, 05 Sep 2026 16:58:30 +0300",
        )
        self.assertEqual(
            news.link,
            "https://yle.fi/a/74-20244761?origin=rss",
        )
        self.assertEqual(str(news), "US destroyed three Iranian tankers")
        self.assertEqual(self.handler.payloads(logging.ERROR), [])

    def test_strips_html_in_description(self):
        element = _element(_item_xml(
            title="Headline",
            description="&lt;p&gt;Summary&lt;/p&gt;",
            pub_date="Sat, 05 Sep 2026 16:58:30 +0300",
            link="https://example.com/a",
        ))
        news = self.source.get_item(element)

        self.assertEqual(news.description, "Summary")

    @patch(
        "sources.rss.time.strftime",
        return_value="2026-09-05T17:00:00",
    )
    def test_missing_pubdate_and_link_use_defaults(self, _strftime):
        element = _element(_item_xml(
            title="Headline",
            description="Summary",
        ))
        news = self.source.get_item(element)

        self.assertIsNotNone(news)
        self.assertEqual(news.pubDate, "2026-09-05T17:00:00")
        self.assertEqual(news.link, "")
        self.assertEqual(self.handler.payloads(logging.ERROR), [])

    def test_description_only_keeps_item(self):
        element = _element(_item_xml(
            description="Summary only",
            pub_date="Sat, 05 Sep 2026 16:58:30 +0300",
        ))
        news = self.source.get_item(element)

        self.assertIsNotNone(news)
        self.assertEqual(news.title, "")
        self.assertEqual(news.description, "Summary only")
        self.assertEqual(str(news), "Summary only")
        self.assertEqual(self.handler.payloads(logging.ERROR), [])

    def test_missing_title_and_description_skips_item(self):
        element = _element(_item_xml(
            pub_date="Sat, 05 Sep 2026 16:58:30 +0300",
            link="https://example.com/a",
        ))
        news = self.source.get_item(element)

        self.assertIsNone(news)
        errors = self.handler.payloads(logging.ERROR)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]["msg"], "Error parsing RSS item")
        self.assertEqual(
            errors[0]["reason"],
            "missing title and description",
        )


class TestSourceRSSFetch(unittest.TestCase):
    def setUp(self):
        self.handler = RecordingHandler()
        self.logger = logging.getLogger("test_rss_fetch")
        self.logger.handlers = [self.handler]
        self.logger.setLevel(logging.DEBUG)
        self.logger.propagate = False
        self.source = SourceRSS("https://example.com/feed.rss", self.logger)

    def test_fetch_keeps_partial_items_and_skips_empty(self):
        feed = _feed(
            _item_xml(
                title="With description",
                description="Body",
                pub_date="Sat, 05 Sep 2026 10:00:00 +0300",
                link="https://example.com/1",
            ),
            _item_xml(
                title="Title only",
                pub_date="Sat, 05 Sep 2026 16:58:30 +0300",
                link="https://example.com/2",
            ),
            _item_xml(link="https://example.com/3"),
        )
        response = Mock()
        response.text = feed

        with patch("sources.rss.requests.get", return_value=response):
            result = self.source.fetch(self.logger)

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].title, "With description")
        self.assertEqual(result[1].title, "Title only")
        self.assertEqual(result[1].description, "")
        errors = self.handler.payloads(logging.ERROR)
        self.assertEqual(len(errors), 1)
        self.assertEqual(
            errors[0]["reason"],
            "missing title and description",
        )

    def test_fetch_request_error_returns_empty(self):
        with patch(
            "sources.rss.requests.get",
            side_effect=TimeoutError("timeout"),
        ):
            result = self.source.fetch(self.logger)

        self.assertEqual(result, [])

    def test_fetch_invalid_xml_returns_empty(self):
        response = Mock()
        response.text = "not xml"

        with patch("sources.rss.requests.get", return_value=response):
            result = self.source.fetch(self.logger)

        self.assertEqual(result, [])
        errors = self.handler.payloads(logging.ERROR)
        self.assertEqual(errors[0]["msg"], "Error parsing RSS source")


if __name__ == "__main__":
    unittest.main()
