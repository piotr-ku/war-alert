"""
    FAA NMS NOTAM source for war-alert.

    Environment variables:
        FAA_NMS_CLIENT_ID, FAA_NMS_CLIENT_SECRET — enable this source.
        FAA_NMS_BASE_URL — API base (default production NMS API).
        FAA_NMS_AUTH_URL — OAuth token URL (default production).
        NOTAM_LOCATIONS — space-separated ICAO codes (default EPWW EPWA).
        NOTAM_QCODES — comma-separated Q-code prefixes to match.
        NOTAM_PASSTHROUGH_QCODES — always alert, skip text filter
            (default QATLC,QRPCA for TMA/CTR and Ukraine NPZ notices).
        NOTAM_TEXT_EXCLUDE — comma substrings; routine TRA/PJE/UAV/AUP
            noise is dropped when matched Q-code is not passthrough.
            Set to empty to disable text filtering.
        NOTAM_CLASSIFICATION — optional API filter: INTERNATIONAL,
            DOMESTIC, MILITARY, LOCAL_MILITARY, or FDC. Unset = all active.
        NOTAM_REQUEST_DELAY — seconds between location queries (default 1.1;
            staging API enforces ~1 req/s per client).

    Filtering pipeline:
        1. Q-code must match NOTAM_QCODES.
        2. Passthrough Q-codes skip the text exclude stage.
        3. Other matches are dropped when text contains any
           NOTAM_TEXT_EXCLUDE substring.
        4. Within-poll dedup by NOTAM number + location + text.
        5. ProcessorUnique dedup across polls (MD5 of content text).

    Processors: [ProcessorUnique] only — no LLM classification.

    Structured logs (source NOTAM):
        info — NOTAM source configured (once), FAA NMS token acquired,
            NOTAM matched, NOTAM noise filtered (reason histogram),
            NOTAM fetch complete (fetched, skipped_qcode, filtered,
            duplicates, matched, duration_ms, per-location counts).
        debug — per-item NOTAM filtered as noise (full text), full
            per-location NOTAM list from FAA NMS.

    Standing restrictions (e.g. EPR129) are reported once on first sight;
    ProcessorUnique logs Content skipped as duplicate at debug thereafter.

    Items are marked seen after processing (including classifier rejection
    on other sources) or after at least one notifier succeeds; failed
    deliveries are retried on the next poll. On first run many NOTAMs may
    match at once — Telegram sends are throttled via TELEGRAM_MIN_INTERVAL
    in notifiers/telegram.py.
"""

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
DEFAULT_QCODES = "QATLC,QRTCA,QRTCL,QRRCA,QRPCA,QRMXX"
DEFAULT_PASSTHROUGH_QCODES = "QATLC,QRPCA"
DEFAULT_TEXT_EXCLUDE = (
    "PJE,PARAGLID,UAV FLT,UAS FLT,"
    "UNMANNED AERIAL VEHICLES FLIGHTS,"
    "AIRSPACE USE PLAN,AUP,AIP SUP,"
    "AREA MANAGER,"
    "TEMPORARY RESERVED,TEMPORARY RESTRICTED,"
    "AVBL FOR REQUEST,TEMPORARY AVBL"
)
DEFAULT_REQUEST_DELAY = 1.1
MAX_RATE_LIMIT_RETRIES = 2
NOTAM_LINK = "https://notams.aim.faa.gov/notamSearch/"

_token_lock = threading.Lock()
_token: str | None = None
_token_expiry: float = 0.0
_logged_source_config = False

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
    """
        Resolve a Q-code from selectionCode, text, or ICAO translation.
    """
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


def _log_notam(
    logger: logging.Logger,
    payload: dict,
    level: int = logging.INFO,
) -> None:
    logger.log(level, json.dumps({
        "time": time.strftime(
            "%Y-%m-%dT%H:%M:%S",
            time.localtime(),
        ),
        "source": "NOTAM",
        **payload,
    }, ensure_ascii=False))


def _log_source_config_once(logger: logging.Logger, base_url: str) -> None:
    global _logged_source_config
    if _logged_source_config:
        return
    _logged_source_config = True
    _log_notam(logger, {
        "msg": "NOTAM source configured",
        "locations": _locations(),
        "qcodes": _qcode_prefixes(),
        "passthrough_qcodes": _passthrough_qcodes(),
        "base_url": base_url,
        "auth_url": _auth_url(),
        "classification": _classification(),
    })


