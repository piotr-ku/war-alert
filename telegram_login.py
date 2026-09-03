#!/usr/bin/env python3

import os
import sys

import dotenv
from telethon.sync import TelegramClient
from telethon.sessions import StringSession

from sources.telegram import (
    _api_hash,
    _api_id,
    _session_file,
    _session_string,
    telegram_credentials_configured,
)


def main() -> int:
    dotenv.load_dotenv()

    if not telegram_credentials_configured():
        print(
            "Set TELEGRAM_API_ID and TELEGRAM_API_HASH in .env "
            "(from https://my.telegram.org).",
            file=sys.stderr,
        )
        return 1

    api_id = _api_id()
    if api_id is None:
        print("TELEGRAM_API_ID must be an integer.", file=sys.stderr)
        return 1

    session_string = _session_string()
    if session_string != "":
        session = StringSession(session_string)
        session_path = None
    else:
        session = _session_file()
        session_path = session

    phone = os.environ.get("TELEGRAM_PHONE", "").strip() or None

    with TelegramClient(session, api_id, _api_hash()) as client:
        client.start(phone=phone)

        if session_path is not None:
            print(f"Session saved to {session_path}")
        else:
            print("Authorized with TELEGRAM_SESSION_STRING.")

        if session_string == "":
            exported = StringSession.save(client.session)
            print()
            print("Optional: copy this into TELEGRAM_SESSION_STRING for Docker:")
            print(exported)

    return 0


if __name__ == "__main__":
    sys.exit(main())
