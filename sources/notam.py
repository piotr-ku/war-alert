import base64
import json
import logging
import os
import re
import threading
import time
from typing import Any

import requests

from processors.base import Content, Processor
from processors.unique import ProcessorUnique
from sources.base import Source

DEFAULT_BASE_URL = "https://api-nms.aim.faa.gov/nmsapi"
DEFAULT_AUTH_URL = "https://api-nms.aim.faa.gov/v1/auth/token"
DEFAULT_LOCATIONS = "EPWW EPWA"
DEFAULT_QCODES = "QATLC,QRTCA,QRTCL,QRRCA"
DEFAULT_REQUEST_DELAY = 1.1
MAX_RATE_LIMIT_RETRIES = 2
NOTAM_LINK = "https://notams.aim.faa.gov/notamSearch/"

_token_lock = threading.Lock()
_token: str | None = None
_token_expiry: float = 0.0

_QCODE_LINE_RE = re.compile(r"Q\)\s+\w+/([A-Z]{5})/", re.IGNORECASE)
_QCODE_PLACEHOLDERS = frozenset({"QXXXX", ""})


class Notam(Content):
    """
        A class to represent a NOTAM.
    """
    def __init__(self, title, description, pubDate, link):
        """
            Initialize a NOTAM.
        """
        self.title = title
        self.description = description
        self.pubDate = pubDate
        self.link = link
        self._dedup_key = description

    def __str__(self) -> str:
        """
            Return a string representation used for deduplication.
        """
        return self._dedup_key


def _normalize_whitespace(text: str) -> str:
    return " ".join(text.split())


def _parse_qcode_prefixes(raw: str) -> list[str]:
    prefixes = []
    for part in raw.split(","):
        code = part.strip().upper()
        if not code:
            continue
        if not code.startswith("Q"):
            code = f"Q{code}"
        prefixes.append(code)
    return prefixes


def _qcode_matches(code: str | None, prefixes: list[str]) -> bool:
    if code is None or not prefixes:
        return False
    normalized = code.strip().upper()
    if not normalized.startswith("Q"):
        normalized = f"Q{normalized}"
    return any(normalized.startswith(prefix) for prefix in prefixes)


def _extract_qcode_from_text(text: str) -> str | None:
    match = _QCODE_LINE_RE.search(text)
    if match is None:
        return None
    return match.group(1).upper()


def _normalize_selection_code(value: Any) -> str | None:
    if value is None:
        return None
    code = str(value).strip().upper()
    if code in _QCODE_PLACEHOLDERS:
        return None
    if not code.startswith("Q"):
        code = f"Q{code}"
    return code


def _extract_qcode(notam: dict, core: dict) -> str | None:
    qcode = _normalize_selection_code(notam.get("selectionCode"))
    if qcode is not None:
        return qcode

    text = notam.get("text", "")
    if not isinstance(text, str):
        text = str(text)
    qcode = _extract_qcode_from_text(text)
    if qcode is not None:
        return qcode

    translations = core.get("notamTranslation", [])
    if not isinstance(translations, list):
        return None

    for translation in translations:
        if not isinstance(translation, dict):
            continue
        if translation.get("type") != "ICAO":
            continue
        for field in ("formattedText", "simpleText"):
            value = translation.get(field)
            if not isinstance(value, str):
                continue
            qcode = _extract_qcode_from_text(value)
            if qcode is not None:
                return qcode
    return None


def _parse_expires_in(value: Any) -> int:
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return 0


def _auth_url() -> str:
    return os.environ.get("FAA_NMS_AUTH_URL", DEFAULT_AUTH_URL)


def _log_notam_info(logger: logging.Logger, payload: dict) -> None:
    logger.info(json.dumps({
        "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        "source": "NOTAM",
        **payload,
    }, ensure_ascii=False))


