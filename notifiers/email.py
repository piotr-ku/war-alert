import email.message
import json
import os
import logging
import smtplib
import time
from notifiers.base import Notifier
from processors.base import Content

class NotifierEmail(Notifier):
    """
        A base class for all email notifiers.
    """
    def __init__(self, recipient: str):
        """
            Initialize an email notifier.
        """
        self.sender = os.environ.get("EMAIL_FROM", "")
        self.recipient = recipient

    def notify(self, content: Content, logger: logging.Logger) -> None:
        """
            Notify a content.
        """
        # Validation
        if self.recipient == "":
            return

        # Create an email message
        msg = email.message.EmailMessage()
        msg['Subject'] = content.title
        msg['From'] = self.sender
        msg['To'] = self.recipient
        msg.set_content(f"{content.description}\n\n{content.link}")

        # SMTP configuration
        smtp_server = os.environ.get("SMTP_SERVER", "smtp.example.com")
        port = os.environ.get("SMTP_PORT", 587)
        login = os.environ.get("SMTP_LOGIN", "your.email@example.com")
        password = os.environ.get("SMTP_PASSWORD", "your_password")

        # Wysyłanie wiadomości e-mail
        try:
            with smtplib.SMTP(smtp_server, port) as server:
                server.starttls()
                server.login(login, password)
                server.send_message(msg)

            logger.info(json.dumps({
                "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
                "msg": "Email notification sent",
                "to": self.recipient,
            }, ensure_ascii=False))
        except Exception as e:
            logger.error(json.dumps({
                "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
                "msg": "Error sending email notification",
                "exception": str(e),
            }, ensure_ascii=False))
            return
        return
