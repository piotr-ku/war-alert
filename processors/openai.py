import json
import logging
import time
import openai
import os
from processors.base import Processor
from processors.base import Content

class ProcessorOpenAI(Processor):
    """
        A class to represent an OpenAI processor.
    """
    def process(self, content: Content, logger) -> Content|None:
        """
            Process a content using OpenAI API.
        """
        prompt = get_prompt(str(content))
        answer = query(prompt, logger)

        # Parse the JSON response
        try:
            parsed = json.loads(answer)
        except Exception as e:
            logger.error(json.dumps({
                "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
                "error": str(e),
                "title": content.title,
                "description": content.description,
                "pubDate": content.pubDate,
                "link": content.link,
            }, ensure_ascii=False))
            return

        # Validate the JSON response, result and justification must be present
        if "result" not in parsed or "justification" not in parsed:
            logger.error(json.dumps({
                "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
                "error": "result or justification not found",
                "title": content.title,
                "description": content.description,
                "pubDate": content.pubDate,
                "link": content.link,
            }, ensure_ascii=False))
            return None

        # If the result is no, return None
        if parsed["result"] == "no":
            logger.info(json.dumps({
                "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
                "result": parsed["result"],
                "justification": parsed["justification"],
                "title": content.title,
                "description": content.description,
                "pubDate": content.pubDate,
                "link": content.link,
            }, ensure_ascii=False))
            return None

        # Print the result
        logger.warning(json.dumps({
            "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
            "result": parsed["result"],
            "justification": parsed["justification"],
            "title": content.title,
            "description": content.description,
            "pubDate": content.pubDate,
            "link": content.link,
        }, ensure_ascii=False))

        # Set description
        content.description = parsed["justification"]
        return content

def get_prompt(content: str) -> str:
    """
        Return the prompt.
    """
    with open(os.environ.get("PROMPT_FILE", "./prompt.txt"), "r") as file:
        return file.read().replace("<content>", content)

def query(query: str, logger: logging.Logger) -> str:
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
            "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
            "msg": "Error sending OpenAI request",
            "exception": str(e),
        }, ensure_ascii=False))
        return

    # Check the response
    try:
        return completion.choices[0].message.content
    except Exception as e:
        logger.error(json.dumps({
            "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
            "msg": "Error parsing OpenAI response",
            "exception": str(e),
        }, ensure_ascii=False))
        return ""
