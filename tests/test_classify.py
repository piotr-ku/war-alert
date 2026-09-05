import logging
import unittest
from unittest.mock import Mock, patch

from processors.classify import (
    ProcessorClassification,
    get_system_prompt,
    news_processors,
    parse_processor_names,
)
from processors.unique import ProcessorUnique
from sources.rss import News


class TestParseProcessorNames(unittest.TestCase):
    def test_default_when_unset(self):
        self.assertEqual(parse_processor_names(None), ["openai"])
        self.assertEqual(parse_processor_names(""), ["openai"])
        self.assertEqual(parse_processor_names("   "), ["openai"])

    def test_single_provider(self):
        self.assertEqual(parse_processor_names("openrouter"), ["openrouter"])

    def test_multiple_providers(self):
        self.assertEqual(
            parse_processor_names("openrouter,openai"),
            ["openrouter", "openai"],
        )

    def test_ignores_whitespace(self):
        self.assertEqual(
            parse_processor_names(" openrouter , openai "),
            ["openrouter", "openai"],
        )

    def test_unknown_provider_raises(self):
        with self.assertRaises(ValueError) as ctx:
            parse_processor_names("unknown")
        self.assertIn("unknown", str(ctx.exception))


class TestGetSystemPrompt(unittest.TestCase):
    @patch(
        "processors.classify.config.classification_prompt",
        return_value="Classify: <content>",
    )
    def test_strips_legacy_content_placeholder(self, _mock_prompt):
        self.assertEqual(get_system_prompt(), "Classify: ")


class TestNewsProcessors(unittest.TestCase):
    def test_returns_unique_and_classification(self):
        processors = news_processors()
        self.assertEqual(len(processors), 2)
        self.assertIs(processors[0], ProcessorUnique)
        self.assertIs(processors[1], ProcessorClassification)


class TestProcessorClassification(unittest.TestCase):
    def setUp(self):
        self.logger = logging.getLogger("test_classify")
        self.content = News(
            "Alert title",
            "Alert description",
            "2026-04-09T10:00:00",
            "https://example.com/item",
        )

    @patch(
        "processors.classify.get_system_prompt",
        return_value="system prompt",
    )
    def test_accepts_relevant_item(self, _mock_system_prompt):
        mock_openai = Mock(
            return_value=(
                '{"result": "yes", "justification": "Relevant alert"}'
            ),
        )
        providers = {"openai": mock_openai}
        user_prompt = str(self.content)
        with patch.dict(
            "processors.classify.PROVIDERS",
            providers,
            clear=True,
        ):
            processor = ProcessorClassification(["openai"])
            result = processor.process(self.content, self.logger)

        self.assertIs(result, self.content)
        self.assertEqual(result.description, "Relevant alert")
        mock_openai.assert_called_once_with(
            "system prompt",
            user_prompt,
            self.logger,
        )

    @patch(
        "processors.classify.get_system_prompt",
        return_value="system prompt",
    )
    def test_rejects_item_without_fallback(self, _mock_system_prompt):
        mock_openai = Mock(
            return_value=(
                '{"result": "no", "justification": "Not relevant"}'
            ),
        )
        providers = {
            "openrouter": Mock(return_value=""),
            "openai": mock_openai,
        }
        user_prompt = str(self.content)
        with patch.dict(
            "processors.classify.PROVIDERS",
            providers,
            clear=True,
        ):
            processor = ProcessorClassification(
                ["openrouter", "openai"],
            )
            result = processor.process(self.content, self.logger)

        self.assertIsNone(result)
        mock_openai.assert_called_once_with(
            "system prompt",
            user_prompt,
            self.logger,
        )
        providers["openrouter"].assert_called_once_with(
            "system prompt",
            user_prompt,
            self.logger,
        )

    @patch(
        "processors.classify.get_system_prompt",
        return_value="system prompt",
    )
    def test_fallback_on_api_failure(self, _mock_system_prompt):
        mock_openrouter = Mock(return_value="")
        mock_openai = Mock(
            return_value=(
                '{"result": "yes", "justification": "Fallback ok"}'
            ),
        )
        providers = {
            "openrouter": mock_openrouter,
            "openai": mock_openai,
        }
        user_prompt = str(self.content)
        with patch.dict(
            "processors.classify.PROVIDERS",
            providers,
            clear=True,
        ):
            processor = ProcessorClassification(
                ["openrouter", "openai"],
            )
            result = processor.process(self.content, self.logger)

        self.assertIs(result, self.content)
        mock_openrouter.assert_called_once_with(
            "system prompt",
            user_prompt,
            self.logger,
        )
        mock_openai.assert_called_once_with(
            "system prompt",
            user_prompt,
            self.logger,
        )

    @patch(
        "processors.classify.get_system_prompt",
        return_value="system prompt",
    )
    def test_fallback_on_invalid_json(self, _mock_system_prompt):
        mock_openrouter = Mock(return_value="not-json")
        mock_openai = Mock(
            return_value=(
                '{"result": "yes", "justification": "Fallback ok"}'
            ),
        )
        providers = {
            "openrouter": mock_openrouter,
            "openai": mock_openai,
        }
        user_prompt = str(self.content)
        with patch.dict(
            "processors.classify.PROVIDERS",
            providers,
            clear=True,
        ):
            processor = ProcessorClassification(
                ["openrouter", "openai"],
            )
            result = processor.process(self.content, self.logger)

        self.assertIs(result, self.content)
        mock_openrouter.assert_called_once_with(
            "system prompt",
            user_prompt,
            self.logger,
        )
        mock_openai.assert_called_once_with(
            "system prompt",
            user_prompt,
            self.logger,
        )

    @patch(
        "processors.classify.get_system_prompt",
        return_value="system prompt",
    )
    def test_all_providers_fail_returns_none(self, _mock_system_prompt):
        providers = {
            "openrouter": Mock(return_value=""),
            "openai": Mock(return_value=""),
        }
        with patch.dict(
            "processors.classify.PROVIDERS",
            providers,
            clear=True,
        ):
            processor = ProcessorClassification(
                ["openrouter", "openai"],
            )
            result = processor.process(self.content, self.logger)

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
