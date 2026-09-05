import logging
import tempfile
import textwrap
import unittest
from pathlib import Path

import config


class TestConfigApply(unittest.TestCase):
    def tearDown(self):
        config.reset()

    def test_apply_sets_rss_urls(self):
        config.apply({"rss": {"urls": ["https://example.com/rss"]}})
        self.assertEqual(
            config.rss_urls(),
            ["https://example.com/rss"],
        )

    def test_classification_processor_parses_chain(self):
        config.apply({
            "classification": {
                "processor": "openrouter,openai",
                "prompt": "test <content>",
            },
        })
        self.assertEqual(
            config.classification_processor(),
            ["openrouter", "openai"],
        )

    def test_notam_empty_lists_disable_filters(self):
        config.apply({
            "notam": {
                "passthrough_qcodes": [],
                "text_exclude": [],
            },
        })
        self.assertEqual(config.notam_passthrough_qcodes_raw(), "")
        self.assertEqual(config.notam_text_exclude_raw(), "")


class TestConfigReload(unittest.TestCase):
    def setUp(self):
        self.logger = logging.getLogger("test_config_reload")
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_path = Path(self.temp_dir.name) / "war-alert.yml"
        config.reset()
        config.set_search_paths([self.config_path])

    def tearDown(self):
        self.temp_dir.cleanup()
        config.reset()

    def _write(self, content: str) -> None:
        self.config_path.write_text(textwrap.dedent(content), encoding="utf-8")

    def test_reload_required_exits_when_missing(self):
        with self.assertRaises(SystemExit):
            config.reload(self.logger, required=True)

    def test_reload_keeps_previous_config_on_parse_error(self):
        self._write("""
            classification:
              processor: openai
              prompt: |
                test <content>
            rss:
              urls:
                - https://example.com/rss
        """)
        config.reload(self.logger, required=True)
        self.assertEqual(
            config.rss_urls(),
            ["https://example.com/rss"],
        )

        self._write("classification: [unclosed\n")
        result = config.reload(self.logger, required=False)

        self.assertFalse(result)
        self.assertEqual(
            config.rss_urls(),
            ["https://example.com/rss"],
        )

    def test_reload_rejects_unknown_processor(self):
        self._write("""
            classification:
              processor: unknown
              prompt: |
                test <content>
        """)
        with self.assertRaises(SystemExit):
            config.reload(self.logger, required=True)

    def test_reload_updates_values(self):
        self._write("""
            classification:
              processor: openai
              prompt: |
                test <content>
            twitter:
              usernames:
                - DefenceU
        """)
        config.reload(self.logger, required=True)
        self.assertEqual(config.twitter_usernames(), ["DefenceU"])

        self._write("""
            classification:
              processor: openai
              prompt: |
                test <content>
            twitter:
              usernames:
                - MON_GOV_PL
        """)
        config.reload(self.logger, required=False)
        self.assertEqual(config.twitter_usernames(), ["MON_GOV_PL"])


class TestConfigSearchPaths(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = Path(self.temp_dir.name)
        config.reset()

    def tearDown(self):
        self.temp_dir.cleanup()
        config.reset()

    def test_uses_first_existing_path(self):
        low = self.base / "low.yml"
        high = self.base / "high.yml"
        low.write_text(
            "classification:\n  processor: openai\n  prompt: low\n",
            encoding="utf-8",
        )
        high.write_text(
            "classification:\n  processor: openai\n  prompt: high\n",
            encoding="utf-8",
        )
        config.set_search_paths([high, low])
        logger = logging.getLogger("test_config_search_paths")

        config.reload(logger, required=True)

        self.assertEqual(config.config_path(), high)
        self.assertEqual(config.classification_prompt(), "high")


class TestParseProcessorNames(unittest.TestCase):
    def test_default_when_unset(self):
        config.reset()
        self.assertEqual(config.classification_processor(), ["openai"])


if __name__ == "__main__":
    unittest.main()
