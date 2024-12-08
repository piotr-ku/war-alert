import json
import time
import openai
import os

def query(query, logger):
    """
        Return a response from OpenAI API in a string format.
    """
    try:
        client = openai.OpenAI()
        completion = client.chat.completions.create(
            model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
            messages=[
                {
                    "role": "user",
                    "content": query,
                }
            ],
            response_format={ "type": "json_object" }
        )
    except Exception as e:
        logger.error(json.dumps({
            "msg": "Error sending OpenAI request",
            "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
            "exception": str(e),
        }, ensure_ascii=False))
        return

    # Check the response
    try:
        return completion.choices[0].message.content
    except Exception as e:
        logger.error(json.dumps({
            "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
            "exception": str(e),
        }, ensure_ascii=False))
        return ""