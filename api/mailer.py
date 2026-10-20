"""Sends the web sign-in code by email over plain SMTP (stdlib only).

smtplib is blocking, so the actual send runs in a worker thread. Only the
one-time code goes out — nothing about the account or its health data.
"""
import asyncio
import logging
import smtplib
import ssl
from email.message import EmailMessage

import config

SEND_TIMEOUT = 15  # seconds


class MailNotConfigured(RuntimeError):
    """No SMTP account is set up (and dev code printing is off)."""


class MailSendError(RuntimeError):
    """The SMTP server refused or couldn't be reached."""


def _build_message(to: str, code: str, ttl_minutes: int) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = f"Код входа в «Мой Доктор»: {code}"
    msg["From"] = config.SMTP_FROM
    msg["To"] = to
    msg.set_content(
        f"Ваш код входа: {code}\n\n"
        f"Он действует {ttl_minutes} минут и подходит только один раз.\n"
        "Если вы не запрашивали код — просто проигнорируйте это письмо."
    )
    return msg


def _send_blocking(msg: EmailMessage) -> None:
    context = ssl.create_default_context()
    try:
        if config.SMTP_PORT == 465:
            with smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT, timeout=SEND_TIMEOUT, context=context) as smtp:
                if config.SMTP_USER:
                    smtp.login(config.SMTP_USER, config.SMTP_PASSWORD)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=SEND_TIMEOUT) as smtp:
                smtp.starttls(context=context)
                if config.SMTP_USER:
                    smtp.login(config.SMTP_USER, config.SMTP_PASSWORD)
                smtp.send_message(msg)
    except (smtplib.SMTPException, OSError) as exc:
        raise MailSendError(str(exc)) from exc


async def send_login_code(to: str, code: str, ttl_minutes: int = 10) -> None:
    if not config.SMTP_HOST:
        if config.WEB_DEV_PRINT_CODES:
            logging.warning("DEV sign-in code for %s: %s", to, code)
            return
        raise MailNotConfigured("SMTP_HOST is not set")
    await asyncio.to_thread(_send_blocking, _build_message(to, code, ttl_minutes))
