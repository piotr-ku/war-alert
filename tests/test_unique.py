import importlib.util
import logging
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

from processors.base import Content, Processor
from processors.unique import ProcessorUnique, calculate_md5_hash
from sources.rss import News


def load_war_alert():
    module_path = os.path.join(os.path.dirname(__file__), "..", "war-alert.py")
    spec = importlib.util.spec_from_file_location("war_alert", module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["war_alert"] = module
    spec.loader.exec_module(module)
    return module


class StubContent(Content):
    def __init__(self, text: str):
        self.text = text

    def __str__(self) -> str:
        return self.text


class DropProcessor(Processor):
    def process(self, content: Content, logger: logging.Logger) -> Content | None:
        return None


class PassThroughProcessor(Processor):
    def process(self, content: Content, logger: logging.Logger) -> Content | None:
        return content


class TestProcessorUnique(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        os.environ["TMPDIR"] = self.tmpdir
        self.logger = logging.getLogger("test_unique")

    def tearDown(self):
        os.environ.pop("TMPDIR", None)

    def test_mark_seen_uses_original_hash_after_description_change(self):
        content = News("Title", "original description", "2026-01-01", "http://example.com")
        original_hash = calculate_md5_hash(str(content))

        processor = ProcessorUnique()
        self.assertIsNotNone(processor.process(content, self.logger))

        content.description = "OpenAI justification"
        processor.mark_seen(content)

        fresh = News("Title", "original description", "2026-01-01", "http://example.com")
        self.assertIsNone(processor.process(fresh, self.logger))

        mutated = News("Title", "OpenAI justification", "2026-01-01", "http://example.com")
        self.assertIsNotNone(processor.process(mutated, self.logger))
        self.assertNotEqual(
            calculate_md5_hash(str(mutated)),
            original_hash,
        )

    def test_mark_seen_without_process_falls_back_to_current_content(self):
        content = StubContent("fallback")
        ProcessorUnique().mark_seen(content)

        self.assertIsNone(ProcessorUnique().process(StubContent("fallback"), self.logger))


class TestProcessAndNotify(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.war_alert = load_war_alert()

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        os.environ["TMPDIR"] = self.tmpdir
        self.logger = logging.getLogger("test_process_and_notify")

    def tearDown(self):
        os.environ.pop("TMPDIR", None)

    def test_processor_drop_marks_seen(self):
        process_and_notify = self.war_alert.process_and_notify

        content = News("Title", "description", "2026-01-01", "http://example.com")
        notified = process_and_notify(
            content,
            [ProcessorUnique, DropProcessor],
            self.logger,
        )

        self.assertFalse(notified)
        self.assertIsNone(ProcessorUnique().process(
            News("Title", "description", "2026-01-01", "http://example.com"),
            self.logger,
        ))

    def test_failed_notification_does_not_mark_seen(self):
        process_and_notify = self.war_alert.process_and_notify

        with patch.object(self.war_alert, "all_notifiers", return_value=[]):
            content = News("Title", "description", "2026-01-01", "http://example.com")
            notified = process_and_notify(
                content,
                [ProcessorUnique, PassThroughProcessor],
                self.logger,
            )

        self.assertFalse(notified)
        self.assertIsNotNone(ProcessorUnique().process(
            News("Title", "description", "2026-01-01", "http://example.com"),
            self.logger,
        ))

    def test_successful_notification_marks_seen(self):
        process_and_notify = self.war_alert.process_and_notify

        class SuccessfulNotifier:
            def notify(self, content, logger):
                return True

        with patch.object(self.war_alert, "all_notifiers", return_value=[SuccessfulNotifier()]):
            content = News("Title", "description", "2026-01-01", "http://example.com")
            notified = process_and_notify(
                content,
                [ProcessorUnique, PassThroughProcessor],
                self.logger,
            )

        self.assertTrue(notified)
        self.assertIsNone(ProcessorUnique().process(
            News("Title", "description", "2026-01-01", "http://example.com"),
            self.logger,
        ))


if __name__ == "__main__":
    unittest.main()
