"""
    Geographic helpers for NEPTUN threat proximity to Poland.

    Uses a simplified Poland polygon (stdlib math only). Points inside
    count as 0 km from the border. Lookahead dead-reckons position
    along bearing/speed like NEPTUN.predict().
"""

import math
from typing import NamedTuple

# Simplified Poland outline (lat, lon), clockwise.
POLAND_POLYGON: list[tuple[float, float]] = [
    (54.84, 14.12),
    (54.77, 16.92),
    (54.59, 18.80),
    (54.44, 19.27),
    (54.35, 22.90),
    (53.95, 23.65),
    (52.85, 23.55),
    (51.95, 24.15),
    (50.88, 23.95),
    (49.78, 23.65),
    (49.39, 22.55),
    (49.39, 18.85),
    (49.02, 17.55),
    (50.25, 16.45),
    (50.88, 15.02),
    (51.38, 14.98),
    (51.38, 14.72),
    (52.35, 14.12),
    (53.05, 14.25),
    (54.84, 14.12),
]

EARTH_RADIUS_KM = 6371.0


class PolandProximity(NamedTuple):
    """
        Result of checking a point against Poland.
    """
    matches: bool
    inside_poland: bool
    distance_km: float
    predicted_inside: bool
    predicted_distance_km: float | None


def haversine_km(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:
    """
        Return great-circle distance in kilometres.
    """
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def point_in_polygon(
    lat: float,
    lon: float,
    polygon: list[tuple[float, float]],
) -> bool:
    """
        Ray-casting test for a point inside a lat/lon polygon.
    """
    inside = False
    count = len(polygon)
    j = count - 1

    for i in range(count):
        lat_i, lon_i = polygon[i]
        lat_j, lon_j = polygon[j]

        crosses = (
            (lon_i > lon) != (lon_j > lon)
            and lat
            < (lat_j - lat_i) * (lon - lon_i) / (lon_j - lon_i) + lat_i
        )
        if crosses:
            inside = not inside
        j = i

    return inside


def _distance_point_to_segment_km(
    lat: float,
    lon: float,
    lat_a: float,
    lon_a: float,
    lat_b: float,
    lon_b: float,
    steps: int = 20,
) -> float:
    """
        Approximate distance from a point to a polygon edge segment.
    """
    minimum = float("inf")
    for step in range(steps + 1):
        fraction = step / steps
        edge_lat = lat_a + fraction * (lat_b - lat_a)
        edge_lon = lon_a + fraction * (lon_b - lon_a)
        distance = haversine_km(lat, lon, edge_lat, edge_lon)
        if distance < minimum:
            minimum = distance
    return minimum


def distance_to_poland_km(lat: float, lon: float) -> float:
    """
        Return 0 when inside Poland, else km to the nearest border edge.
    """
    if point_in_polygon(lat, lon, POLAND_POLYGON):
        return 0.0

    minimum = float("inf")
    count = len(POLAND_POLYGON)
    for index in range(count - 1):
        lat_a, lon_a = POLAND_POLYGON[index]
        lat_b, lon_b = POLAND_POLYGON[index + 1]
        distance = _distance_point_to_segment_km(
            lat,
            lon,
            lat_a,
            lon_a,
            lat_b,
            lon_b,
        )
        if distance < minimum:
            minimum = distance
    return minimum


def dest(
    lat: float,
    lon: float,
    bearing_deg: float,
    distance_km: float,
) -> tuple[float, float]:
    """
        Dead-reckon a point along bearing and distance.
    """
    if distance_km <= 0:
        return lat, lon

    lat1 = math.radians(lat)
    lon1 = math.radians(lon)
    bearing = math.radians(bearing_deg)
    angular = distance_km / EARTH_RADIUS_KM

    lat2 = math.asin(
        math.sin(lat1) * math.cos(angular)
        + math.cos(lat1) * math.sin(angular) * math.cos(bearing)
    )
    lon2 = lon1 + math.atan2(
        math.sin(bearing) * math.sin(angular) * math.cos(lat1),
        math.cos(angular) - math.sin(lat1) * math.sin(lat2),
    )
    return math.degrees(lat2), math.degrees(lon2)


def predict_position(
    lat: float,
    lon: float,
    bearing_deg: float | None,
    speed_kmh: float | None,
    minutes: float,
) -> tuple[float, float] | None:
    """
        Return predicted lat/lon after minutes at speed, or None if unknown.
    """
    if bearing_deg is None or speed_kmh is None or speed_kmh <= 0:
        return None
    if minutes <= 0:
        return lat, lon

    distance_km = speed_kmh * (minutes / 60.0)
    return dest(lat, lon, bearing_deg, distance_km)


def threat_near_poland(
    lat: float,
    lon: float,
    bearing_deg: float | None,
    speed_kmh: float | None,
    alert_km: float,
    lookahead_minutes: float,
) -> PolandProximity:
    """
        Return whether a threat is inside Poland or within alert_km.

        Also checks the lookahead position when bearing and speed exist.
    """
    inside = point_in_polygon(lat, lon, POLAND_POLYGON)
    distance = distance_to_poland_km(lat, lon)

    predicted = predict_position(
        lat,
        lon,
        bearing_deg,
        speed_kmh,
        lookahead_minutes,
    )
    predicted_inside = False
    predicted_distance: float | None = None
    if predicted is not None:
        pred_lat, pred_lon = predicted
        predicted_inside = point_in_polygon(pred_lat, pred_lon, POLAND_POLYGON)
        predicted_distance = distance_to_poland_km(pred_lat, pred_lon)

    matches = (
        inside
        or distance <= alert_km
        or predicted_inside
        or (
            predicted_distance is not None
            and predicted_distance <= alert_km
        )
    )

    return PolandProximity(
        matches=matches,
        inside_poland=inside,
        distance_km=distance,
        predicted_inside=predicted_inside,
        predicted_distance_km=predicted_distance,
    )
