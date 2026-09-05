import base64
import logging
import os
import unittest
from unittest.mock import MagicMock, patch

import config
from notifiers.ntfy import NotifierNtfy
from sources.rss import News


class TestNotifierNtfy(unittest.TestCase):
    def setUp(self):
        self.logger = logging.getLogger("test_ntfy")
        self.content = News(
            "War Alert",
            "Airspace closure near Warsaw",
            "2026-04-09T10:00:00",
            "https://example.com/notam",
        )

    def tearDown(self):
        config.reset()

    @patch.dict(os.environ, {
        "NTFY_TOPIC": "war-alerts-secret",
        "NTFY_TOKEN": "tk_test_token",
    }, clear=False)
    @patch("notifiers.ntfy.requests.post")
    def test_successful_send_includes_headers(self, mock_post):
        config.apply({
            "ntfy": {
                "tags": ["warning", "skull"],
            },
        })
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        result = NotifierNtfy().notify(self.content, self.logger)

        self.assertTrue(result)
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], "https://ntfy.sh/war-alerts-secret")
        self.assertEqual(
            kwargs["data"],
            "Airspace closure near Warsaw\n\nhttps://example.com/notam",
        )
        headers = kwargs["headers"]
        self.assertEqual(headers["Title"], "War Alert")
        self.assertEqual(headers["Priority"], "high")
        self.assertEqual(headers["Click"], "https://example.com/notam")
        self.assertEqual(headers["Tags"], "warning,skull")
        self.assertEqual(
            headers["Authorization"],
            "Bearer tk_test_token",
        )

    @patch.dict(os.environ, {"NTFY_TOPIC": "war-alerts-secret"}, clear=False)
    @patch("notifiers.ntfy.requests.post")
    def test_missing_token_omits_authorization(self, mock_post):
        env = os.environ
        env.pop("NTFY_TOKEN", None)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        result = NotifierNtfy().notify(self.content, self.logger)

        self.assertTrue(result)
        headers = mock_post.call_args.kwargs["headers"]
        self.assertNotIn("Authorization", headers)

    @patch.dict(os.environ, {"NTFY_TOPIC": "war-alerts-secret"}, clear=False)
    @patch("notifiers.ntfy.requests.post")
    def test_non_200_returns_false(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.headers = {}
        mock_response.text = "rate limited"
        mock_post.return_value = mock_response

        result = NotifierNtfy().notify(self.content, self.logger)

        self.assertFalse(result)

    @patch.dict(os.environ, {"NTFY_TOPIC": "war-alerts-secret"}, clear=False)
    @patch("notifiers.ntfy.requests.post")
    def test_unicode_title_is_rfc2047_encoded(self, mock_post):
        title = (
            "Ministeriö tuomitsee Venäjän vaarallisen toiminnan "
            "– Venäjä kehotti aiemmin Suomea välttämään "
            "”provokaatioita”"
        )
        description = (
            "Ulkoministeriö puhutteli Venäjän suurlähettilästä "
            "keskiviikkona. Kuznetsov käytti tilaisuuden esittämällä "
            "Suomelle ”toiveen”."
        )
        content = News(
            title,
            description,
            "Fri, 04 Sep 2026 15:29:08 +0300",
            "https://yle.fi/a/74-20244544?origin=rss",
        )
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        result = NotifierNtfy().notify(content, self.logger)

        self.assertTrue(result)
        headers = mock_post.call_args.kwargs["headers"]
        encoded_title = headers["Title"]
        self.assertTrue(encoded_title.startswith("=?UTF-8?B?"))
        self.assertTrue(encoded_title.endswith("?="))
        encoded_title.encode("latin-1")
        decoded = base64.b64decode(
            encoded_title[len("=?UTF-8?B?"):-len("?=")],
        ).decode("utf-8")
        self.assertEqual(decoded, title)
        self.assertIn(description, mock_post.call_args.kwargs["data"])


if __name__ == "__main__":
    unittest.main()
