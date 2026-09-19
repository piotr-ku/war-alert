"""
    NEPTUN threat source for war-alert.

    Public REST API: https://neptun.in.ua/developers
    No API key required. Poll GET /api/v1/threats on the global sleep_delay.

    Filter options in war-alert.yml under neptun:
        enabled — enable this source (default false).
        alert_km — notify when within this distance of Poland (default 50).
        lookahead_minutes — dead-reckon position for approach check (15).
        skip_advisory — drop advisory observations (default true).
        types — threat types to include (default uav,missile,ballistic,kab).

    Processors: [ProcessorUnique] only — no LLM classification.
    Dedup hash includes threat id and rounded position so movement
    triggers a new notification on the next poll.
"""

import json
import logging
import time
from typing import Any

import requests

import config
from processors.base import Content, Processor
from processors.unique import ProcessorUnique
from sources.base import Source
from sources.neptun_geo import PolandProximity, threat_near_poland

THREATS_URL = "https://neptun.in.ua/api/v1/threats"
ATTRIBUTION_URL = "https://neptun.in.ua/"
REQUEST_TIMEOUT = 30

TYPE_LABELS = {
    "uav": "BPL",
    "missile": "Rakieta",
    "ballistic": "Rakieta balistyczna",
    "kab": "KAB",
    "recon": "Rozpoznanie",
    "mig31k": "MiG-31K",
    "unknown": "Nieznane",
}


def _parse_float(value: Any) -> float | None:
    """
        Parse a numeric API field, returning None when invalid.
    """
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class NeptunThreat(Content):
    """
        A NEPTUN threat item ready for notification.
    """
    def __init__(
        self,
        threat_id: str,
        title: str,
        description: str,
        pub_date: str,
        link: str,
        lat: float,
        lon: float,
    ):
        """
            Initialize a NEPTUN threat content item.
        """
        self.threat_id = threat_id
        self.title = title
        self.description = description
        self.pubDate = pub_date
        self.link = link
        self.lat = lat
        self.lon = lon

    def __str__(self) -> str:
        """
            Dedup key: threat id plus position rounded to ~100 m.
        """
        return (
            f"neptun:{self.threat_id}:"
            f"{self.lat:.3f}:{self.lon:.3f}"
        )


