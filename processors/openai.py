"""
    OpenAI classification API client for war-alert.
"""

import json
import logging
import time

import openai

import config
from processors.llm_meta import build_query_meta


def query(
    system_prompt: str,
    user_prompt: str,
    logger: logging.Logger,
) -> tuple[str, dict[str, str]]:
    """
        Return OpenAI response text and query metadata for logs.
    """
    model = config.openai_model()

    try:
        client = openai.OpenAI()
        completion = client.chat.completions.create(
            model=model,
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
            "msg": "Error sending OpenAI request",
            "exception": str(e),
        }, ensure_ascii=False))
        return "", {}

    try:
        text = completion.choices[0].message.content or ""
        return text, build_query_meta(completion, model)
    except Exception as e:
        logger.error(json.dumps({
            "time": time.strftime(
                "%Y-%m-%dT%H:%M:%S",
                time.localtime(),
            ),
            "msg": "Error parsing OpenAI response",
            "exception": str(e),
        }, ensure_ascii=False))
        return "", {}
