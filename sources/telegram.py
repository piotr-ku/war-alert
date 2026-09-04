"""
    Telegram channel source for war-alert (Telethon user client).
"""

import json
import logging
import os
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from telethon.errors import SecurityError
from telethon.sync import TelegramClient
from telethon.sessions import StringSession

from processors.base import Content, Processor
from processors.classify import news_processors
from sources.base import Source

DEFAULT_CHANNELS_FILE = "./telegram.yaml"
DEFAULT_SESSION_FILE = "telegram.session"
DEFAULT_CHANNEL_LIMIT = 20

_logged_source_config = False


@dataclass(frozen=True)
class ChannelConfig:
    username: str
    limit: int
    filters: list[re.Pattern[str]] | None


class TelegramPost(Content):
    """
        A class to represent a Telegram channel post.
    """
    def __init__(self, title: str, description: str, pubDate: str, link: str):
        self.title = title
        self.description = description
        self.pubDate = pubDate
        self.link = link

    def __str__(self) -> str:
        if self.description is None:
            return self.title
        if self.title is None:
            return self.description
        return f"{self.title}: {self.description}"


def _log(
    logger: logging.Logger,
    payload: dict,
    level: int = logging.INFO,
) -> None:
    payload.setdefault("source", "Telegram")
    payload.setdefault(
        "time",
        time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
    )
    logger.log(level, json.dumps(payload, ensure_ascii=False))


def _api_id() -> int | None:
    raw = os.environ.get("TELEGRAM_API_ID", "").strip()
    if raw == "":
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _api_hash() -> str:
    return os.environ.get("TELEGRAM_API_HASH", "").strip()


def _channels_file() -> str:
    return os.environ.get(
        "TELEGRAM_CHANNELS_FILE",
        DEFAULT_CHANNELS_FILE,
    ).strip()


def _session_file() -> str:
    return os.environ.get(
        "TELEGRAM_SESSION_FILE",
        DEFAULT_SESSION_FILE,
    ).strip()


def _session_string() -> str:
    return os.environ.get("TELEGRAM_SESSION_STRING", "").strip()


def telegram_credentials_configured() -> bool:
    """
        Return True when TELEGRAM_API_ID and TELEGRAM_API_HASH are set.
    """
    return _api_id() is not None and _api_hash() != ""


def _compile_filters(
    username: str,
    patterns: list[str],
    logger: logging.Logger,
) -> list[re.Pattern[str]]:
    compiled: list[re.Pattern[str]] = []
    for index, pattern in enumerate(patterns):
        if not isinstance(pattern, str) or pattern.strip() == "":
            continue
        try:
            compiled.append(re.compile(pattern))
        except re.error as exc:
            _log(logger, {
                "msg": "Invalid Telegram channel filter regex",
                "username": username,
                "pattern_index": index,
                "pattern": pattern,
                "exception": str(exc),
            }, level=logging.ERROR)
    return compiled


def load_channel_configs(logger: logging.Logger) -> list[ChannelConfig]:
    """
        Load and validate channel configs from the YAML channels file.
    """
    path = Path(_channels_file())
    if not path.is_file():
        _log(logger, {
            "msg": "Telegram channels file not found",
            "path": str(path),
        }, level=logging.ERROR)
        return []

    # Load YAML from disk
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle)
    except Exception as exc:
        _log(logger, {
            "msg": "Error loading Telegram channels file",
            "path": str(path),
            "exception": str(exc),
        }, level=logging.ERROR)
        return []

    if not isinstance(payload, dict):
        _log(logger, {
            "msg": "Telegram channels file must contain a mapping",
            "path": str(path),
        }, level=logging.ERROR)
        return []

    raw_channels = payload.get("channels")
    if not isinstance(raw_channels, list):
        _log(logger, {
            "msg": "Telegram channels file must contain a channels list",
            "path": str(path),
        }, level=logging.ERROR)
        return []

    channels: list[ChannelConfig] = []
    for entry in raw_channels:
        if not isinstance(entry, dict):
            continue

        username = entry.get("username")
        if not isinstance(username, str) or username.strip() == "":
            _log(logger, {
                "msg": "Skipping Telegram channel without username",
            }, level=logging.ERROR)
            continue

        limit = entry.get("limit", DEFAULT_CHANNEL_LIMIT)
        if not isinstance(limit, int) or limit < 1:
            limit = DEFAULT_CHANNEL_LIMIT

        raw_filters = entry.get("filters", [])
        if raw_filters is None:
            raw_filters = []
        if not isinstance(raw_filters, list):
            _log(logger, {
                "msg": "Skipping Telegram channel with invalid filters",
                "username": username,
            }, level=logging.ERROR)
            continue

        filters = _compile_filters(username, raw_filters, logger)
        # None = pass all; [] = drop all; list = OR-match regexes
        if raw_filters and not filters:
            _log(logger, {
                "msg": (
                    "Telegram channel has no valid filters; "
                    "all posts will be dropped"
                ),
                "username": username,
            }, level=logging.ERROR)
            filter_patterns: list[re.Pattern[str]] | None = []
        elif not raw_filters:
            filter_patterns = None
        else:
            filter_patterns = filters

        channels.append(ChannelConfig(
            username=username.lstrip("@"),
            limit=limit,
            filters=filter_patterns,
        ))

    return channels


