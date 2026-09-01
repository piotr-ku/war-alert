import os
import unittest

from sources.notam import (
    DEFAULT_TEXT_EXCLUDE,
    _exclude_patterns,
    _exclude_reason,
    _is_passthrough,
    _passthrough_qcodes,
)

NOISE_CORPUS = [
    (
        "D6270/26",
        "QRTCA",
        "TEMPORARY RESERVED AREA EPTR1022 - PJE. "
        "AIRSPACE UNCLASSIFIED. TIME OF ACT ACCORDING TO AIRSPACE USE PLAN (AUP).",
    ),
    (
        "D6299/26",
        "QRRCA",
        "RESTRICTED AREA EPR981 - WIELUN. WITHIN AREA ALL FLIGHTS ARE PROHIBITED EXC: "
        "1. STATE AVIATION 2. ACFT BELONGING TO AREA MANAGER",
    ),
    (
        "D6094/26",
        "QRTCA",
        "TEMPORARY RESERVED AREA EPTR1016 - FLYING DRAGONS TEAM - PARAGLIDERS.",
    ),
    (
        "D5725/26",
        "QRTCA",
        "TEMPORARY RESERVED AREA EPTR427 ZEGRZE. TIME OF ACTIVITY ACCORDING TO AIRSPACE USE PLAN.",
    ),
    (
        "D6118/26",
        "QRTCA",
        "TEMPORARY RESERVED AREA EPTR1017. ACT ACCORDING TO AIRSPACE USE PLAN (AUP)",
    ),
    (
        "D6147/26",
        "QRTCA",
        "TEMPORARY RESERVED AREA EPTR364 - MIL. ACT ACCORDING TO AIRSPACE USE PLAN (AUP)",
    ),
    (
        "D6217/26",
        "QRTCA",
        "TEMPORARY RESERVED AREA EPTR1031 PJE CZERSK SWIECKI. "
        "TIME OF ACT ACCORDING TO AIRSPACE USE PLAN (AUP).",
    ),
    (
        "D6222/26",
        "QRTCA",
        "TEMPORARY RESERVED AREA EPTR1035 PJE KOWALEWKO. "
        "TIME OF ACT ACCORDING TO AIRSPACE USE PLAN (AUP).",
    ),
    (
        "D6323/26",
        "QRRCA",
        "RESTRICTED AREA EPR986 GDANSK. WITHIN AREA ALL FLIGHTS ARE PROHIBITED EXC: "
        "1. STATE AVIATION 2. PERFORMED IN COORDINATION WITH AREA MANAGER",
    ),
    (
        "D6240/26",
        "QRTCA",
        "TEMPORARY RESERVED AREA EPTR1023 - PJE. "
        "TIME OF ACT ACCORDING TO AIRSPACE USE PLAN (AUP).",
    ),
    (
        "D6242/26",
        "QRTCA",
        "TEMPORARY RESERVED AREA EPTR1021 UAV FLT AIRSPACE UNCLASSIFIED "
        "TIME OF ACTIVITY ACCORDING TO AIRSPACE USE PLAN.",
    ),
    (
        "D4675/26",
        "QRTCA",
        "TEMPORARY RESERVED AREA EPTR415 - RUBNO WIELKIE (UNMANNED AERIAL VEHICLES FLIGHTS). "
        "TIME OF ACT ACCORDING TO AIRSPACE USE PLAN.",
    ),
    (
        "D6213/26",
        "QRTCA",
        "TEMPORARY RESERVED AREA EPTR910 DEBINY. "
        "FLIGHT INTO AREA AFTER PRIOR PERMISSION FM ORGANIZER ONLY.",
    ),
    (
        "D6294/26",
        "QRRCA",
        "RESTRICTED AREA EPR985 TARNOW. WITHIN AREA ALL FLIGHTS ARE PROHIBITED EXC: "
        "1) ACFT BELONGING TO AREA MANAGER",
    ),
    (
        "D3822/26",
        "QRTCA",
        "REF AIP SUP 102/26 (ENR 5) IN DISTRIBUTION: POINT 1 DATE AND TIME (UTC)",
    ),
    (
        "D3844/26",
        "QRTCA",
        "TEMPORARY RESERVED AREA EPTR456 - ZDUNSKA WOLA. "
        "TIME OF ACTIVITY ACCORDNIG TO AIRSPACE USE PLAN.",
    ),
    (
        "D3845/26",
        "QRTCA",
        "TEMPORARY RESTRICTED AREA ACTIVATED TEMPORARY RESERVED AREA EPTR505B BIELSK PODLASKI. "
        "TIME OF ACTIVITY ACCORDING TO AIRSPACE USE PLAN.",
    ),
    (
        "D3853/26",
        "QRTCA",
        "RESTRICTED AREA EPTR325 - BRZESKO. TIME OF ACTIVITY ACCORDNIG TO AIRSPACE USE PLAN.",
    ),
    (
        "D3594/26",
        "QRTCA",
        "TEMPORARY RESERVED AREA EPTR328 - MIL ACT. "
        "TIME OF ACTIVITY ACCORDING TO AIRSPACE USE PLAN (AUP).",
    ),
    (
        "D3593/26",
        "QRTCA",
        "TEMPORARY RESERVED AREA EPTR327 - MIL ACT. "
        "TIME OF ACTIVITY ACCORDING TO AIRSPACE USE PLAN (AUP).",
    ),
    (
        "D5086/26",
        "QRTCA",
        "REF AIP IFR ENR 5.2.1.2, EPTR153 IS TEMPORARY AVBL FOR REQUEST AND ACTIVATION H24.",
    ),
]


