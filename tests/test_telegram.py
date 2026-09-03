import importlib.util
import logging
import os
import sqlite3
import sys
import tempfile
import textwrap
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from processors.openai import ProcessorOpenAI
from processors.unique import ProcessorUnique
from sources.telegram import (
    ChannelConfig,
    SourceTelegram,
    TelegramPost,
    authorize_telegram_client,
    connect_telegram_client,
    disconnect_telegram_client,
    is_session_locked_error,
    load_channel_configs,
    matches_filters,
    reset_telegram_client,
    telegram_credentials_configured,
    telegram_session_locked_hint,
)


def load_war_alert():
    module_path = os.path.join(os.path.dirname(__file__), "..", "war-alert.py")
    spec = importlib.util.spec_from_file_location("war_alert", module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["war_alert"] = module
    spec.loader.exec_module(module)
    return module


def _message(message_id: int, text: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=message_id,
        message=text,
        date=SimpleNamespace(strftime=lambda fmt: "2026-09-03T12:00:00"),
    )


class TestTelegramFilters(unittest.TestCase):
    def setUp(self):
        self.logger = logging.getLogger("test_telegram_filters")
        self.env_backup = {
            key: os.environ.get(key)
            for key in ("TELEGRAM_CHANNELS_FILE",)
        }

    def tearDown(self):
        for key, value in self.env_backup.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_load_channel_configs_compiles_filters(self):
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as handle:
            handle.write(textwrap.dedent("""
                channels:
                  - username: AMK_Mapping
                    limit: 5
                    filters:
                      - '(?i)\\bpoland\\b'
                      - '(?i)\\bjasionka\\b'
            """))
            path = handle.name

        os.environ["TELEGRAM_CHANNELS_FILE"] = path
        channels = load_channel_configs(self.logger)

        self.assertEqual(len(channels), 1)
        self.assertEqual(channels[0].username, "AMK_Mapping")
        self.assertEqual(channels[0].limit, 5)
        self.assertEqual(len(channels[0].filters), 2)

        os.unlink(path)

    def test_matches_filters_or_semantics(self):
        filters = [__import__("re").compile(r"(?i)\bpoland\b")]
        self.assertTrue(matches_filters("Troops near Poland border", filters))
        self.assertFalse(matches_filters("Russian advances in Donetsk Oblast", filters))

    def test_project_yaml_matches_poland_krakow_jasionka(self):
        channels = load_channel_configs(self.logger)
        self.assertGreaterEqual(len(channels), 1)
        filters = channels[0].filters

        self.assertTrue(matches_filters("Poland activated air defences.", filters))
        self.assertTrue(matches_filters("Cargo landed at Jasionka airport.", filters))
        self.assertTrue(matches_filters("Strike reported near Kraków.", filters))
        self.assertFalse(matches_filters("Russian Geran-4 drones struck Odesa Oblast.", filters))

    def test_invalid_regex_is_skipped(self):
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as handle:
            handle.write(textwrap.dedent("""
                channels:
                  - username: test_channel
                    filters:
                      - '(?i)[unclosed'
                      - '(?i)\\bpoland\\b'
            """))
            path = handle.name

        os.environ["TELEGRAM_CHANNELS_FILE"] = path
        channels = load_channel_configs(self.logger)

        self.assertEqual(len(channels), 1)
        self.assertEqual(len(channels[0].filters), 1)
        self.assertTrue(matches_filters("Poland alert", channels[0].filters))

        os.unlink(path)

    def test_empty_filters_pass_everything(self):
        self.assertTrue(matches_filters("Any text", None))

    def test_all_invalid_filters_drop_everything(self):
        self.assertFalse(matches_filters("Poland alert", []))


class TestSourceTelegram(unittest.TestCase):
    def setUp(self):
        self.logger = logging.getLogger("test_source_telegram")
        self.env_keys = (
            "TELEGRAM_API_ID",
            "TELEGRAM_API_HASH",
            "TELEGRAM_CHANNELS_FILE",
            "TELEGRAM_SESSION_STRING",
        )
        self.env_backup = {key: os.environ.get(key) for key in self.env_keys}
        os.environ["TELEGRAM_API_ID"] = "12345"
        os.environ["TELEGRAM_API_HASH"] = "hash"
        os.environ["TELEGRAM_SESSION_STRING"] = "1AgA"

        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as handle:
            handle.write(textwrap.dedent("""
                channels:
                  - username: AMK_Mapping
                    limit: 3
                    filters:
                      - '(?i)\\bpoland\\b'
                      - '(?i)\\bjasionka\\b'
            """))
            self.channels_file = handle.name
        os.environ["TELEGRAM_CHANNELS_FILE"] = self.channels_file
        reset_telegram_client()

    def tearDown(self):
        reset_telegram_client()
        for key, value in self.env_backup.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        os.unlink(self.channels_file)

    def test_processors(self):
        source = SourceTelegram(self.logger)
        self.assertEqual(source.processors(), [ProcessorUnique, ProcessorOpenAI])

    def test_fetch_applies_regex_before_returning_posts(self):
        source = SourceTelegram(self.logger)
        entity = SimpleNamespace(title="AMK Mapping")
        messages = [
            _message(1, "Poland activated air defences."),
            _message(2, "Russian Geran-4 drones struck Odesa Oblast."),
            _message(3, "Cargo landed at Jasionka airport."),
        ]
        client = Mock()
        client.get_entity.return_value = entity
        client.get_messages.return_value = messages

        with patch("sources.telegram.connect_telegram_client", return_value=client):
            items = source.fetch(self.logger)

        self.assertEqual(len(items), 2)
        self.assertIsInstance(items[0], TelegramPost)
        self.assertIn("Poland", items[0].description)
        self.assertIn("Jasionka", items[1].description)
        client.get_entity.assert_called_once_with("AMK_Mapping")
        client.get_messages.assert_called_once_with(entity, limit=3)

    def test_fetch_skips_empty_messages(self):
        source = SourceTelegram(self.logger)
        entity = SimpleNamespace(title="AMK Mapping")
        messages = [
            _message(1, "   "),
            _message(2, "Poland alert"),
        ]
        client = Mock()
        client.get_entity.return_value = entity
        client.get_messages.return_value = messages

        with patch("sources.telegram.connect_telegram_client", return_value=client):
            items = source.fetch(self.logger)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].link, "https://t.me/AMK_Mapping/2")

    def test_fetch_returns_empty_when_client_unavailable(self):
        source = SourceTelegram(self.logger)

        with patch("sources.telegram.connect_telegram_client", return_value=None):
            items = source.fetch(self.logger)

        self.assertEqual(items, [])


    def test_fetch_disconnects_client_after_poll(self):
        source = SourceTelegram(self.logger)
        client = Mock()
        client.get_entity.return_value = SimpleNamespace(title="AMK Mapping")
        client.get_messages.return_value = []

        with patch("sources.telegram.connect_telegram_client", return_value=client), \
             patch("sources.telegram.disconnect_telegram_client") as disconnect:
            source.fetch(self.logger)

        disconnect.assert_called_once_with(client)


