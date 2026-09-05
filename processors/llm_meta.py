"""
    Shared helpers for LLM query metadata used in classification logs.
"""

from typing import Any


def format_cost(value: Any) -> str | None:
    """
        Return a decimal cost string or None when cost is unavailable.
    """
    if value is None:
        return None

    try:
        cost = float(value)
    except (TypeError, ValueError):
        return None

    formatted = format(cost, ".10f").rstrip("0").rstrip(".")
    if formatted == "":
        return "0"
    return formatted


def read_usage_cost(usage: Any) -> str | None:
    """
        Read usage.cost from an OpenAI SDK usage object or dict.
    """
    if usage is None:
        return None

    raw = getattr(usage, "cost", None)
    if raw is None and hasattr(usage, "model_extra"):
        extra = usage.model_extra
        if isinstance(extra, dict):
            raw = extra.get("cost")
    if raw is None and isinstance(usage, dict):
        raw = usage.get("cost")

    return format_cost(raw)


def build_query_meta(completion: Any, model: str) -> dict[str, str]:
    """
        Build log metadata for a successful LLM completion.
    """
    meta = {"model": model}
    cost = read_usage_cost(getattr(completion, "usage", None))
    if cost is not None:
        meta["cost"] = cost
    return meta
