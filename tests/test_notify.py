from pact.config import Settings, load_settings
from pact.notify import (
    NotificationProvider,
    SmtpEmailProvider,
    TestEmailProvider,
    get_notification_provider,
)


def test_test_email_provider_records_to_sent_and_returns_dict():
    provider = TestEmailProvider()
    assert provider.sent == []

    result = provider.send(
        to="colehaddad40@gmail.com",
        subject="Pact nudge: 2 workouts left",
        body="You're behind pace. Two sessions to go before Sunday.",
    )

    assert result == {
        "provider": "test_email",
        "to": "colehaddad40@gmail.com",
        "subject": "Pact nudge: 2 workouts left",
    }
    assert len(provider.sent) == 1
    assert provider.sent[0] == {
        "to": "colehaddad40@gmail.com",
        "subject": "Pact nudge: 2 workouts left",
        "body": "You're behind pace. Two sessions to go before Sunday.",
    }


def test_test_email_provider_accumulates_multiple_sends():
    provider = TestEmailProvider()

    provider.send(to="a@example.com", subject="s1", body="b1")
    provider.send(to="b@example.com", subject="s2", body="b2")

    assert len(provider.sent) == 2
    assert provider.sent[0]["to"] == "a@example.com"
    assert provider.sent[1]["to"] == "b@example.com"


def test_test_email_provider_satisfies_protocol():
    provider: NotificationProvider = TestEmailProvider()
    out = provider.send(to="x@example.com", subject="s", body="b")
    assert out["provider"] == "test_email"


def test_notification_mode_defaults_to_test():
    s = Settings()
    assert s.notification_mode == "test"


def test_notification_mode_env_override_to_smtp():
    s = load_settings({"PACT_NOTIFICATION_MODE": "smtp"})
    assert s.notification_mode == "smtp"
    # Day-1/Day-2 fields remain untouched by the new env key.
    assert s.reasoning_mode == "hybrid"
    assert s.clock_mode == "real"


def test_get_notification_provider_default_returns_test_email():
    provider = get_notification_provider(Settings())
    assert isinstance(provider, TestEmailProvider)


def test_get_notification_provider_returns_smtp_when_mode_smtp():
    provider = get_notification_provider(Settings(notification_mode="smtp"))
    assert isinstance(provider, SmtpEmailProvider)


def test_smtp_provider_default_send_does_not_hit_network():
    # Default (live=False) must NOT call smtplib: returns a not-sent marker.
    provider = SmtpEmailProvider(
        host="smtp.example.com",
        port=587,
        username="bot@example.com",
        password="unused-in-test",
        from_addr="bot@example.com",
    )

    result = provider.send(
        to="colehaddad40@gmail.com",
        subject="Pact nudge",
        body="hello",
    )

    assert result["provider"] == "smtp_email"
    assert result["mode"] == "not_sent"
    assert result["to"] == "colehaddad40@gmail.com"
    assert result["subject"] == "Pact nudge"


def test_smtp_provider_builds_a_wellformed_message_without_sending():
    provider = SmtpEmailProvider(
        host="smtp.example.com",
        port=587,
        username="bot@example.com",
        password="unused-in-test",
        from_addr="bot@example.com",
    )

    msg = provider.build_message(
        to="colehaddad40@gmail.com",
        subject="Pact nudge",
        body="two sessions left",
    )

    assert msg["From"] == "bot@example.com"
    assert msg["To"] == "colehaddad40@gmail.com"
    assert msg["Subject"] == "Pact nudge"
    assert msg.get_content().strip() == "two sessions left"


def test_smtp_provider_from_settings_constructs_without_network():
    s = Settings(notification_mode="smtp")
    provider = SmtpEmailProvider.from_settings(s)
    assert isinstance(provider, SmtpEmailProvider)
    # Still inert by default — building a message touches no network.
    msg = provider.build_message(to="x@example.com", subject="s", body="b")
    assert msg["Subject"] == "s"
