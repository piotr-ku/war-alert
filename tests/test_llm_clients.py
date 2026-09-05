import logging
import os
import unittest
from unittest.mock import MagicMock, patch

from processors.openai import query as openai_query
from processors.openrouter import query as openrouter_query


class TestOpenAIClient(unittest.TestCase):
    def setUp(self):
        self.logger = logging.getLogger("test_openai")

    @patch("processors.openai.config.openai_model", return_value="gpt-test")
    @patch("processors.openai.openai.OpenAI")
    def test_sends_system_and_user_messages(self, mock_openai_cls, _mock_model):
        completion = MagicMock()
        completion.choices = [
            MagicMock(message=MagicMock(content='{"result": "no"}')),
        ]
        completion.usage = None
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = completion
        mock_openai_cls.return_value = mock_client

        text, meta = openai_query(
            "system instructions",
            "news text",
            self.logger,
        )

        self.assertEqual(text, '{"result": "no"}')
        self.assertEqual(meta, {"model": "gpt-test"})
        messages = (
            mock_client.chat.completions.create.call_args.kwargs["messages"]
        )
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[0]["content"], "system instructions")
        self.assertEqual(messages[1]["role"], "user")
        self.assertEqual(messages[1]["content"], "news text")

    @patch("processors.openai.config.openai_model", return_value="gpt-test")
    @patch("processors.openai.openai.OpenAI")
    def test_returns_decimal_cost_when_available(
        self,
        mock_openai_cls,
        _mock_model,
    ):
        completion = MagicMock()
        completion.choices = [
            MagicMock(message=MagicMock(content='{"result": "no"}')),
        ]
        completion.usage = MagicMock(cost=8.41e-05)
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = completion
        mock_openai_cls.return_value = mock_client

        _text, meta = openai_query(
            "system instructions",
            "news text",
            self.logger,
        )

        self.assertEqual(meta["model"], "gpt-test")
        self.assertEqual(meta["cost"], "0.0000841")
        self.assertNotIn("e", meta["cost"])


class TestOpenRouterClient(unittest.TestCase):
    def setUp(self):
        self.logger = logging.getLogger("test_openrouter")

    @patch.dict(os.environ, {}, clear=True)
    def test_missing_api_key_returns_empty(self):
        text, meta = openrouter_query(
            "system instructions",
            "news text",
            self.logger,
        )
        self.assertEqual(text, "")
        self.assertEqual(meta, {})

    @patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}, clear=False)
    @patch(
        "processors.openrouter.config.openrouter_model",
        return_value="openai/gpt-test",
    )
    @patch("processors.openrouter.openai.OpenAI")
    def test_sends_system_and_user_messages(
        self,
        mock_openai_cls,
        _mock_model,
    ):
        completion = MagicMock()
        completion.choices = [
            MagicMock(message=MagicMock(content='{"result": "no"}')),
        ]
        completion.model = "anthropic/claude-3.5-sonnet"
        completion.usage = MagicMock(cost=0.0012)
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = completion
        mock_openai_cls.return_value = mock_client

        text, meta = openrouter_query(
            "system instructions",
            "news text",
            self.logger,
        )

        self.assertEqual(text, '{"result": "no"}')
        self.assertEqual(meta["model"], "anthropic/claude-3.5-sonnet")
        self.assertEqual(meta["cost"], "0.0012")
        messages = (
            mock_client.chat.completions.create.call_args.kwargs["messages"]
        )
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[0]["content"], "system instructions")
        self.assertEqual(messages[1]["role"], "user")
        self.assertEqual(messages[1]["content"], "news text")

    @patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}, clear=False)
    @patch(
        "processors.openrouter.config.openrouter_model",
        return_value="openai/gpt-test",
    )
    @patch("processors.openrouter.openai.OpenAI")
    def test_omits_cost_when_usage_has_none(
        self,
        mock_openai_cls,
        _mock_model,
    ):
        completion = MagicMock()
        completion.choices = [
            MagicMock(message=MagicMock(content='{"result": "no"}')),
        ]
        completion.model = "openai/gpt-test"
        completion.usage = MagicMock(cost=None)
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = completion
        mock_openai_cls.return_value = mock_client

        _text, meta = openrouter_query(
            "system instructions",
            "news text",
            self.logger,
        )

        self.assertEqual(meta, {"model": "openai/gpt-test"})


if __name__ == "__main__":
    unittest.main()
