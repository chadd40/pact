from __future__ import annotations

import smtplib
from email.message import EmailMessage
from typing import Protocol, runtime_checkable

from pact.config import Settings


@runtime_checkable
class NotificationProvider(Protocol):
    """Outbound coaching channel. Implementations must never block on or
    require a network connection unless an explicit live flag is set."""

    def send(self, to: str, subject: str, body: str) -> dict:
        ...


class TestEmailProvider:
    """Deterministic, recording-safe notification provider. No network.

    Every send() is appended to ``self.sent`` so tests and the demo can
    assert on what *would* have been emailed.
    """

    def __init__(self) -> None:
        self.sent: list[dict] = []

    def send(self, to: str, subject: str, body: str) -> dict:
        self.sent.append({"to": to, "subject": subject, "body": body})
        return {"provider": "test_email", "to": to, "subject": subject}


class SmtpEmailProvider:
    """Builds a real RFC-5322 message but does NOT transmit by default.

    SAFETY: ``send()`` only contacts an SMTP server when called with
    ``live=True``. The default path builds the message, drops it, and returns
    a ``mode="not_sent"`` marker — so tests and the default runtime never
    open a socket. The live path is documented but never exercised by tests.
    """

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        from_addr: str,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.from_addr = from_addr

    @classmethod
    def from_settings(cls, settings: Settings) -> "SmtpEmailProvider":
        # Settings carries only the mode toggle; SMTP credentials would come
        # from the live environment. For the inert default we use placeholders
        # so construction never requires real secrets.
        return cls(
            host="localhost",
            port=587,
            username="pact-bot",
            password="",
            from_addr="pact-bot@localhost",
        )

    def build_message(self, to: str, subject: str, body: str) -> EmailMessage:
        msg = EmailMessage()
        msg["From"] = self.from_addr
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)
        return msg

    def send(self, to: str, subject: str, body: str, *, live: bool = False) -> dict:
        msg = self.build_message(to, subject, body)
        if not live:
            # Default, test-safe path: message is built but never transmitted.
            return {
                "provider": "smtp_email",
                "to": to,
                "subject": subject,
                "mode": "not_sent",
            }
        # LIVE PATH — never reached in tests or by default. Documented only.
        # Requires an explicit live=True from a configured live runtime.
        with smtplib.SMTP(self.host, self.port) as server:
            server.starttls()
            if self.username:
                server.login(self.username, self.password)
            server.send_message(msg)
        return {
            "provider": "smtp_email",
            "to": to,
            "subject": subject,
            "mode": "sent",
        }


def get_notification_provider(settings: Settings) -> NotificationProvider:
    """Return the configured notification provider.

    Defaults to the recording-safe ``TestEmailProvider``. Only ever returns
    an SMTP provider when ``notification_mode == "smtp"`` — and even then the
    SMTP provider is inert (no network) until called with ``live=True``.
    """
    if settings.notification_mode == "smtp":
        return SmtpEmailProvider.from_settings(settings)
    return TestEmailProvider()
