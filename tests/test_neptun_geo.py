import unittest

from sources.neptun_geo import (
    distance_to_poland_km,
    point_in_polygon,
    predict_position,
    threat_near_poland,
    POLAND_POLYGON,
)


class TestPointInPolygon(unittest.TestCase):
    def test_warsaw_inside_poland(self):
        self.assertTrue(point_in_polygon(52.23, 21.01, POLAND_POLYGON))

    def test_rzeszow_inside_poland(self):
        self.assertTrue(point_in_polygon(50.04, 22.00, POLAND_POLYGON))

    def test_lviv_outside_poland(self):
        self.assertFalse(point_in_polygon(49.84, 24.03, POLAND_POLYGON))

    def test_odessa_far_from_poland(self):
        self.assertFalse(point_in_polygon(46.48, 30.74, POLAND_POLYGON))


class TestDistanceToPoland(unittest.TestCase):
    def test_inside_returns_zero(self):
        self.assertEqual(distance_to_poland_km(52.23, 21.01), 0.0)

    def test_odessa_is_far(self):
        distance = distance_to_poland_km(46.48, 30.74)
        self.assertGreater(distance, 200)


class TestPredictPosition(unittest.TestCase):
    def test_returns_none_without_speed(self):
        self.assertIsNone(predict_position(50.0, 22.0, 90.0, None, 15))

    def test_moves_east_with_east_bearing(self):
        lat, lon = predict_position(50.0, 22.0, 90.0, 120.0, 60)
        self.assertIsNotNone(lat)
        self.assertGreater(lon, 22.0)


class TestThreatNearPoland(unittest.TestCase):
    def test_inside_poland_matches(self):
        result = threat_near_poland(
            52.23,
            21.01,
            None,
            None,
            alert_km=50,
            lookahead_minutes=15,
        )
        self.assertTrue(result.matches)
        self.assertTrue(result.inside_poland)
        self.assertEqual(result.distance_km, 0.0)

    def test_odessa_does_not_match(self):
        result = threat_near_poland(
            46.48,
            30.74,
            None,
            None,
            alert_km=50,
            lookahead_minutes=15,
        )
        self.assertFalse(result.matches)

    def test_lookahead_can_match_approach(self):
        # West of Lviv, heading west toward Poland at high speed.
        result = threat_near_poland(
            49.90,
            23.20,
            270.0,
            600.0,
            alert_km=50,
            lookahead_minutes=30,
        )
        self.assertTrue(result.matches)


if __name__ == "__main__":
    unittest.main()
