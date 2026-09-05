"""
    YAML runtime configuration for war-alert.

    Secrets and infrastructure stay in .env. Frequently changed options
    live in war-alert.yml. The first existing file from the search list
    is used:

        /etc/war-alert.yml
        ~/.config/war-alert/war-alert.yml
        ./war-alert.yml

    Call reload() at startup and before each poll iteration so edits take
    effect without restarting the process. On reload failure after a
    successful load, the previous config is kept.
"""

import json
import logging
import time
from pathlib import Path
from typing import Any

import yaml

DEFAULT_SLEEP_DELAY = 600
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
DEFAULT_OPENROUTER_MODEL = "openai/gpt-4o-mini"
DEFAULT_NOTAM_LOCATIONS = "EPWW EPWA"
DEFAULT_NOTAM_QCODES = "QATLC,QRTCA,QRTCL,QRRCA,QRPCA,QRMXX"
DEFAULT_NOTAM_PASSTHROUGH_QCODES = "QATLC,QRPCA"
DEFAULT_NOTAM_TEXT_EXCLUDE = (
    "PJE,PARAGLID,UAV FLT,UAS FLT,"
    "UNMANNED AERIAL VEHICLES FLIGHTS,"
    "AIRSPACE USE PLAN,AUP,AIP SUP,"
    "AREA MANAGER,"
    "TEMPORARY RESERVED,TEMPORARY RESTRICTED,"
    "AVBL FOR REQUEST,TEMPORARY AVBL"
)
DEFAULT_NTFY_PRIORITY = "high"

_config: dict[str, Any] = {}
_loaded = False
_search_paths_override: list[Path] | None = None

CONFIG_SEARCH_PATHS = (
    Path("/etc/war-alert.yml"),
    Path.home() / ".config" / "war-alert" / "war-alert.yml",
    Path("war-alert.yml"),
)


def _config_search_paths() -> list[Path]:
    if _search_paths_override is not None:
        return _search_paths_override
    return list(CONFIG_SEARCH_PATHS)


def _find_config_path() -> Path | None:
    for path in _config_search_paths():
        if path.is_file():
            return path
    return None


def _config_not_found_message() -> str:
    paths = ", ".join(str(path) for path in _config_search_paths())
    return f"Config file not found. Searched: {paths}"


def set_search_paths(paths: list[Path] | None) -> None:
    """
        Override config search paths. For tests only.
    """
    global _search_paths_override
    _search_paths_override = paths


def config_path() -> Path | None:
    """
        Return the config file path currently in use, if any.
    """
    return _find_config_path()


def _log(
    logger: logging.Logger,
    payload: dict,
    level: int = logging.ERROR,
) -> None:
    payload.setdefault(
        "time",
        time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
    )
    logger.log(level, json.dumps(payload, ensure_ascii=False))


def _normalize_root(payload: Any) -> dict[str, Any]:
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ValueError("Config file must contain a mapping at the root")
    return payload


def _validate_processor(root: dict[str, Any]) -> None:
    from processors.classify import parse_processor_names

    parse_processor_names(classification_processor_raw(root))


def _read_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"Config file not found: {path}")

    with path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle)

    root = _normalize_root(payload)
    _validate_processor(root)
    return root


def reset() -> None:
    """
        Clear loaded config. For tests only.
    """
    global _config, _loaded, _search_paths_override
    _config = {}
    _loaded = False
    _search_paths_override = None


def apply(data: dict[str, Any] | None) -> None:
    """
        Replace config from a dict. For tests only.
    """
    global _config, _loaded
    root = _normalize_root(data)
    _validate_processor(root)
    _config = root
    _loaded = True


def reload(
    logger: logging.Logger,
    *,
    required: bool = False,
) -> bool:
    """
        Load or refresh config from disk.

        required=True at startup: exit the process on failure.
        required=False in the poll loop: keep the previous config on error.
    """
    global _config, _loaded

    path = _find_config_path()
    if path is None:
        exc = FileNotFoundError(_config_not_found_message())
        _log(logger, {
            "msg": "Error loading config file",
            "exception": str(exc),
        })
        if required or not _loaded:
            raise SystemExit(1) from exc
        return False

    try:
        root = _read_file(path)
    except Exception as exc:
        _log(logger, {
            "msg": "Error loading config file",
            "path": str(path),
            "exception": str(exc),
        })
        if required or not _loaded:
            raise SystemExit(1) from exc
        return False

    _config = root
    _loaded = True
    return True


def get() -> dict[str, Any]:
    """
        Return the current config mapping.
    """
    return _config


def _section(name: str) -> dict[str, Any]:
    value = _config.get(name)
    if value is None:
        return {}
    if not isinstance(value, dict):
        return {}
    return value


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [part.strip() for part in value.split() if part.strip()]
    return []