def matches_filters(
    text: str,
    filters: list[re.Pattern[str]] | None,
) -> bool:
    """
        Return True when text matches channel filter rules.
    """
    if filters is None:
        return True
    if not filters:
        return False
    return any(pattern.search(text) for pattern in filters)


def _message_text(message: Any) -> str | None:
    text = getattr(message, "message", None)
    if isinstance(text, str) and text.strip() != "":
        return text
    return None


def _message_date(message: Any) -> str:
    message_date = getattr(message, "date", None)
    if message_date is None:
        return time.strftime(
            "%Y-%m-%dT%H:%M:%S",
            time.localtime(),
        )
    return message_date.strftime("%Y-%m-%dT%H:%M:%S")


def _channel_title(entity: Any, username: str) -> str:
    title = getattr(entity, "title", None)
    if isinstance(title, str) and title.strip() != "":
        return f"{title} (@{username})"
    return f"@{username}"


def _prepare_post(
    message: Any,
    entity: Any,
    username: str,
    logger: logging.Logger,
) -> TelegramPost | None:
    text = _message_text(message)
    if text is None:
        return None

    message_id = getattr(message, "id", None)
    if message_id is None:
        _log(logger, {
            "msg": "Error parsing Telegram post",
            "username": username,
            "reason": "missing id",
        }, level=logging.ERROR)
        return None

    return TelegramPost(
        _channel_title(entity, username),
        text,
        _message_date(message),
        f"https://t.me/{username}/{message_id}",
    )


def telegram_session_locked_hint() -> str:
    return (
        "telegram.session is locked by another process. "
        "Stop war-alert before logging in: docker compose stop war-alert"
    )


def telegram_session_out_of_sync_hint() -> str:
    return (
        "Telegram session is out of sync. Stop war-alert, delete "
        "telegram.session and telegram.session-journal, then run "
        "python3 telegram_login.py and restart war-alert."
    )


def is_session_locked_error(exc: BaseException) -> bool:
    if isinstance(exc, sqlite3.OperationalError):
        return "locked" in str(exc).lower()
    return "database is locked" in str(exc).lower()


def build_telegram_client() -> TelegramClient:
    """
        Build a Telethon client from env session string or file.
    """
    api_id = _api_id()
    if api_id is None:
        raise RuntimeError("TELEGRAM_API_ID is not configured")

    api_hash = _api_hash()
    if api_hash == "":
        raise RuntimeError("TELEGRAM_API_HASH is not configured")

    session_string = _session_string()
    if session_string != "":
        session = StringSession(session_string)
    else:
        session = _session_file()

    return TelegramClient(session, api_id, api_hash)


def authorize_telegram_client(
    client: TelegramClient,
    phone: str | None = None,
) -> None:
    """
        Connect and authorize the Telethon user session if needed.
    """
    if not client.is_connected():
        client.connect()

    if client.is_user_authorized():
        return

    if phone:
        client.start(phone=phone)
    else:
        client.start()


def disconnect_telegram_client(client: TelegramClient | None) -> None:
    """
        Disconnect a Telethon client, ignoring errors.
    """
    if client is None:
        return
    try:
        if client.is_connected():
            client.disconnect()
    except Exception:
        pass


