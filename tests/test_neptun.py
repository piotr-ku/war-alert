import json
import logging
import os
import tempfile
import unittest
from unittest.mock import Mock, patch

import config
from processors.unique import ProcessorUnique
from sources.neptun import NeptunThreat, SourceNeptun


class RecordingHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


def _threat(
    threat_id="trk_1",
    threat_type="uav",
    lat=52.23,
    lon=21.01,
    status="active",
    area_only=False,
    advisory=False,
    heading=None,
    velocity=None,
    title="Шахед",
    explanation="BPL kurs na Warszawę",
):
    payload = {
        "id": threat_id,
        "type": threat_type,
        "title": title,
        "region": "Мазовецьке воєводство",
        "district": "",
        "locality": "Warszawa",
        "lat": lat,
        "lon": lon,
        "heading": heading,
        "status": status,
        "areaOnly": area_only,
        "advisory": advisory,
        "updatedAt": "2026-07-09T12:34:50.000Z",
        "explanationShort": explanation,
    }
    if velocity is not None:
        payload["velocity"] = velocity
    return payload


class TestNeptunThreatStr(unittest.TestCase):
    def test_dedup_includes_position(self):
        threat = NeptunThreat(
            "trk_1",
            "Title",
            "Body",
            "2026-01-01",
            "https://neptun.in.ua/",
            52.231,
            21.012,
        )
        self.assertEqual(str(threat), "neptun:trk_1:52.231:21.012")


class TestSourceNeptunFetch(unittest.TestCase):
    def setUp(self):
        self.handler = RecordingHandler()
        self.logger = logging.getLogger("test_neptun")
        self.logger.handlers = [self.handler]
        self.logger.setLevel(logging.DEBUG)
        self.logger.propagate = False
        self.source = SourceNeptun(self.logger)
        config.apply({
            "classification": {
                "processor": "openai",
                "prompt": "test",
            },
            "neptun": {
                "enabled": True,
                "alert_km": 50,
                "lookahead_minutes": 15,
                "skip_advisory": True,
                "types": ["uav", "missile", "ballistic", "kab"],
            },
        })

    def tearDown(self):
        config.reset()

    @patch("sources.neptun.requests.get")
    def test_inside_poland_threat_is_matched(self, mock_get):
        mock_get.return_value = Mock(
            status_code=200,
            json=Mock(return_value={"threats": [_threat()]}),
        )
        items = self.source.fetch(self.logger)
        self.assertEqual(len(items), 1)
        self.assertIn("nad Polską", items[0].title)

    @patch("sources.neptun.requests.get")
    def test_area_only_threat_is_skipped(self, mock_get):
        mock_get.return_value = Mock(
            status_code=200,
            json=Mock(return_value={
                "threats": [_threat(area_only=True, lat=49.5, lon=24.0)],
            }),
        )
        items = self.source.fetch(self.logger)
        self.assertEqual(items, [])

    @patch("sources.neptun.requests.get")
    def test_advisory_threat_is_skipped(self, mock_get):
        mock_get.return_value = Mock(
            status_code=200,
            json=Mock(return_value={
                "threats": [_threat(advisory=True, lat=49.9, lon=23.2)],
            }),
        )
        items = self.source.fetch(self.logger)
        self.assertEqual(items, [])

    @patch("sources.neptun.requests.get")
    def test_odessa_threat_is_skipped(self, mock_get):
        mock_get.return_value = Mock(
            status_code=200,
            json=Mock(return_value={
                "threats": [_threat(lat=46.48, lon=30.74)],
            }),
        )
        items = self.source.fetch(self.logger)
        self.assertEqual(items, [])

    @patch("sources.neptun.requests.get")
    def test_fetch_logs_error_on_http_failure(self, mock_get):
        mock_get.return_value = Mock(status_code=500, text="error")
        items = self.source.fetch(self.logger)
        self.assertEqual(items, [])
        errors = [
            json.loads(record.getMessage())
            for record in self.handler.records
            if record.levelno == logging.ERROR
        ]
        self.assertTrue(any(entry.get("msg") == "Error fetching threats from NEPTUN" for entry in errors))

    @patch("sources.neptun.requests.get")
    def test_invalid_coordinates_are_skipped(self, mock_get):
        mock_get.return_value = Mock(
            status_code=200,
            json=Mock(return_value={
                "threats": [_threat(lat="not-a-number", lon=21.01)],
            }),
        )
        items = self.source.fetch(self.logger)
        self.assertEqual(items, [])

    @patch("sources.neptun.requests.get")
    def test_invalid_velocity_falls_back_to_heading(self, mock_get):
        mock_get.return_value = Mock(
            status_code=200,
            json=Mock(return_value={
                "threats": [_threat(
                    velocity={"bearingDeg": "bad", "speedKmh": 150},
                    heading=270,
                )],
            }),
        )
        items = self.source.fetch(self.logger)
        self.assertEqual(len(items), 1)
        self.assertIn("Kurs: 270°", items[0].description)

    @patch("sources.neptun.requests.get")
    def test_malformed_threat_does_not_break_valid_one(self, mock_get):
        mock_get.return_value = Mock(
            status_code=200,
            json=Mock(return_value={
                "threats": [
                    _threat(threat_id="bad", lat="x", lon="y"),
                    _threat(threat_id="good"),
                ],
            }),
        )
        items = self.source.fetch(self.logger)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].threat_id, "good")


class TestNeptunDedup(unittest.TestCase):
    def setUp(self):
        self.logger = logging.getLogger("test_neptun_dedup")
        self.logger.handlers = []
        self.logger.setLevel(logging.DEBUG)
        self.logger.propagate = False
        self.tmp = tempfile.NamedTemporaryFile(delete=False)
        self.tmp.close()
        os.environ["TMPDIR"] = os.path.dirname(self.tmp.name)
        dedup_path = os.path.join(os.environ["TMPDIR"], "war-alert.txt")
        if os.path.exists(dedup_path):
            os.remove(dedup_path)

    def tearDown(self):
        dedup_path = os.path.join(os.environ["TMPDIR"], "war-alert.txt")
        if os.path.exists(dedup_path):
            os.remove(dedup_path)
        if os.path.exists(self.tmp.name):
            os.remove(self.tmp.name)

    def _threat(self, lat, lon):
        return NeptunThreat(
            "trk_1",
            "Title",
            "Body",
            "2026-01-01",
            "https://neptun.in.ua/",
            lat,
            lon,
        )

    def test_same_position_is_duplicate_after_mark_seen(self):
        processor = ProcessorUnique()
        first = self._threat(52.231, 21.012)
        second = self._threat(52.231, 21.012)

        self.assertIsNotNone(processor.process(first, self.logger))
        processor.mark_seen(first)
        self.assertIsNone(processor.process(second, self.logger))

    def test_position_change_is_not_duplicate(self):
        processor = ProcessorUnique()
        first = self._threat(52.231, 21.012)
        moved = self._threat(52.240, 21.020)

        self.assertIsNotNone(processor.process(first, self.logger))
        processor.mark_seen(first)
        self.assertIsNotNone(processor.process(moved, self.logger))


if __name__ == "__main__":
    unittest.main()