class TestTelegramSession(unittest.TestCase):
    def test_authorize_skips_start_when_already_authorized(self):
        client = Mock()
        client.is_connected.return_value = True
        client.is_user_authorized.return_value = True

        authorize_telegram_client(client, phone="+48123456789")

        client.connect.assert_not_called()
        client.start.assert_not_called()

    def test_authorize_uses_phone_when_provided(self):
        client = Mock()
        client.is_connected.return_value = False
        client.is_user_authorized.side_effect = [False, True]

        authorize_telegram_client(client, phone="+48123456789")

        client.connect.assert_called_once()
        client.start.assert_called_once_with(phone="+48123456789")

    def test_authorize_prompts_interactively_without_phone(self):
        client = Mock()
        client.is_connected.return_value = False
        client.is_user_authorized.side_effect = [False, True]

        authorize_telegram_client(client)

        client.start.assert_called_once_with()

    def test_disconnect_only_when_connected(self):
        client = Mock()
        client.is_connected.return_value = True

        disconnect_telegram_client(client)

        client.disconnect.assert_called_once()

    def test_session_locked_error_detection(self):
        self.assertTrue(is_session_locked_error(sqlite3.OperationalError("database is locked")))
        self.assertTrue(is_session_locked_error(RuntimeError("database is locked")))
        self.assertFalse(is_session_locked_error(RuntimeError("other error")))

    def test_session_locked_hint_mentions_stop(self):
        self.assertIn("stop war-alert", telegram_session_locked_hint().lower())


class TestTelegramCredentials(unittest.TestCase):
    def setUp(self):
        self.env_backup = {
            key: os.environ.get(key)
            for key in ("TELEGRAM_API_ID", "TELEGRAM_API_HASH")
        }

    def tearDown(self):
        for key, value in self.env_backup.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_credentials_require_id_and_hash(self):
        os.environ.pop("TELEGRAM_API_ID", None)
        os.environ.pop("TELEGRAM_API_HASH", None)
        self.assertFalse(telegram_credentials_configured())

        os.environ["TELEGRAM_API_ID"] = "12345"
        self.assertFalse(telegram_credentials_configured())

        os.environ["TELEGRAM_API_HASH"] = "hash"
        self.assertTrue(telegram_credentials_configured())


class TestAllSourcesTelegram(unittest.TestCase):
    def setUp(self):
        self.war_alert = load_war_alert()
        self.logger = logging.getLogger("test_all_sources_telegram")
        self.env_keys = (
            "TELEGRAM_API_ID",
            "TELEGRAM_API_HASH",
            "TELEGRAM_CHANNELS_FILE",
            "TWITTERAPI_KEY",
            "TWITTERAPI_USERNAMES",
        )
        self.env_backup = {key: os.environ.get(key) for key in self.env_keys}
        for key in self.env_keys:
            os.environ.pop(key, None)

    def tearDown(self):
        for key, value in self.env_backup.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_all_sources_adds_telegram_when_configured(self):
        os.environ["TELEGRAM_API_ID"] = "12345"
        os.environ["TELEGRAM_API_HASH"] = "hash"

        sources = self.war_alert.all_sources(self.logger)

        self.assertEqual(len(sources), 1)
        self.assertIsInstance(sources[0], SourceTelegram)

    def test_all_sources_skips_telegram_without_credentials(self):
        sources = self.war_alert.all_sources(self.logger)
        self.assertEqual(sources, [])

    def test_all_sources_skips_telegram_without_channels_file(self):
        os.environ["TELEGRAM_API_ID"] = "12345"
        os.environ["TELEGRAM_API_HASH"] = "hash"
        os.environ["TELEGRAM_CHANNELS_FILE"] = "/does/not/exist.yaml"

        sources = self.war_alert.all_sources(self.logger)
        self.assertEqual(sources, [])


if __name__ == "__main__":
    unittest.main()
