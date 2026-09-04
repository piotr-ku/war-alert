#!/usr/bin/env python3
"""
    War-alert main entry point: poll sources and send notifications.
"""

import dotenv
import json
import logging
import os
import signal
import sys
import time

from notifiers.base import Notifier
from notifiers.email import NotifierEmail
from notifiers.ntfy import NotifierNtfy
from notifiers.pushover import NotifierPushover
from notifiers.telegram import NotifierTelegram
from sources.alertsua import SourceAlertsInUa
from sources.alertsua import url as alertsua_url
from sources.base import Source
from sources.notam import SourceNotam
from sources.rss import News, SourceRSS
from sources.twitterapi import SourceTwitterAPI
from sources.telegram import (
    SourceTelegram,
    load_channel_configs,
    telegram_credentials_configured,
)
from processors.classify import news_processors, parse_processor_names
from processors.unique import ProcessorUnique
from processors.base import Content, Processor
from webhooks.server import start_http_server

def process_and_notify(
    item: Content,
    processors: list[type[Processor]],
    logger: logging.Logger,
) -> bool:
    """
        Process an item through processors and notifiers.
        Returns True if a notification was sent.
    """
    unique_content = None
    for processor in processors:
        if item is None:
            break
        item = processor().process(item, logger)
        if processor is ProcessorUnique and item is not None:
            unique_content = item
    if item is not None:
        notified = False
        for notifier in all_notifiers(logger):
            if notifier.notify(item, logger):
                notified = True
        # Mark seen only after at least one notifier succeeds
        if notified:
            ProcessorUnique().mark_seen(item)
        return notified
    # A later processor dropped the item, but Unique already passed it
    if unique_content is not None:
        ProcessorUnique().mark_seen(unique_content)
    return False

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
    process_and_notify(content, news_processors(), logger)

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

    # Add the NOTAM source if FAA NMS credentials are set
    if os.environ.get("FAA_NMS_CLIENT_ID") is not None \
        and os.environ.get("FAA_NMS_CLIENT_ID") != "" \
        and os.environ.get("FAA_NMS_CLIENT_SECRET") is not None \
        and os.environ.get("FAA_NMS_CLIENT_SECRET") != "":
        all_sources.append(SourceNotam(logger))

    # Add the RSS sources if the URLs are set
    if os.environ.get("RSS_URLS") is not None \
        and os.environ.get("RSS_URLS") != "":
        for url in os.environ.get("RSS_URLS").split():
            all_sources.append(SourceRSS(url, logger))

    # Add the TwitterAPI source if the key and usernames are set
    if os.environ.get("TWITTERAPI_KEY") is not None \
        and os.environ.get("TWITTERAPI_KEY") != "" \
        and os.environ.get("TWITTERAPI_USERNAMES") is not None \
        and os.environ.get("TWITTERAPI_USERNAMES") != "":
        all_sources.append(SourceTwitterAPI(logger))

    # Add the Telegram channel source if API credentials and channels are set
    if telegram_credentials_configured() and load_channel_configs(logger):
        all_sources.append(SourceTelegram(logger))

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

    # Add the ntfy notifier if the topic is set
    if os.environ.get("NTFY_TOPIC") is not None \
        and os.environ.get("NTFY_TOPIC") != "":
        all_notifiers.append(NotifierNtfy())

    # Add the Email notifier if the token is set
    if os.environ.get("EMAIL_FROM") is not None \
        and os.environ.get("EMAIL_FROM") != "" \
        and os.environ.get("EMAIL_TO") is not None \
        and os.environ.get("EMAIL_TO") != "":
        for email in os.environ.get("EMAIL_TO").split():
            all_notifiers.append(NotifierEmail(email))

    return all_notifiers

def _log_level() -> int:
    """
        Parse LOG_LEVEL from the environment, defaulting to INFO.
    """
    raw = os.environ.get("LOG_LEVEL", "INFO")
    if raw is None or raw.strip() == "":
        return logging.INFO
    level = getattr(logging, raw.strip().upper(), None)
    # Fall back when LOG_LEVEL is not a valid logging constant
    if isinstance(level, int):
        return level
    return logging.INFO


if __name__ == "__main__":
    # Create a logger and set stdout as a handler
    logger = logging.getLogger(__name__)
    logger.addHandler(logging.StreamHandler(sys.stdout))

    # Load the .env file
    dotenv.load_dotenv()
    logger.setLevel(_log_level())

    try:
        parse_processor_names(os.environ.get("CLASSIFICATION_PROCESSOR"))
    except ValueError as e:
        logger.error(json.dumps({
            "time": time.strftime(
                "%Y-%m-%dT%H:%M:%S",
                time.localtime(),
            ),
            "msg": str(e),
        }))
        sys.exit(1)

    http_port = os.environ.get("WEBHOOK_PORT") or os.environ.get("HEALTH_PORT")
    if http_port is not None and http_port != "":
        webhook_port = os.environ.get("WEBHOOK_PORT")
        if webhook_port and not os.environ.get("WEBHOOK_SECRET"):
            logger.error(json.dumps({
                "time": time.strftime(
                    "%Y-%m-%dT%H:%M:%S",
                    time.localtime(),
                ),
                "msg": (
                    "WEBHOOK_SECRET is required when WEBHOOK_PORT is set"
                ),
            }))
            sys.exit(1)
        start_http_server(logger, process_and_notify, int(http_port))

    # Infinite loop
    while True:
        try:
            # Get sources
            sources = all_sources(logger)

            # Loop through the sources
            for source in sources:
                items = source.fetch(logger)
                for item in items:
                    if item is None:
                        continue
                    process_and_notify(item, source.processors(), logger)
        except Exception as e:
            logger.error(json.dumps({
                "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
                "exception": str(e),
            }, ensure_ascii=False))
            continue

        # Sleep for the specified delay
        time.sleep(int(os.environ.get("SLEEP_DELAY", 600)))
