import json
import logging
import os
import time
from typing import Any

import requests

from processors.base import Content, Processor
from processors.openai import ProcessorOpenAI
from processors.unique import ProcessorUnique
from sources.base import Source

DEFAULT_BASE_URL = "https://api.twitterapi.io"
REQUEST_TIMEOUT = 30


class Tweet(Content):
    """
        A class to represent a tweet.
    """
    def __init__(self, title, description, pubDate, link):
        """
            Initialize a tweet.
        """
        self.title = title
        self.description = description
        self.pubDate = pubDate
        self.link = link

    def __str__(self) -> str:
        """
            Return a string representation of a tweet.
        """
        if self.description is None:
            return self.title
        if self.title is None:
            return self.description
        return f"{self.title}: {self.description}"


def _base_url() -> str:
    return os.environ.get("TWITTERAPI_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


def _usernames() -> list[str]:
    raw = os.environ.get("TWITTERAPI_USERNAMES", "")
    if raw is None or raw.strip() == "":
        return []
    return [username.lstrip("@") for username in raw.split() if username.strip()]


def _api_key() -> str:
    return os.environ.get("TWITTERAPI_KEY", "")


def _headers() -> dict[str, str]:
    return {"x-api-key": _api_key()}


def _log(logger: logging.Logger, payload: dict, level: int = logging.INFO) -> None:
    payload.setdefault("time", time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()))
    logger.log(level, json.dumps(payload, ensure_ascii=False))


def _author_title(author: dict[str, Any]) -> str:
    name = author.get("name") or author.get("userName") or "Unknown"
    username = author.get("userName") or "unknown"
    return f"{name} (@{username})"


def _prepare_tweet(raw: dict[str, Any], username: str, logger: logging.Logger) -> Tweet | None:
    text = raw.get("text")
    if text is None or not isinstance(text, str):
        _log(logger, {
            "source": "TwitterAPI",
            "msg": "Error parsing tweet item",
            "username": username,
            "reason": "missing text",
            "tweet_id": raw.get("id"),
        }, level=logging.ERROR)
        return None

    author = raw.get("author")
    if not isinstance(author, dict):
        _log(logger, {
            "source": "TwitterAPI",
            "msg": "Error parsing tweet item",
            "username": username,
            "reason": "missing author",
            "tweet_id": raw.get("id"),
        }, level=logging.ERROR)
        return None

    link = raw.get("url")
    if link is None or not isinstance(link, str):
        link = ""

    pub_date = raw.get("createdAt")
    if pub_date is None or not isinstance(pub_date, str):
        pub_date = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())

    return Tweet(
        _author_title(author),
        text,
        pub_date,
        link,
    )


class SourceTwitterAPI(Source):
    """
        A class to represent the twitterapi.io source.
    """
    def __init__(self, logger: logging.Logger):
        """
            Initialize the TwitterAPI source.
        """
        self.logger = logger
        self.base_url = _base_url()

    def processors(self) -> list[Processor]:
        """
            Return a list of processors.
        """
        return [ProcessorUnique, ProcessorOpenAI]

    def fetch(self, logger) -> list[Tweet]:
        """
            Return tweets from configured usernames (first page, up to 20 each).
        """
        usernames = _usernames()
        _log(self.logger, {
            "source": "TwitterAPI",
            "usernames": usernames,
            "base_url": self.base_url,
        })

        items: list[Tweet] = []
        for username in usernames:
            items.extend(self._fetch_username(username))

        _log(self.logger, {
            "source": "TwitterAPI",
            "msg": "TwitterAPI fetch complete",
            "usernames": len(usernames),
            "tweets": len(items),
        })
        return items

    def _fetch_username(self, username: str) -> list[Tweet]:
        url = f"{self.base_url}/twitter/user/last_tweets"
        params = {
            "userName": username,
            "includeReplies": "false",
        }

        try:
            response = requests.get(
                url,
                headers=_headers(),
                params=params,
                timeout=REQUEST_TIMEOUT,
            )
        except Exception as e:
            _log(self.logger, {
                "source": "TwitterAPI",
                "msg": "Error fetching tweets",
                "username": username,
                "exception": str(e),
            }, level=logging.ERROR)
            return []

        if response.status_code != 200:
            _log(self.logger, {
                "source": "TwitterAPI",
                "msg": "Error fetching tweets",
                "username": username,
                "status": response.status_code,
                "response": response.text,
            }, level=logging.ERROR)
            return []

        try:
            payload = response.json()
        except Exception as e:
            _log(self.logger, {
                "source": "TwitterAPI",
                "msg": "Error parsing tweets response",
                "username": username,
                "exception": str(e),
            }, level=logging.ERROR)
            return []

        if payload.get("status") == "error":
            _log(self.logger, {
                "source": "TwitterAPI",
                "msg": "Error fetching tweets",
                "username": username,
                "api_message": payload.get("message"),
            }, level=logging.ERROR)
            return []

        tweets = payload.get("tweets")
        if not isinstance(tweets, list):
            return []

        items: list[Tweet] = []
        for raw in tweets:
            if not isinstance(raw, dict):
                continue
            tweet = _prepare_tweet(raw, username, self.logger)
            if tweet is not None:
                items.append(tweet)
        return items
