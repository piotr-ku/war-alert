import importlib.util
import json
import logging
import os
import sys
import unittest
from unittest.mock import Mock, patch

from processors.openai import ProcessorOpenAI
from processors.unique import ProcessorUnique
from sources.twitterapi import SourceTwitterAPI, Tweet


def load_war_alert():
    module_path = os.path.join(os.path.dirname(__file__), "..", "war-alert.py")
    spec = importlib.util.spec_from_file_location("war_alert", module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["war_alert"] = module
    spec.loader.exec_module(module)
    return module


def _tweet_payload(index: int, username: str = "DefenceU") -> dict:
    return {
        "id": str(index),
        "url": f"https://x.com/{username}/status/{index}",
        "text": f"tweet {index}",
        "createdAt": f"2026-01-{index:02d}T00:00:00 +0000 2026",
        "author": {
            "name": "Defence of Ukraine",
            "userName": username,
        },
    }


def _api_response(tweets: list[dict]) -> dict:
    return {
        "tweets": tweets,
        "has_next_page": len(tweets) >= 20,
        "next_cursor": "next-page",
        "status": "success",
        "message": "ok",
    }


class TestSourceTwitterAPI(unittest.TestCase):
    def setUp(self):
        self.env_keys = (
            "TWITTERAPI_KEY",
            "TWITTERAPI_USERNAMES",
            "TWITTERAPI_BASE_URL",
        )
        self.env_backup = {key: os.environ.get(key) for key in self.env_keys}
        os.environ["TWITTERAPI_KEY"] = "test-key"
        os.environ["TWITTERAPI_USERNAMES"] = "DefenceU"
        self.logger = logging.getLogger("test_twitterapi")

    def tearDown(self):
        for key, value in self.env_backup.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_fetch_returns_full_first_page(self):
        tweets = [_tweet_payload(index) for index in range(1, 21)]
        response = Mock()
        response.status_code = 200
        response.json.return_value = _api_response(tweets)

        with patch("sources.twitterapi.requests.get", return_value=response) as mock_get:
            result = SourceTwitterAPI(self.logger).fetch(self.logger)

        self.assertEqual(len(result), 20)
        mock_get.assert_called_once()
        call_kwargs = mock_get.call_args.kwargs
        self.assertEqual(call_kwargs["params"]["userName"], "DefenceU")
        self.assertEqual(call_kwargs["params"]["includeReplies"], "false")
        self.assertNotIn("cursor", call_kwargs["params"])

    def test_prepare_tweet_maps_fields(self):
        tweets = [_tweet_payload(1)]
        response = Mock()
        response.status_code = 200
        response.json.return_value = _api_response(tweets)

        with patch("sources.twitterapi.requests.get", return_value=response):
            result = SourceTwitterAPI(self.logger).fetch(self.logger)

        self.assertEqual(len(result), 1)
        tweet = result[0]
        self.assertIsInstance(tweet, Tweet)
        self.assertEqual(tweet.title, "Defence of Ukraine (@DefenceU)")
        self.assertEqual(tweet.description, "tweet 1")
        self.assertEqual(tweet.link, "https://x.com/DefenceU/status/1")
        self.assertEqual(tweet.pubDate, "2026-01-01T00:00:00 +0000 2026")
        self.assertEqual(str(tweet), "Defence of Ukraine (@DefenceU): tweet 1")

    def test_error_for_one_username_does_not_drop_other(self):
        good_response = Mock()
        good_response.status_code = 200
        good_response.json.return_value = _api_response([_tweet_payload(1, "GoodUser")])

        bad_response = Mock()
        bad_response.status_code = 400
        bad_response.text = "bad request"

        def side_effect(url, **kwargs):
            username = kwargs["params"]["userName"]
            if username == "BadUser":
                return bad_response
            return good_response

        os.environ["TWITTERAPI_USERNAMES"] = "BadUser GoodUser"

        with patch("sources.twitterapi.requests.get", side_effect=side_effect):
            result = SourceTwitterAPI(self.logger).fetch(self.logger)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].title, "Defence of Ukraine (@GoodUser)")

    def test_request_exception_returns_empty_for_username(self):
        with patch("sources.twitterapi.requests.get", side_effect=TimeoutError("timeout")):
            result = SourceTwitterAPI(self.logger).fetch(self.logger)

        self.assertEqual(result, [])

    def test_api_error_status_returns_empty_for_username(self):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "tweets": [],
            "has_next_page": False,
            "next_cursor": "",
            "status": "error",
            "message": "user not found",
        }

        with patch("sources.twitterapi.requests.get", return_value=response):
            result = SourceTwitterAPI(self.logger).fetch(self.logger)

        self.assertEqual(result, [])

    def test_missing_author_skips_item(self):
        payload = _tweet_payload(1)
        del payload["author"]
        response = Mock()
        response.status_code = 200
        response.json.return_value = _api_response([payload])

        with patch("sources.twitterapi.requests.get", return_value=response):
            result = SourceTwitterAPI(self.logger).fetch(self.logger)

        self.assertEqual(result, [])

    def test_processors_match_rss(self):
        source = SourceTwitterAPI(self.logger)
        self.assertEqual(source.processors(), [ProcessorUnique, ProcessorOpenAI])


class TestAllSourcesTwitterAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.war_alert = load_war_alert()

    def setUp(self):
        self.env_keys = (
            "TWITTERAPI_KEY",
            "TWITTERAPI_USERNAMES",
            "RSS_URLS",
            "ALERTSUA_TOKEN",
            "FAA_NMS_CLIENT_ID",
            "FAA_NMS_CLIENT_SECRET",
        )
        self.env_backup = {key: os.environ.get(key) for key in self.env_keys}
        for key in self.env_keys:
            os.environ.pop(key, None)
        self.logger = logging.getLogger("test_all_sources_twitterapi")

    def tearDown(self):
        for key, value in self.env_backup.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_all_sources_adds_twitterapi_when_configured(self):
        os.environ["TWITTERAPI_KEY"] = "test-key"
        os.environ["TWITTERAPI_USERNAMES"] = "DefenceU MON_GOV_PL"

        sources = self.war_alert.all_sources(self.logger)

        self.assertEqual(len(sources), 1)
        self.assertIsInstance(sources[0], SourceTwitterAPI)

    def test_all_sources_skips_twitterapi_without_usernames(self):
        os.environ["TWITTERAPI_KEY"] = "test-key"

        sources = self.war_alert.all_sources(self.logger)

        self.assertEqual(sources, [])

    def test_all_sources_skips_twitterapi_without_key(self):
        os.environ["TWITTERAPI_USERNAMES"] = "DefenceU"

        sources = self.war_alert.all_sources(self.logger)

        self.assertEqual(sources, [])


if __name__ == "__main__":
    unittest.main()
