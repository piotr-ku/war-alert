"""
    Configurable LLM classification processor for war-alert.
"""

import json
import logging
import os
import time
from collections.abc import Callable

from processors.base import Content, Processor
from processors.openai import query as openai_query
from processors.openrouter import query as openrouter_query
from processors.unique import ProcessorUnique

# Registry of supported classification providers
PROVIDERS: dict[str, Callable[[str, logging.Logger], str]] = {
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


def get_prompt(content: str) -> str:
    """
        Return the classification prompt with content substituted.
    """
    prompt_file = os.environ.get("PROMPT_FILE", "./prompt.txt")
    with open(prompt_file, "r") as file:
        return file.read().replace("<content>", content)


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
            **_content_log_fields(content),
        }, ensure_ascii=False))
        return "invalid"

    if parsed["result"] == "no":
        logger.info(json.dumps({
            "time": time.strftime(
                "%Y-%m-%dT%H:%M:%S",
                time.localtime(),
            ),
            "provider": provider,
            "result": parsed["result"],
            "justification": parsed["justification"],
            **_content_log_fields(content),
        }, ensure_ascii=False))
        return None

    logger.warning(json.dumps({
        "time": time.strftime(
            "%Y-%m-%dT%H:%M:%S",
            time.localtime(),
        ),
        "provider": provider,
        "result": parsed["result"],
        "justification": parsed["justification"],
        **_content_log_fields(content),
    }, ensure_ascii=False))

    content.description = parsed["justification"]
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
            providers = parse_processor_names(
                os.environ.get("CLASSIFICATION_PROCESSOR"),
            )
        self.providers = providers

    def process(
        self,
        content: Content,
        logger: logging.Logger,
    ) -> Content | None:
        """
            Classify content; try fallback providers only on API failures.
        """
        prompt = get_prompt(str(content))

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
            answer = query_fn(prompt, logger)
            if answer == "":
                continue

            result = _parse_classification(
                answer,
                content,
                logger,
                provider,
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
