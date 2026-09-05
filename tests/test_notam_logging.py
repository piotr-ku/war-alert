import json
import logging
import os
import unittest
from unittest.mock import Mock, patch

import config
from sources import notam as notam_module
from sources.notam import SourceNotam


class RecordingHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)

    def payloads(self, level=None):
        result = []
        for record in self.records:
            if level is not None and record.levelno != level:
                continue
            result.append(json.loads(record.getMessage()))
        return result

    def by_msg(self, msg, level=None):
        return [
            payload
            for payload in self.payloads(level)
            if payload.get("msg") == msg
        ]


def _fields(number, qcode, text, location="EPWW"):
    return {
        "number": number,
        "location": location,
        "text": text,
        "qcode": qcode,
        "pubDate": "2026-01-01",
    }


class TestNotamFetchLogging(unittest.TestCase):
    def setUp(self):
        self.env_keys = ("NOTAM_CLASSIFICATION",)
        self.env_backup = {key: os.environ.get(key) for key in self.env_keys}
        config.apply({
            "notam": {
                "locations": ["EPWW"],
            },
        })
        os.environ.pop("NOTAM_CLASSIFICATION", None)
        notam_module._logged_source_config = False

        self.handler = RecordingHandler()
        self.logger = logging.getLogger("test_notam_logging")
        self.logger.handlers = [self.handler]
        self.logger.setLevel(logging.DEBUG)
        self.logger.propagate = False

    def tearDown(self):
        config.reset()
        for key, value in self.env_backup.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_fetch_logs_match_summary_and_debug_noise(self):
        fields = [
            _fields("D1/26", "QRTCA", "TEMPORARY RESERVED AREA - PJE."),
            _fields(
                "D2/26",
                "QRTCA",
                "WARSAW TMA CLOSED DUE TO UNIDENTIFIED AIRCRAFT.",
            ),
            _fields("D3/26", "QAFXX", "NAV AID"),
        ]
        with patch.object(
            notam_module, "_get_access_token", return_value="token",
        ), patch.object(
                 SourceNotam,
                 "_fetch_location_notams",
                 return_value=(fields, 12),
             ):
            result = SourceNotam(self.logger).fetch(self.logger)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].title, "NOTAM D2/26 (EPWW, QRTCA)")

        info_msgs = [
            payload["msg"]
            for payload in self.handler.payloads(logging.INFO)
        ]
        self.assertEqual(
            info_msgs,
            [
                "NOTAM source configured",
                "NOTAM matched",
                "NOTAM noise filtered",
                "NOTAM fetch complete",
            ],
        )

        matched = self.handler.by_msg("NOTAM matched", logging.INFO)
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0]["number"], "D2/26")
        self.assertFalse(matched[0]["passthrough"])
        self.assertEqual(
            matched[0]["text"],
            "WARSAW TMA CLOSED DUE TO UNIDENTIFIED AIRCRAFT.",
        )

        noise = self.handler.by_msg("NOTAM noise filtered", logging.INFO)
        self.assertEqual(noise[0]["count"], 1)
        self.assertEqual(noise[0]["reasons"], {"PJE": 1})

        complete = self.handler.by_msg("NOTAM fetch complete", logging.INFO)[0]
        self.assertEqual(complete["fetched"], 3)
        self.assertEqual(complete["skipped_qcode"], 1)
        self.assertEqual(complete["filtered"], 1)
        self.assertEqual(complete["matched"], 1)
        self.assertEqual(complete["duplicates"], 0)
        self.assertIn("duration_ms", complete)
        self.assertEqual(complete["locations"]["EPWW"]["count"], 3)
        self.assertEqual(complete["locations"]["EPWW"]["duration_ms"], 12)

        debug_noise = self.handler.by_msg(
            "NOTAM filtered as noise",
            logging.DEBUG,
        )
        self.assertEqual(len(debug_noise), 1)
        self.assertEqual(debug_noise[0]["number"], "D1/26")
        self.assertEqual(
            debug_noise[0]["text"],
            "TEMPORARY RESERVED AREA - PJE.",
        )

    def test_config_logged_once(self):
        with patch.object(
            notam_module, "_get_access_token", return_value="token",
        ), patch.object(
                 SourceNotam,
                 "_fetch_location_notams",
                 return_value=([], 0),
             ):
            source = SourceNotam(self.logger)
            source.fetch(self.logger)
            source.fetch(self.logger)

        self.assertEqual(
            len(self.handler.by_msg("NOTAM source configured", logging.INFO)),
            1,
        )
        completes = self.handler.by_msg("NOTAM fetch complete", logging.INFO)
        self.assertEqual(len(completes), 2)
        self.assertNotIn("NOTAM noise filtered", [
            payload["msg"] for payload in self.handler.payloads(logging.INFO)
        ])

    def test_qatlc_passthrough_logged_as_match(self):
        fields = [
            _fields(
                "A1/26",
                "QATLC",
                "WARSAW TMA CLOSED. AIRSPACE USE PLAN (AUP).",
            ),
        ]
        with patch.object(
            notam_module, "_get_access_token", return_value="token",
        ), patch.object(
                 SourceNotam,
                 "_fetch_location_notams",
                 return_value=(fields, 5),
             ):
            result = SourceNotam(self.logger).fetch(self.logger)

        self.assertEqual(len(result), 1)
        matched = self.handler.by_msg("NOTAM matched", logging.INFO)[0]
        self.assertTrue(matched["passthrough"])
        self.assertEqual(
            matched["text"],
            "WARSAW TMA CLOSED. AIRSPACE USE PLAN (AUP).",
        )
        self.assertEqual(self.handler.by_msg("NOTAM noise filtered"), [])

    def test_location_fetch_dump_is_debug(self):
        payload = {
            "status": "success",
            "data": {
                "geojson": [
                    {
                        "properties": {
                            "coreNOTAMData": {
                                "notam": {
                                    "number": "D1/26",
                                    "location": "EPWW",
                                    "text": "hello",
                                    "selectionCode": "QRTCA",
                                    "issued": "2026-01-01",
                                }
                            }
                        }
                    }
                ]
            },
        }
        response = Mock()
        response.status_code = 200
        response.json.return_value = payload
        with patch("sources.notam.requests.get", return_value=response):
            fields, duration_ms = (
                SourceNotam(self.logger)._fetch_location_notams(
                    "EPWW",
                    "token",
                )
            )

        self.assertEqual(len(fields), 1)
        self.assertGreaterEqual(duration_ms, 0)
        self.assertEqual(
            self.handler.by_msg("FAA NMS NOTAMs fetched", logging.INFO),
            [],
        )
        debug = self.handler.by_msg("FAA NMS NOTAMs fetched", logging.DEBUG)
        self.assertEqual(len(debug), 1)
        self.assertEqual(debug[0]["count"], 1)
        self.assertEqual(debug[0]["notams"][0]["number"], "D1/26")
        self.assertIn("duration_ms", debug[0])


if __name__ == "__main__":
    unittest.main()
