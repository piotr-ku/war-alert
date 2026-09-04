"""
    Interactive Telegram login helper for war-alert.
"""

import os
import sys

import dotenv
from telethon.sessions import StringSession

from sources.telegram import (
    _session_file,
    _session_string,
    authorize_telegram_client,
    build_telegram_client,
    disconnect_telegram_client,
    is_session_locked_error,
    telegram_credentials_configured,
    telegram_session_locked_hint,
)


def main() -> int:
    """
        Authorize a Telethon user session and print export hints.
    """
    dotenv.load_dotenv()

    if not telegram_credentials_configured():
        print(
            "Set TELEGRAM_API_ID and TELEGRAM_API_HASH in .env "
            "(from https://my.telegram.org).",
            file=sys.stderr,
        )
        return 1

    # Prefer in-memory session string over a local session file
    session_string = _session_string()
    if session_string != "":
        session_path = None
    else:
        session_path = _session_file()

    phone = os.environ.get("TELEGRAM_PHONE", "").strip() or None
    client = build_telegram_client()

    try:
        authorize_telegram_client(client, phone=phone)
    except Exception as exc:
        if is_session_locked_error(exc):
            print(telegram_session_locked_hint(), file=sys.stderr)
        raise
    else:
        if client.is_user_authorized():
            if session_path is not None:
                print(f"Session saved to {session_path}")
            else:
                print("Authorized with TELEGRAM_SESSION_STRING.")

            # Offer a session string for Docker deployments
            if session_string == "":
                exported = StringSession.save(client.session)
                print()
                print(
                    "Optional: copy this into "
                    "TELEGRAM_SESSION_STRING for Docker:"
                )
                print(exported)
        else:
            print("Telegram authorization failed.", file=sys.stderr)
            return 1
    finally:
        disconnect_telegram_client(client)

    return 0


if __name__ == "__main__":
    sys.exit(main())
