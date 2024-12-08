import email.message
import json
import os
import smtplib
import time

def notify(recipient, title, message, logger):
    """
        Send an email notification.

        Args:
            title (str): The title of the notification.
            message (str): The message of the notification.
            logger (logging.Logger): The logger to use.
    """
    msg = email.message.EmailMessage()
    msg['Subject'] = title
    msg['From'] = os.environ.get("EMAIL_FROM", "your.email@example.com")
    msg['To'] = recipient
    msg.set_content(message)

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
            "to": recipient,
        }, ensure_ascii=False))
    except Exception as e:
        logger.error(json.dumps({
            "msg": "Error sending email notification",
            "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
            "exception": str(e),
        }, ensure_ascii=False))
        return