class TestNotamPassthrough(unittest.TestCase):
    def test_qatlc_is_passthrough(self):
        self.assertTrue(_is_passthrough("QATLC"))

    def test_qrpca_is_passthrough(self):
        self.assertTrue(_is_passthrough("QRPCA"))

    def test_qrtca_is_not_passthrough(self):
        self.assertFalse(_is_passthrough("QRTCA"))

    def test_qatlc_passthrough_with_aup_text(self):
        text = "WARSAW TMA CLOSED. TIME OF ACT ACCORDING TO AIRSPACE USE PLAN (AUP)."
        self.assertTrue(_is_passthrough("QATLC"))
        # Passthrough bypasses text filter even when exclude patterns match.
        self.assertIsNotNone(_exclude_reason(text))

    def test_qrpca_passthrough_with_aup_text(self):
        text = (
            "DUE TO THE CRISIS SITUATION IN UKRAINE, NO PLANNING ZONES ARE "
            "MANAGED BY AMC POLAND VIA AUP/UUP."
        )
        self.assertTrue(_is_passthrough("QRPCA"))
        self.assertIsNotNone(_exclude_reason(text))


class TestNotamExcludeReason(unittest.TestCase):
    def setUp(self):
        self.patterns = [
            p.strip().upper()
            for p in DEFAULT_TEXT_EXCLUDE.split(",")
            if p.strip()
        ]

    def test_noise_corpus_all_filtered(self):
        for number, qcode, text in NOISE_CORPUS:
            with self.subTest(number=number, qcode=qcode):
                self.assertFalse(_is_passthrough(qcode))
                self.assertIsNotNone(
                    _exclude_reason(text, self.patterns),
                    msg=f"expected noise filter for {number}",
                )

    def test_unusual_closure_passes(self):
        text = "WARSAW TMA CLOSED DUE TO UNIDENTIFIED AIRCRAFT. ALL FLIGHTS PROHIBITED."
        self.assertFalse(_is_passthrough("QRTCA"))
        self.assertIsNone(_exclude_reason(text, self.patterns))

    def test_qatlc_with_pje_text_still_passes_via_passthrough(self):
        text = "TEMPORARY RESERVED AREA - PJE. AIRSPACE USE PLAN."
        self.assertTrue(_is_passthrough("QATLC"))

    def test_epr131_standing_restriction_passes(self):
        text = (
            "RESTRICTED AREA EPR131. WITHIN AREA ALL FLIGHTS ARE PROHIBITED EXC: "
            "- GARDA, ALPHA SCRAMBLE FLIGHTS "
            "- CIVIL UNMANNED AERIAL VEHICLES EXC ADIZ BIALORUS AND ADIZ UKRAINE "
            "- STATE AVIATION FLIGHTS AND FLIGHTS OF AIR MEDICAL RESCUE (LPR)"
        )
        self.assertFalse(_is_passthrough("QRRCA"))
        self.assertIsNone(_exclude_reason(text, self.patterns))

    def test_qrmxx_state_security_passes(self):
        text = (
            "NAV WRNG FOR AIRSPACE: UNPLANNED MILITARY ACTIVITY RELATED TO "
            "ENSURING STATE SECURITY CAN BE EXPECTED WITHIN THE AREA."
        )
        self.assertFalse(_is_passthrough("QRMXX"))
        self.assertIsNone(_exclude_reason(text, self.patterns))

    def test_unmanned_aerial_vehicles_flights_matches_across_newline(self):
        text = (
            "TEMPORARY RESERVED AREA EPTR415 - RUBNO WIELKIE (UNMANNED AERIAL\n"
            "VEHICLES FLIGHTS). TIME OF ACT ACCORDING TO AIRSPACE USE PLAN."
        )
        self.assertEqual(
            _exclude_reason(text, self.patterns),
            "UNMANNED AERIAL VEHICLES FLIGHTS",
        )


class TestNotamFilterEnv(unittest.TestCase):
    def tearDown(self):
        for key in ("NOTAM_PASSTHROUGH_QCODES", "NOTAM_TEXT_EXCLUDE"):
            os.environ.pop(key, None)

    def test_empty_passthrough_disables_passthrough(self):
        os.environ["NOTAM_PASSTHROUGH_QCODES"] = ""
        self.assertEqual(_passthrough_qcodes(), [])
        self.assertFalse(_is_passthrough("QATLC"))
        self.assertFalse(_is_passthrough("QRPCA"))

    def test_empty_exclude_disables_text_filter(self):
        os.environ["NOTAM_TEXT_EXCLUDE"] = ""
        self.assertEqual(_exclude_patterns(), [])
        text = "TEMPORARY RESERVED AREA EPTR1022 - PJE."
        self.assertIsNone(_exclude_reason(text, _exclude_patterns()))


if __name__ == "__main__":
    unittest.main()