class SourceNeptun(Source):
    """
        Fetch active NEPTUN threats and filter by Poland proximity.
    """
    def __init__(self, logger: logging.Logger):
        """
            Initialize the NEPTUN source.
        """
        self.logger = logger
        self.url = THREATS_URL

    def processors(self) -> list[Processor]:
        """
            Return a list of processors.
        """
        return [ProcessorUnique]

    def fetch(self, logger: logging.Logger) -> list[NeptunThreat]:
        """
            Return threats that are over or approaching Poland.
        """
        self.logger.info(json.dumps({
            "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
            "source": "Neptun",
            "url": self.url,
        }))

        try:
            response = requests.get(self.url, timeout=REQUEST_TIMEOUT)
        except Exception as exc:
            self.logger.error(json.dumps({
                "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
                "url": self.url,
                "msg": "Error fetching threats from NEPTUN",
                "exception": str(exc),
            }, ensure_ascii=False))
            return []

        if response.status_code != 200:
            self.logger.error(json.dumps({
                "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
                "url": self.url,
                "msg": "Error fetching threats from NEPTUN",
                "status": response.status_code,
                "response": response.text,
            }, ensure_ascii=False))
            return []

        try:
            payload = response.json()
            threats = payload.get("threats", [])
        except Exception as exc:
            self.logger.error(json.dumps({
                "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
                "url": self.url,
                "msg": "Error parsing threats from NEPTUN",
                "exception": str(exc),
            }, ensure_ascii=False))
            return []

        if not isinstance(threats, list):
            return []

        allowed_types = set(config.neptun_types())
        skip_advisory = config.neptun_skip_advisory()
        alert_km = config.neptun_alert_km()
        lookahead = config.neptun_lookahead_minutes()

        matched: list[NeptunThreat] = []
        for raw in threats:
            item = self._prepare_threat(
                raw,
                allowed_types,
                skip_advisory,
                alert_km,
                lookahead,
            )
            if item is not None:
                matched.append(item)

        self.logger.info(json.dumps({
            "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
            "source": "Neptun",
            "msg": "NEPTUN fetch complete",
            "fetched": len(threats),
            "matched": len(matched),
        }, ensure_ascii=False))

        return matched

    def _prepare_threat(
        self,
        threat: dict[str, Any],
        allowed_types: set[str],
        skip_advisory: bool,
        alert_km: float,
        lookahead_minutes: float,
    ) -> NeptunThreat | None:
        """
            Filter one threat and build notification content.
        """
        if threat.get("status") != "active":
            return None
        if threat.get("areaOnly"):
            return None
        if skip_advisory and threat.get("advisory"):
            return None

        threat_type = str(threat.get("type", "unknown"))
        if threat_type not in allowed_types:
            return None

        lat = _parse_float(threat.get("lat"))
        lon = _parse_float(threat.get("lon"))
        if lat is None or lon is None:
            return None

        bearing, speed = self._velocity(threat)
        proximity = threat_near_poland(
            lat,
            lon,
            bearing,
            speed,
            alert_km,
            lookahead_minutes,
        )
        if not proximity.matches:
            return None

        threat_id = str(threat.get("id", ""))
        if threat_id == "":
            return None

        title = self._build_title(threat, threat_type, proximity)
        description = self._build_description(threat, proximity, bearing, speed)
        pub_date = str(threat.get("updatedAt", threat.get("confirmedAt", "")))
        if pub_date == "":
            pub_date = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())

        return NeptunThreat(
            threat_id,
            title,
            description,
            pub_date,
            ATTRIBUTION_URL,
            lat,
            lon,
        )

    def _velocity(
        self,
        threat: dict[str, Any],
    ) -> tuple[float | None, float | None]:
        """
            Extract bearing and speed from a NEPTUN threat payload.
        """
        velocity = threat.get("velocity")
        if isinstance(velocity, dict):
            bearing = _parse_float(velocity.get("bearingDeg"))
            speed = _parse_float(velocity.get("speedKmh"))
            if bearing is not None and speed is not None:
                return bearing, speed

        heading = _parse_float(threat.get("heading"))
        if heading is not None:
            return heading, None

        return None, None

    def _type_label(self, threat: dict[str, Any], threat_type: str) -> str:
        """
            Return a Polish label for the threat type.
        """
        title = threat.get("title")
        if isinstance(title, str) and title.strip() != "":
            return title.strip()
        return TYPE_LABELS.get(threat_type, threat_type)

    def _build_title(
        self,
        threat: dict[str, Any],
        threat_type: str,
        proximity: PolandProximity,
    ) -> str:
        """
            Build a short notification title.
        """
        label = self._type_label(threat, threat_type)
        place = self._place_name(threat)

        if proximity.inside_poland:
            if place:
                return f"{label} nad Polską — {place}"
            return f"{label} nad Polską"

        distance = int(round(proximity.distance_km))
        if place:
            return f"{label} {distance} km od Polski — {place}"
        return f"{label} {distance} km od Polski"

    def _build_description(
        self,
        threat: dict[str, Any],
        proximity: PolandProximity,
        bearing: float | None,
        speed: float | None,
    ) -> str:
        """
            Build the notification body with course and NEPTUN summary.
        """
        parts: list[str] = []

        if bearing is not None:
            parts.append(f"Kurs: {int(round(bearing))}°")
        if speed is not None:
            parts.append(f"~{int(round(speed))} km/h")

        region = threat.get("region")
        district = threat.get("district")
        locality = threat.get("locality")
        location_bits = [
            str(value).strip()
            for value in (locality, district, region)
            if isinstance(value, str) and value.strip() != ""
        ]
        if location_bits:
            parts.append(", ".join(location_bits))

        if proximity.predicted_inside and not proximity.inside_poland:
            parts.append("Prognoza: wejście nad Polskę")
        elif (
            proximity.predicted_distance_km is not None
            and proximity.predicted_distance_km <= config.neptun_alert_km()
            and not proximity.inside_poland
        ):
            predicted = int(round(proximity.predicted_distance_km))
            parts.append(f"Prognoza: {predicted} km od Polski")

        explanation = threat.get("explanationShort")
        if isinstance(explanation, str) and explanation.strip() != "":
            parts.append(explanation.strip())

        parts.append("Dane: NEPTUN (neptun.in.ua)")
        return ". ".join(parts)

    def _place_name(self, threat: dict[str, Any]) -> str:
        """
            Return the best human-readable place name from the threat.
        """
        for key in ("locality", "district", "region"):
            value = threat.get(key)
            if isinstance(value, str) and value.strip() != "":
                return value.strip()
        return ""
