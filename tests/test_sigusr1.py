import importlib.util
import logging
import os
import signal
import sys
import unittest
from unittest.mock import patch


def load_war_alert():
    module_path = os.path.join(
        os.path.dirname(__file__),
        "..",
        "war-alert.py",
    )
    spec = importlib.util.spec_from_file_location("war_alert", module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["war_alert"] = module
    spec.loader.exec_module(module)
    return module


class TestSIGUSR1(unittest.TestCase):
    def setUp(self):
        self.war_alert = load_war_alert()
        self.war_alert._test_notification_event.clear()
        self.logger = logging.getLogger("test_sigusr1")
        self.war_alert.logger = self.logger

    def test_usr1_handler_sets_event_without_processing(self):
        with patch.object(
            self.war_alert,
            "process_and_notify",
        ) as mock_notify:
            self.war_alert.usr1_handler(signal.SIGUSR1, None)

        self.assertTrue(self.war_alert._test_notification_event.is_set())
        mock_notify.assert_not_called()

    def test_run_pending_test_notification_clears_event_and_processes(
        self,
    ):
        self.war_alert._test_notification_event.set()
        with patch.object(
            self.war_alert,
            "process_and_notify",
            return_value=True,
        ) as mock_notify:
            self.war_alert.run_pending_test_notification(self.logger)

        self.assertFalse(self.war_alert._test_notification_event.is_set())
        mock_notify.assert_called_once()


if __name__ == "__main__":
    unittest.main()
