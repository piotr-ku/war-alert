"""
    OpenAI classification API client for war-alert.
"""

import json
import logging
import time

import openai

import config


def query(
    system_prompt: str,
    user_prompt: str,
    logger: logging.Logger,
) -> str:
    """
        Return a response from OpenAI API in a string format.
    """
    try:
        client = openai.OpenAI()
        completion = client.chat.completions.create(
            model=config.openai_model(),
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
        return ""

    try:
        return completion.choices[0].message.content or ""
    except Exception as e:
        logger.error(json.dumps({
            "time": time.strftime(
                "%Y-%m-%dT%H:%M:%S",
                time.localtime(),
            ),
            "msg": "Error parsing OpenAI response",
            "exception": str(e),
        }, ensure_ascii=False))
        return ""