def connect_telegram_client(logger: logging.Logger) -> TelegramClient | None:
    """
        Connect an authorized Telethon client or log the failure.
    """
    if not telegram_credentials_configured():
        return None

    try:
        client = build_telegram_client()
        client.connect()
        if not client.is_user_authorized():
            _log(logger, {
                "msg": (
                    "Telegram user session is not authorized; "
                    "run telegram_login.py"
                ),
            }, level=logging.ERROR)
            disconnect_telegram_client(client)
            return None
        return client
    except Exception as exc:
        # SQLite lock means war-alert still holds the session file
        if is_session_locked_error(exc):
            _log(logger, {
                "msg": "Telegram session file is locked",
                "hint": telegram_session_locked_hint(),
                "exception": str(exc),
            }, level=logging.ERROR)
        else:
            _log(logger, {
                "msg": "Error connecting Telegram client",
                "exception": str(exc),
            }, level=logging.ERROR)
        return None


def reset_telegram_client() -> None:
    """Kept for tests; connections are no longer pooled."""
    return None


class SourceTelegram(Source):
    """
        A class to represent Telegram channel sources (Telethon user client).
    """
    def __init__(self, logger: logging.Logger):
        """
            Initialize the Telegram source from channel configs.
        """
        self.logger = logger
        self.channels = load_channel_configs(logger)

    def processors(self) -> list[Processor]:
        """
            Return a list of processors.
        """
        return news_processors()

    def fetch(self, logger) -> list[TelegramPost]:
        """
            Fetch recent posts from all configured Telegram channels.
        """
        global _logged_source_config

        if not self.channels:
            return []

        # Log channel config once per process
        if not _logged_source_config:
            _log(self.logger, {
                "msg": "Telegram source configured",
                "channels_file": _channels_file(),
                "channels": [
                    {
                        "username": channel.username,
                        "limit": channel.limit,
                        "filters": (
                            "all"
                            if channel.filters is None
                            else len(channel.filters)
                        ),
                    }
                    for channel in self.channels
                ],
            })
            _logged_source_config = True

        client = connect_telegram_client(self.logger)
        if client is None:
            return []

        try:
            items: list[TelegramPost] = []
            total_fetched = 0
            total_filtered = 0
            total_matched = 0

            for channel in self.channels:
                fetched, filtered, matched, channel_items = (
                    self._fetch_channel(client, channel)
                )
                total_fetched += fetched
                total_filtered += filtered
                total_matched += matched
                items.extend(channel_items)

            _log(self.logger, {
                "msg": "Telegram fetch complete",
                "channels": len(self.channels),
                "fetched": total_fetched,
                "filtered": total_filtered,
                "matched": total_matched,
                "posts": len(items),
            })
            return items
        finally:
            disconnect_telegram_client(client)

    def _fetch_channel(
        self,
        client: TelegramClient,
        channel: ChannelConfig,
    ) -> tuple[int, int, int, list[TelegramPost]]:
        username = channel.username
        fetched = 0
        filtered = 0
        matched = 0
        items: list[TelegramPost] = []

        try:
            entity = client.get_entity(username)
            messages = client.get_messages(entity, limit=channel.limit)
        except SecurityError as exc:
            # Session drift needs re-login, not a channel error
            _log(self.logger, {
                "msg": "Telegram session security error",
                "username": username,
                "hint": telegram_session_out_of_sync_hint(),
                "exception": str(exc),
            }, level=logging.ERROR)
            return fetched, filtered, matched, items
        except Exception as exc:
            _log(self.logger, {
                "msg": "Error fetching Telegram channel",
                "username": username,
                "exception": str(exc),
            }, level=logging.ERROR)
            return fetched, filtered, matched, items

        for message in messages:
            if message is None:
                continue

            fetched += 1
            post = _prepare_post(message, entity, username, self.logger)
            if post is None:
                filtered += 1
                _log(self.logger, {
                    "msg": "Telegram post filtered",
                    "username": username,
                    "reason": "empty text",
                    "message_id": getattr(message, "id", None),
                }, level=logging.DEBUG)
                continue

            if not matches_filters(post.description, channel.filters):
                filtered += 1
                _log(self.logger, {
                    "msg": "Telegram post filtered",
                    "username": username,
                    "reason": "regex",
                    "message_id": getattr(message, "id", None),
                }, level=logging.DEBUG)
                continue

            matched += 1
            items.append(post)

        return fetched, filtered, matched, items