def _get_access_token(logger: logging.Logger) -> str | None:
    global _token, _token_expiry

    client_id = os.environ.get("FAA_NMS_CLIENT_ID", "")
    client_secret = os.environ.get("FAA_NMS_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        return None

    auth_url = _auth_url()

    with _token_lock:
        if _token is not None and time.time() < _token_expiry:
            _log_notam_info(logger, {
                "msg": "FAA NMS token reused",
                "auth_url": auth_url,
            })
            return _token
        credentials = base64.b64encode(
            f"{client_id}:{client_secret}".encode("utf-8"),
        ).decode("ascii")
        headers = {
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/x-www-form-urlencoded",
        }

        try:
            response = requests.post(
                auth_url,
                headers=headers,
                data={"grant_type": "client_credentials"},
                timeout=30,
            )
        except Exception as e:
            logger.error(json.dumps({
                "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
                "source": "NOTAM",
                "msg": "Error requesting FAA NMS token",
                "exception": str(e),
            }, ensure_ascii=False))
            return None

        if response.status_code != 200:
            logger.error(json.dumps({
                "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
                "source": "NOTAM",
                "msg": "Error requesting FAA NMS token",
                "status": response.status_code,
                "response": response.text,
            }, ensure_ascii=False))
            return None

        try:
            payload = response.json()
            access_token = payload["access_token"]
            expires_in = _parse_expires_in(payload.get("expires_in", 3600))
        except (KeyError, json.JSONDecodeError) as e:
            logger.error(json.dumps({
                "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
                "source": "NOTAM",
                "msg": "Error parsing FAA NMS token response",
                "exception": str(e),
            }, ensure_ascii=False))
            return None

        _token = access_token
        _token_expiry = time.time() + max(expires_in - 60, 0)
        _log_notam_info(logger, {
            "msg": "FAA NMS token acquired",
            "auth_url": auth_url,
            "expires_in": expires_in,
        })
        return _token


def _parse_notam_fields(feature: dict) -> dict | None:
    properties = feature.get("properties", {})
    core = properties.get("coreNOTAMData", {})
    notam = core.get("notam", {})
    if not isinstance(notam, dict):
        return None

    number = notam.get("number")
    location = notam.get("location")
    text = notam.get("text", "")
    if not number or not location:
        return None

    if not isinstance(text, str):
        text = str(text)

    qcode = _extract_qcode(notam, core)

    pub_date = notam.get("issued") or notam.get("effectiveStart")
    if pub_date is None:
        pub_date = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())

    return {
        "number": str(number).strip(),
        "location": str(location).strip().upper(),
        "text": text.strip(),
        "qcode": qcode,
        "pubDate": str(pub_date),
    }


def _locations() -> list[str]:
    raw = os.environ.get("NOTAM_LOCATIONS", DEFAULT_LOCATIONS)
    return [location.strip().upper() for location in raw.split() if location.strip()]


def _qcode_prefixes() -> list[str]:
    raw = os.environ.get("NOTAM_QCODES", DEFAULT_QCODES)
    return _parse_qcode_prefixes(raw)


def _classification() -> str | None:
    raw = os.environ.get("NOTAM_CLASSIFICATION")
    if raw is None:
        return None
    value = raw.strip().upper()
    if value == "":
        return None
    return value


def _request_delay() -> float:
    raw = os.environ.get("NOTAM_REQUEST_DELAY")
    if raw is None or raw.strip() == "":
        return DEFAULT_REQUEST_DELAY
    try:
        return max(float(raw), 0.0)
    except ValueError:
        return DEFAULT_REQUEST_DELAY


def _parse_nms_payload(
    payload: dict,
    logger: logging.Logger,
    location: str,
) -> list[dict]:
    status = payload.get("status", "")
    if not isinstance(status, str) or status.lower() != "success":
        logger.error(json.dumps({
            "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
            "source": "NOTAM",
            "location": location,
            "msg": "FAA NMS returned non-success status",
            "status": status,
            "errors": payload.get("errors", []),
        }, ensure_ascii=False))
        return []

    data = payload.get("data")
    if not isinstance(data, dict):
        return []

    geojson = data.get("geojson", [])
    if not isinstance(geojson, list):
        return []

    fields_list = []
    for feature in geojson:
        if not isinstance(feature, dict):
            continue
        fields = _parse_notam_fields(feature)
        if fields is not None:
            fields_list.append(fields)
    return fields_list