def _comma_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return []


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return str(value)
    stripped = value.strip()
    if stripped == "":
        return None
    return stripped


def sleep_delay() -> int:
    raw = _config.get("sleep_delay", DEFAULT_SLEEP_DELAY)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return DEFAULT_SLEEP_DELAY


def classification_processor_raw(root: dict[str, Any] | None = None) -> str:
    """
        Return the raw classification processor setting.
    """
    data = root if root is not None else _config
    section = data.get("classification")
    if not isinstance(section, dict):
        return ""
    raw = section.get("processor")
    if raw is None:
        return ""
    return str(raw).strip()


def classification_processor() -> list[str]:
    from processors.classify import parse_processor_names

    return parse_processor_names(classification_processor_raw())


def classification_prompt() -> str:
    section = _section("classification")
    raw = section.get("prompt")
    if not isinstance(raw, str) or raw.strip() == "":
        raise ValueError(
            "classification.prompt must be a non-empty string in config"
        )
    return raw


def openai_model() -> str:
    section = _section("classification")
    raw = section.get("openai_model")
    if isinstance(raw, str) and raw.strip() != "":
        return raw.strip()
    return DEFAULT_OPENAI_MODEL


def openrouter_model() -> str:
    section = _section("classification")
    raw = section.get("openrouter_model")
    if isinstance(raw, str) and raw.strip() != "":
        return raw.strip()
    return DEFAULT_OPENROUTER_MODEL


def rss_urls() -> list[str]:
    return _string_list(_section("rss").get("urls"))


def twitter_usernames() -> list[str]:
    raw = _section("twitter").get("usernames")
    names = _string_list(raw)
    return [name.lstrip("@") for name in names]


def telegram_channels_raw() -> list[dict[str, Any]]:
    section = _section("telegram")
    raw = section.get("channels")
    if raw is None:
        return []
    if not isinstance(raw, list):
        return []
    return [entry for entry in raw if isinstance(entry, dict)]


def notam_locations_raw() -> str | None:
    section = _section("notam")
    if "locations" not in section:
        return None
    value = section.get("locations")
    if value is None:
        return None
    if isinstance(value, list):
        parts = [str(item).strip().upper() for item in value if str(item).strip()]
        return " ".join(parts)
    if isinstance(value, str):
        return value.strip()
    return None


def notam_locations() -> list[str]:
    raw = notam_locations_raw()
    if raw is None:
        raw = DEFAULT_NOTAM_LOCATIONS
    return [
        location.strip().upper()
        for location in raw.split()
        if location.strip()
    ]


def notam_qcodes_raw() -> str | None:
    section = _section("notam")
    if "qcodes" not in section:
        return None
    value = section.get("qcodes")
    if value is None:
        return None
    if isinstance(value, list):
        return ",".join(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, str):
        return value.strip()
    return None


def notam_qcodes() -> str:
    raw = notam_qcodes_raw()
    if raw is None or raw == "":
        return DEFAULT_NOTAM_QCODES
    return raw


def notam_passthrough_qcodes_raw() -> str | None:
    section = _section("notam")
    if "passthrough_qcodes" not in section:
        return None
    value = section.get("passthrough_qcodes")
    if value is None:
        return None
    if isinstance(value, list):
        return ",".join(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, str):
        return value.strip()
    return None


def notam_text_exclude_raw() -> str | None:
    section = _section("notam")
    if "text_exclude" not in section:
        return None
    value = section.get("text_exclude")
    if value is None:
        return None
    if isinstance(value, list):
        return ",".join(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, str):
        return value.strip()
    return None


def notam_classification() -> str | None:
    section = _section("notam")
    return _optional_string(section.get("classification"))


def alertsua_filter_types_raw() -> str | None:
    section = _section("alertsua")
    if "filter_types" not in section:
        return None
    value = section.get("filter_types")
    if value is None:
        return None
    if isinstance(value, list):
        return ",".join(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, str):
        return value.strip()
    return None


def alertsua_filter_regions_raw() -> str | None:
    section = _section("alertsua")
    if "filter_regions" not in section:
        return None
    value = section.get("filter_regions")
    if value is None:
        return None
    if isinstance(value, list):
        return ",".join(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, str):
        return value.strip()
    return None


def ntfy_priority() -> str:
    section = _section("ntfy")
    raw = section.get("priority")
    if isinstance(raw, str) and raw.strip() != "":
        return raw.strip()
    return DEFAULT_NTFY_PRIORITY


def ntfy_tags_raw() -> str | None:
    section = _section("ntfy")
    if "tags" not in section:
        return None
    value = section.get("tags")
    if value is None:
        return None
    if isinstance(value, list):
        return ",".join(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, str):
        return value.strip()
    return None


def email_to() -> list[str]:
    section = _section("email")
    return _string_list(section.get("to"))
