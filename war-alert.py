#!/usr/bin/env python3

import dotenv
import json
import logging
import os
import signal
import sys
import time

from notifiers.base import Notifier
from notifiers.email import NotifierEmail
from notifiers.pushover import NotifierPushover
from notifiers.telegram import NotifierTelegram
from sources.alertsua import SourceAlertsInUa
from sources.alertsua import url as alertsua_url
from sources.base import Source
from sources.rss import News, SourceRSS
from processors.unique import ProcessorUnique
from processors.openai import ProcessorOpenAI

def signal_handler(sig, frame):
    """
        Handle the SIGKILL, SIGTERM and KeyboardInterrupt signals.
    """
    logger.warning(json.dumps({
        "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        "signal": signal.Signals(sig).name,
    }))
    sys.exit(0)

def usr1_handler(sig, frame):
    """
        Handle the SIGUSR1 signal.
    """
    logger.warning(json.dumps({
        "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        "signal": signal.Signals(sig).name,
    }))

    # Process the news
    content = News(
        "Everything is fine, it's just a test.",
        "We are testing the system. Please do not panic. Test time: " +
            time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        "https://github.com/piotr-ku/war-alert")
    for processor in [ProcessorUnique, ProcessorOpenAI]:
        content = processor().process(content, logger)
    if content is not None:
        for notifier in all_notifiers(logger):
            notifier.notify(content, logger)

# Handle the SIGTERM, SIGINT and SIGUSR1 signals
signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGUSR1, usr1_handler)

def all_sources(logger: logging.Logger) -> list[Source]:
    """
        Return a list of all sources.
    """
    all_sources = []

    # Add the AlertsInUa source if the token is set
    if os.environ.get("ALERTSUA_TOKEN") is not None \
        and os.environ.get("ALERTSUA_TOKEN") != "":
        all_sources.append(SourceAlertsInUa(alertsua_url, logger))

    # Add the RSS sources if the URLs are set
    if os.environ.get("RSS_URLS") is not None \
        and os.environ.get("RSS_URLS") != "":
        for url in os.environ.get("RSS_URLS").split():
            all_sources.append(SourceRSS(url, logger))

    return all_sources

def all_notifiers(logger: logging.Logger) -> list[Notifier]:
    """
        Return a list of all notifiers.
    """
    all_notifiers = []

    # Add the Telegram notifier if the token is set
    if os.environ.get("TELEGRAM_BOT_TOKEN") is not None \
        and os.environ.get("TELEGRAM_BOT_TOKEN") != "":
        all_notifiers.append(NotifierTelegram())

    # Add the Pushover notifier if the token is set
    if os.environ.get("PUSHOVER_TOKEN") is not None \
        and os.environ.get("PUSHOVER_TOKEN") != "":
        all_notifiers.append(NotifierPushover())

    # Add the Email notifier if the token is set
    if os.environ.get("EMAIL_FROM") is not None \
        and os.environ.get("EMAIL_FROM") != "" \
        and os.environ.get("EMAIL_TO") is not None \
        and os.environ.get("EMAIL_TO") != "":
        for email in os.environ.get("EMAIL_TO").split():
            all_notifiers.append(NotifierEmail(email))

    return all_notifiers

if __name__ == "__main__":
    # Create a logger and set stdout as a handler
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.DEBUG)
    logger.addHandler(logging.StreamHandler(sys.stdout))

    # Load the .env file
    dotenv.load_dotenv()

    # Infinite loop
    while True:
        try:
            # Get sources
            sources = all_sources(logger)

            # Loop through the sources
            for source in sources:
                items = source.fetch(logger)
                for item in items:
                    # Loop through the processors
                    for processor in source.processors():
                        if item is None:
                            continue
                        item = processor().process(item, logger)
                    if item is not None:
                        # Loop through the notifiers
                        for notifier in all_notifiers(logger):
                            notifier.notify(item, logger)
        except Exception as e:
            logger.error(json.dumps({
                "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
                "exception": str(e),
            }, ensure_ascii=False))
            continue

        # Sleep for the specified delay
        time.sleep(int(os.environ.get("SLEEP_DELAY", 600)))
