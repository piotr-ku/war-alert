"""
    OpenRouter classification API client for war-alert.
"""

import json
import logging
import os
import time

import openai

import config
from processors.llm_meta import build_query_meta

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"


def query(
    system_prompt: str,
    user_prompt: str,
    logger: logging.Logger,
) -> tuple[str, dict[str, str]]:
    """
        Return OpenRouter response text and query metadata for logs.
    """
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if api_key == "":
        logger.error(json.dumps({
            "time": time.strftime(
                "%Y-%m-%dT%H:%M:%S",
                time.localtime(),
            ),
            "msg": "OPENROUTER_API_KEY is not set",
        }, ensure_ascii=False))
        return "", {}

    base_url = os.environ.get(
        "OPENROUTER_BASE_URL",
        DEFAULT_BASE_URL,
    ).rstrip("/")

    try:
        client = openai.OpenAI(
            base_url=base_url,
            api_key=api_key,
        )
        completion = client.chat.completions.create(
            model=config.openrouter_model(),
            messages=[
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {
                    "role": "user",
                    "content": user_prompt,
                }
            ],
            response_format={"type": "json_object"},
        )
    except Exception as e:
        logger.error(json.dumps({
            "time": time.strftime(
                "%Y-%m-%dT%H:%M:%S",
                time.localtime(),
            ),
            "msg": "Error sending OpenRouter request",
            "exception": str(e),
        }, ensure_ascii=False))
        return "", {}

    try:
        text = completion.choices[0].message.content or ""
        model = completion.model or config.openrouter_model()
        return text, build_query_meta(completion, model)
    except Exception as e:
        logger.error(json.dumps({
            "time": time.strftime(
                "%Y-%m-%dT%H:%M:%S",
                time.localtime(),
            ),
            "msg": "Error parsing OpenRouter response",
            "exception": str(e),
        }, ensure_ascii=False))
        return "", {}
