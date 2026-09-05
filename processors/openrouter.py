"""
    OpenRouter classification API client for war-alert.
"""

import json
import logging
import os
import time

import openai

import config

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"


def query(prompt: str, logger: logging.Logger) -> str:
    """
        Return a response from OpenRouter API in a string format.
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
        return ""

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
                    "role": "user",
                    "content": prompt,
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
        return ""

    try:
        return completion.choices[0].message.content or ""
    except Exception as e:
        logger.error(json.dumps({
            "time": time.strftime(
                "%Y-%m-%dT%H:%M:%S",
                time.localtime(),
            ),
            "msg": "Error parsing OpenRouter response",
            "exception": str(e),
        }, ensure_ascii=False))
        return ""