class SourceNotam(Source):
    """
        A class to represent the FAA NMS NOTAM source.
    """
    def __init__(self, logger: logging.Logger):
        """
            Initialize the NOTAM source.
        """
        self.logger = logger
        self.base_url = os.environ.get("FAA_NMS_BASE_URL", DEFAULT_BASE_URL).rstrip("/")

    def processors(self) -> list[Processor]:
        """
            Return a list of processors.
        """
        return [ProcessorUnique]

    def fetch(self, logger) -> list[Notam]:
        """
            Return a list of NOTAMs matching configured Q-code filters.
        """
        locations = _locations()
        qcode_prefixes = _qcode_prefixes()
        self.logger.info(json.dumps({
            "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
            "source": "NOTAM",
            "locations": locations,
            "qcodes": qcode_prefixes,
        }))

        token = _get_access_token(self.logger)
        if token is None:
            return []

        notams: list[Notam] = []
        seen_keys: set[str] = set()
        fetched_count = 0

        delay = _request_delay()
        for index, location in enumerate(locations):
            location_notams = self._fetch_location_notams(location, token)
            fetched_count += len(location_notams)
            for fields in location_notams:
                if not _qcode_matches(fields["qcode"], qcode_prefixes):
                    continue

                dedup_key = _normalize_whitespace(
                    f"{fields['number']} {fields['location']}: {fields['text']}",
                )
                if dedup_key in seen_keys:
                    continue
                seen_keys.add(dedup_key)
                notams.append(self._prepare_notam(fields, dedup_key))

            if index < len(locations) - 1:
                time.sleep(delay)

        _log_notam_info(self.logger, {
            "msg": "NOTAM fetch complete",
            "base_url": self.base_url,
            "fetched": fetched_count,
            "matched": len(notams),
        })

        return notams

    def _fetch_location_notams(
        self,
        location: str,
        token: str,
    ) -> list[dict]:
        url = f"{self.base_url}/v1/notams"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "nmsResponseFormat": "GEOJSON",
        }
        params = {"location": location}
        classification = _classification()
        if classification is not None:
            params["classification"] = classification

        delay = _request_delay()
        max_attempts = MAX_RATE_LIMIT_RETRIES + 1
        response = None

        for attempt in range(max_attempts):
            try:
                response = requests.get(url, headers=headers, params=params, timeout=30)
            except Exception as e:
                self.logger.error(json.dumps({
                    "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
                    "source": "NOTAM",
                    "location": location,
                    "msg": "Error fetching NOTAMs from FAA NMS",
                    "exception": str(e),
                }, ensure_ascii=False))
                return []

            if response.status_code == 429 and attempt < max_attempts - 1:
                self.logger.warning(json.dumps({
                    "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
                    "source": "NOTAM",
                    "location": location,
                    "msg": "FAA NMS rate limit hit, retrying",
                    "retry": attempt + 1,
                }, ensure_ascii=False))
                time.sleep(delay)
                continue
            break

        if response is None or response.status_code != 200:
            self.logger.error(json.dumps({
                "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
                "source": "NOTAM",
                "location": location,
                "msg": "Error fetching NOTAMs from FAA NMS",
                "status": response.status_code if response is not None else None,
                "response": response.text if response is not None else "",
            }, ensure_ascii=False))
            return []

        try:
            payload = response.json()
        except json.JSONDecodeError as e:
            self.logger.error(json.dumps({
                "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
                "source": "NOTAM",
                "location": location,
                "msg": "Error parsing FAA NMS NOTAM response",
                "exception": str(e),
            }, ensure_ascii=False))
            return []

        fields_list = _parse_nms_payload(payload, self.logger, location)
        _log_notam_info(self.logger, {
            "msg": "FAA NMS NOTAMs fetched",
            "base_url": self.base_url,
            "location": location,
            "count": len(fields_list),
            "notams": [
                {
                    "number": fields["number"],
                    "location": fields["location"],
                    "qcode": fields["qcode"],
                }
                for fields in fields_list
            ],
        })
        return fields_list

    def _prepare_notam(self, fields: dict, dedup_key: str) -> Notam:
        """
            Prepare a NOTAM content object.
        """
        qcode = fields["qcode"] or "unknown"
        title = f"NOTAM {fields['number']} ({fields['location']}, {qcode})"
        description = fields["text"]
        link = f"{NOTAM_LINK}?query={fields['location']}"
        notam = Notam(title, description, fields["pubDate"], link)
        notam._dedup_key = dedup_key
        return notam
