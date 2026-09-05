"""
    Configurable LLM classification processor for war-alert.

    Classification settings live in war-alert.yml under classification:
        processor — provider name or comma-separated fallback chain
            (default openai). Supported: openai, openrouter.
        openai_model, openrouter_model — model names per provider.
        prompt — system prompt sent to the LLM (item text is the user
            message).

    API keys stay in .env: OPENAI_API_KEY, OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL.

    Fallback rules:
        The next provider runs only when the previous one fails (API error,
        empty response, or invalid JSON). A valid result: "no" does NOT
        trigger fallback — the item is dropped.

    Used by RSS, Twitter, Telegram sources and /webhook/news.
    NOTAM and /webhook/alert skip this processor.
"""

import json
import logging
import time
from collections.abc import Callable

import config

from processors.base import Content, Processor
from processors.openai import query as openai_query
from processors.openrouter import query as openrouter_query
from processors.unique import ProcessorUnique

# Registry of supported classification providers
PROVIDERS: dict[
    str,
    Callable[[str, str, logging.Logger], tuple[str, dict[str, str]]],
] = {
    "openai": openai_query,
    "openrouter": openrouter_query,
}

DEFAULT_PROCESSOR = "openai"


def parse_processor_names(raw: str | None) -> list[str]:
    """
        Parse CLASSIFICATION_PROCESSOR into an ordered provider list.
    """
    if raw is None or raw.strip() == "":
        return [DEFAULT_PROCESSOR]

    names = [part.strip().lower() for part in raw.split(",")]
    names = [name for name in names if name != ""]
    if not names:
        return [DEFAULT_PROCESSOR]

    unknown = [name for name in names if name not in PROVIDERS]
    if unknown:
        supported = ", ".join(sorted(PROVIDERS))
        raise ValueError(
            f"Unknown CLASSIFICATION_PROCESSOR: {unknown[0]}. "
            f"Supported: {supported}"
        )

    return names


def get_system_prompt() -> str:
    """
        Return the classification system prompt from config.

        Strips a legacy <content> placeholder if present in old configs.
    """
    return config.classification_prompt().replace("<content>", "")


def _content_log_fields(content: Content) -> dict:
    """
        Return common content fields for structured logs.
    """
    return {
        "title": content.title,
        "description": content.description,
        "pubDate": content.pubDate,
        "link": content.link,
    }


def _parse_classification(
    answer: str,
    content: Content,
    logger: logging.Logger,
    provider: str,
    query_meta: dict[str, str],
) -> Content | None | str:
    """
        Parse a provider JSON answer.

        Returns Content when the item is relevant, None when rejected,
        or "invalid" when the response should trigger the next provider.
    """
    try:
        parsed = json.loads(answer)
    except Exception as e:
        logger.error(json.dumps({
            "time": time.strftime(
                "%Y-%m-%dT%H:%M:%S",
                time.localtime(),
            ),
            "provider": provider,
            "error": str(e),
            **query_meta,
            **_content_log_fields(content),
        }, ensure_ascii=False))
        return "invalid"

    if "result" not in parsed or "justification" not in parsed:
        logger.error(json.dumps({
            "time": time.strftime(
                "%Y-%m-%dT%H:%M:%S",
                time.localtime(),
            ),
            "provider": provider,
            "error": "result or justification not found",
            **query_meta,
            **_content_log_fields(content),
        }, ensure_ascii=False))
        return "invalid"

    result = parsed["result"]
    justification = parsed["justification"]

    # Both fields must be strings; result is only yes or no.
    if not isinstance(result, str) or not isinstance(justification, str):
        logger.error(json.dumps({
            "time": time.strftime(
                "%Y-%m-%dT%H:%M:%S",
                time.localtime(),
            ),
            "provider": provider,
            "error": "result or justification is not a string",
            **query_meta,
            **_content_log_fields(content),
        }, ensure_ascii=False))
        return "invalid"

    result_norm = result.strip().lower()
    justification_text = justification.strip()

    # Reject swapped or empty fields. justification is a sentence,
    # never the words yes or no.
    if (
        result_norm not in ("yes", "no")
        or justification_text.lower() in ("", "yes", "no")
    ):
        logger.error(json.dumps({
            "time": time.strftime(
                "%Y-%m-%dT%H:%M:%S",
                time.localtime(),
            ),
            "provider": provider,
            "error": "invalid result or justification",
            "result": result,
            "justification": justification,
            **query_meta,
            **_content_log_fields(content),
        }, ensure_ascii=False))
        return "invalid"

    if result_norm == "no":
        logger.info(json.dumps({
            "time": time.strftime(
                "%Y-%m-%dT%H:%M:%S",
                time.localtime(),
            ),
            "provider": provider,
            "result": result_norm,
            "justification": justification_text,
            **query_meta,
            **_content_log_fields(content),
        }, ensure_ascii=False))
        return None

    logger.warning(json.dumps({
        "time": time.strftime(
            "%Y-%m-%dT%H:%M:%S",
            time.localtime(),
        ),
        "provider": provider,
        "result": result_norm,
        "justification": justification_text,
        **query_meta,
        **_content_log_fields(content),
    }, ensure_ascii=False))

    content.description = justification_text
    return content


class ProcessorClassification(Processor):
    """
        Classify content using providers from CLASSIFICATION_PROCESSOR.
    """

    def __init__(self, providers: list[str] | None = None):
        """
            Initialize with an ordered provider list.
        """
        if providers is None:
            providers = config.classification_processor()
        self.providers = providers

    def process(
        self,
        content: Content,
        logger: logging.Logger,
    ) -> Content | None:
        """
            Classify content; try fallback providers only on API failures.
        """
        system_prompt = get_system_prompt()
        user_prompt = str(content)

        for index, provider in enumerate(self.providers):
            if index > 0:
                logger.warning(json.dumps({
                    "time": time.strftime(
                        "%Y-%m-%dT%H:%M:%S",
                        time.localtime(),
                    ),
                    "msg": "Trying classification fallback provider",
                    "provider": provider,
                    **_content_log_fields(content),
                }, ensure_ascii=False))

            query_fn = PROVIDERS[provider]
            answer, query_meta = query_fn(
                system_prompt,
                user_prompt,
                logger,
            )
            if answer == "":
                continue

            result = _parse_classification(
                answer,
                content,
                logger,
                provider,
                query_meta,
            )
            if result == "invalid":
                continue
            return result

        return None


def news_processors() -> list[type[Processor]]:
    """
        Return processors for news-like sources (RSS, Twitter, Telegram).
    """
    return [ProcessorUnique, ProcessorClassification]
