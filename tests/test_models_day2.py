from datetime import datetime, timezone

from pact.models import CoachingMessage, Profile


def _utc(y, mo, d, h=0, mi=0, s=0):
    return datetime(y, mo, d, h, mi, s, tzinfo=timezone.utc)


def test_profile_defaults_empty():
    p = Profile(owner="demo@pact.local")
    assert p.owner == "demo@pact.local"
    assert p.pact_ids == []
    assert p.current_streak == 0
    assert p.best_streak == 0
    assert p.kept == 0
    assert p.failed == 0
    assert p.history == []


def test_profile_with_values():
    p = Profile(
        owner="demo@pact.local",
        pact_ids=["pact_a1b2c3"],
        current_streak=3,
        best_streak=5,
        kept=4,
        failed=1,
        history=[
            {
                "pact_id": "pact_a1b2c3",
                "title": "Work out 5x this week",
                "outcome": "succeeded",
                "ended_at": "2026-06-28T23:59:59+00:00",
            }
        ],
    )
    assert p.pact_ids == ["pact_a1b2c3"]
    assert p.current_streak == 3
    assert p.best_streak == 5
    assert p.kept == 4
    assert p.failed == 1
    assert p.history[0]["outcome"] == "succeeded"


def test_profile_round_trip_json():
    p = Profile(
        owner="demo@pact.local",
        pact_ids=["pact_a1b2c3", "pact_d4e5f6"],
        current_streak=2,
        best_streak=2,
        kept=2,
        failed=0,
        history=[
            {
                "pact_id": "pact_a1b2c3",
                "title": "Run daily",
                "outcome": "succeeded",
                "ended_at": "2026-06-20T12:00:00+00:00",
            }
        ],
    )
    restored = Profile.model_validate_json(p.model_dump_json())
    assert restored == p
    assert restored.history == p.history


def test_coaching_message_defaults():
    m = CoachingMessage(
        id="msg_3",
        pact_id="pact_a1b2c3",
        direction="outbound",
        trigger="mid_week",
        body="2 of 5 done, 2 days left - you need 3.",
        sent_at=_utc(2026, 6, 25, 9, 0, 0),
    )
    assert m.id == "msg_3"
    assert m.pact_id == "pact_a1b2c3"
    assert m.direction == "outbound"
    assert m.trigger == "mid_week"
    assert m.channel == "web"
    assert m.pact_state_snapshot == {}
    assert m.body == "2 of 5 done, 2 days left - you need 3."
    assert m.sent_at == _utc(2026, 6, 25, 9, 0, 0)


def test_coaching_message_with_snapshot_and_channel():
    m = CoachingMessage(
        id="msg_4",
        pact_id="pact_a1b2c3",
        direction="inbound",
        trigger="reply",
        pact_state_snapshot={"valid": 2, "target": 5, "days_left": 2},
        channel="email",
        body="On it, two sessions tomorrow.",
        sent_at=_utc(2026, 6, 25, 18, 30, 0),
    )
    assert m.direction == "inbound"
    assert m.trigger == "reply"
    assert m.channel == "email"
    assert m.pact_state_snapshot == {"valid": 2, "target": 5, "days_left": 2}


def test_coaching_message_round_trip_json():
    m = CoachingMessage(
        id="msg_5",
        pact_id="pact_a1b2c3",
        direction="outbound",
        trigger="deadline_eve",
        pact_state_snapshot={"valid": 4, "target": 5, "days_left": 1},
        channel="web",
        body="One left, one day - lock it in tonight.",
        sent_at=_utc(2026, 6, 27, 20, 0, 0),
    )
    restored = CoachingMessage.model_validate_json(m.model_dump_json())
    assert restored == m
    assert restored.pact_state_snapshot == m.pact_state_snapshot
    assert restored.sent_at == m.sent_at