def _get_access_token(logger: logging.Logger) -> str | None:
    """
        Return a cached FAA NMS OAuth token or request a new one.
    """
    global _token, _token_expiry

    client_id = os.environ.get("FAA_NMS_CLIENT_ID", "")
    client_secret = os.environ.get("FAA_NMS_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        return None

    auth_url = _auth_url()

    with _token_lock:
        # Reuse the token until one minute before expiry
        if _token is not None and time.time() < _token_expiry:
            _log_notam(logger, {
                "msg": "FAA NMS token reused",
                "auth_url": auth_url,
            }, level=logging.DEBUG)
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
            _log_notam(logger, {
                "msg": "Error requesting FAA NMS token",
                "auth_url": auth_url,
                "exception": str(e),
            }, level=logging.ERROR)
            return None

        if response.status_code != 200:
            _log_notam(logger, {
                "msg": "Error requesting FAA NMS token",
                "auth_url": auth_url,
                "status": response.status_code,
                "response": response.text,
            }, level=logging.ERROR)
            return None

        try:
            payload = response.json()
            access_token = payload["access_token"]
            expires_in = _parse_expires_in(payload.get("expires_in", 3600))
        except (KeyError, json.JSONDecodeError) as e:
            _log_notam(logger, {
                "msg": "Error parsing FAA NMS token response",
                "auth_url": auth_url,
                "exception": str(e),
            }, level=logging.ERROR)
            return None

        _token = access_token
        _token_expiry = time.time() + max(expires_in - 60, 0)
        _log_notam(logger, {
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
        pub_date = time.strftime(
            "%Y-%m-%dT%H:%M:%S",
            time.localtime(),
        )

    return {
        "number": str(number).strip(),
        "location": str(location).strip().upper(),
        "text": text.strip(),
        "qcode": qcode,
        "pubDate": str(pub_date),
    }


def _locations() -> list[str]:
    raw = os.environ.get("NOTAM_LOCATIONS", DEFAULT_LOCATIONS)
    return [
        location.strip().upper()
        for location in raw.split()
        if location.strip()
    ]


def _qcode_prefixes() -> list[str]:
    raw = os.environ.get("NOTAM_QCODES", DEFAULT_QCODES)
    return _parse_qcode_prefixes(raw)


def _passthrough_qcodes() -> list[str]:
    raw = os.environ.get("NOTAM_PASSTHROUGH_QCODES")
    if raw is None:
        return _parse_qcode_prefixes(DEFAULT_PASSTHROUGH_QCODES)
    if raw.strip() == "":
        return []
    return _parse_qcode_prefixes(raw)


def _exclude_patterns() -> list[str]:
    raw = os.environ.get("NOTAM_TEXT_EXCLUDE")
    if raw is None:
        return [
            p.strip().upper()
            for p in DEFAULT_TEXT_EXCLUDE.split(",")
            if p.strip()
        ]
    if raw.strip() == "":
        return []
    return [
        p.strip().upper()
        for p in raw.split(",")
        if p.strip()
    ]


def _is_passthrough(
    qcode: str | None,
    prefixes: list[str] | None = None,
) -> bool:
    """
        Return True when the Q-code bypasses text noise filters.
    """
    if prefixes is None:
        prefixes = _passthrough_qcodes()
    return _qcode_matches(qcode, prefixes)


def _exclude_reason(
    text: str,
    patterns: list[str] | None = None,
) -> str | None:
    """
        Return the first matching noise pattern or None.
    """
    if patterns is None:
        patterns = _exclude_patterns()
    upper = _normalize_whitespace(text).upper()
    for pattern in patterns:
        if pattern in upper:
            return pattern
    return None


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


def _classify_notam(
    fields: dict,
    qcode_prefixes: list[str],
    passthrough_prefixes: list[str],
    exclude_patterns: list[str],
) -> tuple[str, bool, str | None]:
    """
        Classify a NOTAM as skip, noise, or keep.

        Returns (decision, passthrough, noise_reason).
    """
    if not _qcode_matches(fields["qcode"], qcode_prefixes):
        return "skip", False, None

    passthrough = _is_passthrough(
        fields["qcode"],
        passthrough_prefixes,
    )
    if not passthrough:
        reason = _exclude_reason(fields["text"], exclude_patterns)
        if reason is not None:
            return "noise", passthrough, reason

    return "keep", passthrough, None


def _parse_nms_payload(
    payload: dict,
    logger: logging.Logger,
    location: str,
) -> list[dict]:
    """
        Parse a successful FAA NMS GeoJSON response into field dicts.
    """
    status = payload.get("status", "")
    if not isinstance(status, str) or status.lower() != "success":
        _log_notam(logger, {
            "msg": "FAA NMS returned non-success status",
            "location": location,
            "status": status,
            "errors": payload.get("errors", []),
        }, level=logging.ERROR)
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
        self.base_url = os.environ.get(
            "FAA_NMS_BASE_URL",
            DEFAULT_BASE_URL,
        ).rstrip("/")

    def processors(self) -> list[Processor]:
        """
            Return a list of processors.
        """
        return [ProcessorUnique]

    def fetch(self, logger) -> list[Notam]:
        """
            Return a list of NOTAMs matching configured Q-code filters.
        """
        _log_source_config_once(self.logger, self.base_url)

        locations = _locations()
        qcode_prefixes = _qcode_prefixes()

        token = _get_access_token(self.logger)
        if token is None:
            return []

        notams: list[Notam] = []
        seen_keys: set[str] = set()
        fetched_count = 0
        filtered_count = 0
        skipped_qcode = 0
        duplicate_count = 0
        location_stats: dict[str, dict[str, int]] = {}
        noise_reasons: dict[str, int] = {}
        passthrough_prefixes = _passthrough_qcodes()
        exclude_patterns = _exclude_patterns()

        delay = _request_delay()
        started = time.monotonic()
        for index, location in enumerate(locations):
            # Fetch NOTAMs for one FIR location
            location_notams, duration_ms = self._fetch_location_notams(
                location,
                token,
            )
            fetched_count += len(location_notams)
            location_stats[location] = {
                "count": len(location_notams),
                "duration_ms": duration_ms,
            }
            for fields in location_notams:
                decision, passthrough, reason = _classify_notam(
                    fields,
                    qcode_prefixes,
                    passthrough_prefixes,
                    exclude_patterns,
                )
                if decision == "skip":
                    skipped_qcode += 1
                    continue
                if decision == "noise":
                    filtered_count += 1
                    noise_reasons[reason] = (
                        noise_reasons.get(reason, 0) + 1
                    )
                    _log_notam(self.logger, {
                        "msg": "NOTAM filtered as noise",
                        "number": fields["number"],
                        "location": fields["location"],
                        "qcode": fields["qcode"],
                        "reason": reason,
                        "text": fields["text"],
                    }, level=logging.DEBUG)
                    continue

                # Deduplicate within this poll cycle
                dedup_key = _normalize_whitespace(
                    f"{fields['number']} {fields['location']}: "
                    f"{fields['text']}",
                )
                if dedup_key in seen_keys:
                    duplicate_count += 1
                    continue
                seen_keys.add(dedup_key)
                notams.append(self._prepare_notam(fields, dedup_key))
                _log_notam(self.logger, {
                    "msg": "NOTAM matched",
                    "number": fields["number"],
                    "location": fields["location"],
                    "qcode": fields["qcode"],
                    "passthrough": passthrough,
                    "text": fields["text"],
                })

            # Pace requests between locations
            if index < len(locations) - 1:
                time.sleep(delay)

        if filtered_count:
            _log_notam(self.logger, {
                "msg": "NOTAM noise filtered",
                "count": filtered_count,
                "reasons": noise_reasons,
            })

        _log_notam(self.logger, {
            "msg": "NOTAM fetch complete",
            "fetched": fetched_count,
            "skipped_qcode": skipped_qcode,
            "filtered": filtered_count,
            "duplicates": duplicate_count,
            "matched": len(notams),
            "duration_ms": int((time.monotonic() - started) * 1000),
            "locations": location_stats,
        })

        return notams

    def _fetch_location_notams(
        self,
        location: str,
        token: str,
    ) -> tuple[list[dict], int]:
        """
            Fetch and parse NOTAMs for one location from FAA NMS.
        """
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
        started = time.monotonic()

        for attempt in range(max_attempts):
            try:
                response = requests.get(
                    url,
                    headers=headers,
                    params=params,
                    timeout=30,
                )
            except Exception as e:
                _log_notam(self.logger, {
                    "msg": "Error fetching NOTAMs from FAA NMS",
                    "location": location,
                    "exception": str(e),
                }, level=logging.ERROR)
                return [], int((time.monotonic() - started) * 1000)

            # Retry once after a rate-limit response
            if response.status_code == 429 and attempt < max_attempts - 1:
                _log_notam(self.logger, {
                    "msg": "FAA NMS rate limit hit, retrying",
                    "location": location,
                    "retry": attempt + 1,
                }, level=logging.WARNING)
                time.sleep(delay)
                continue
            break

        duration_ms = int((time.monotonic() - started) * 1000)

        if response is None or response.status_code != 200:
            status = (
                response.status_code
                if response is not None
                else None
            )
            body = response.text if response is not None else ""
            _log_notam(self.logger, {
                "msg": "Error fetching NOTAMs from FAA NMS",
                "location": location,
                "status": status,
                "response": body,
                "duration_ms": duration_ms,
            }, level=logging.ERROR)
            return [], duration_ms

        try:
            payload = response.json()
        except json.JSONDecodeError as e:
            _log_notam(self.logger, {
                "msg": "Error parsing FAA NMS NOTAM response",
                "location": location,
                "exception": str(e),
                "duration_ms": duration_ms,
            }, level=logging.ERROR)
            return [], duration_ms

        fields_list = _parse_nms_payload(payload, self.logger, location)
        _log_notam(self.logger, {
            "msg": "FAA NMS NOTAMs fetched",
            "location": location,
            "count": len(fields_list),
            "duration_ms": duration_ms,
            "notams": [
                {
                    "number": fields["number"],
                    "location": fields["location"],
                    "qcode": fields["qcode"],
                }
                for fields in fields_list
            ],
        }, level=logging.DEBUG)
        return fields_list, duration_ms

    def _prepare_notam(self, fields: dict, dedup_key: str) -> Notam:
        """
            Prepare a NOTAM content object.
        """
        qcode = fields["qcode"] or "unknown"
        title = (
            f"NOTAM {fields['number']} "
            f"({fields['location']}, {qcode})"
        )
        description = fields["text"]
        link = f"{NOTAM_LINK}?query={fields['location']}"
        notam = Notam(title, description, fields["pubDate"], link)
        notam._dedup_key = dedup_key
        return notam
