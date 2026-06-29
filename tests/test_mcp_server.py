import asyncio
import io
import json
import urllib.error
from unittest.mock import patch

import pytest

from pact.mcp import PactApiError, PactClient, build_server


class FakeClient:
    """Records the (method, path, params, body) of every call the tools make."""

    def __init__(self, result=None):
        self.calls = []
        self._result = result if result is not None else {"ok": True}

    def get_json(self, path, params=None):
        self.calls.append(("GET", path, params, None))
        return self._result

    def post_json(self, path, body=None):
        self.calls.append(("POST", path, None, body))
        return self._result

    def post_multipart(self, path, fields, files):
        self.calls.append(("MULTIPART", path, fields, list(files.keys())))
        return self._result


def _text(result):
    """call_tool returns a list of content blocks; return the first block's text."""
    block = result[0] if isinstance(result, (list, tuple)) else result
    return block.text


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

def test_server_registers_full_tool_set():
    server = build_server(FakeClient())
    names = {t.name for t in asyncio.run(server.list_tools())}
    expected = {
        # make
        "pact_draft", "pact_create", "pact_confirm", "pact_set_owner", "pact_start",
        # review
        "pact_list_pacts", "pact_get", "pact_list_proofs", "pact_packet",
        "pact_profile", "pact_charities", "pact_connector_health",
        # recall
        "pact_get_coaching",
        # coach
        "pact_coach",
        # submit evidence
        "pact_issue_proof_token", "pact_submit_proof", "pact_submit_proof_image",
        # submit evidence decisions
        "pact_settle", "pact_list_reasoning_tasks",
        "pact_claim_reasoning_task", "pact_post_reasoning_result",
        # donation completion (agent-side crawl)
        "pact_provision_card", "pact_card_credential", "pact_record_donation_receipt",
    }
    assert expected.issubset(names)


def test_legacy_tool_names_preserved():
    # settings-connectors.md + older clients reference these names; keep them.
    server = build_server(FakeClient())
    names = {t.name for t in asyncio.run(server.list_tools())}
    assert {"pact_connector_health", "pact_list_pacts"}.issubset(names)


def test_draft_tool_requires_prompt():
    server = build_server(FakeClient())
    schema = {t.name: t.inputSchema for t in asyncio.run(server.list_tools())}
    assert schema["pact_draft"]["required"] == ["prompt"]
    assert "prompt" in schema["pact_draft"]["properties"]


def test_activation_tools_require_consent_in_schema():
    # The backend 422s unless consent_acknowledged is true, so the schema must force
    # the agent to supply it rather than silently defaulting it false.
    server = build_server(FakeClient())
    schema = {t.name: t.inputSchema for t in asyncio.run(server.list_tools())}
    assert "consent_acknowledged" in schema["pact_confirm"]["required"]
    assert "consent_acknowledged" in schema["pact_create"]["required"]


def test_submit_proof_text_tool_has_no_image_path_param():
    # image_path is a server-side path footgun; photos go through pact_submit_proof_image.
    server = build_server(FakeClient())
    schema = {t.name: t.inputSchema for t in asyncio.run(server.list_tools())}
    assert "image_path" not in schema["pact_submit_proof"]["properties"]


# ---------------------------------------------------------------------------
# Make
# ---------------------------------------------------------------------------

def test_draft_routes_to_draft_endpoint():
    fake = FakeClient(result={"id": "pact_1", "title": "Ship"})
    server = build_server(fake)
    res = asyncio.run(server.call_tool("pact_draft", {"prompt": "run daily"}))
    assert fake.calls == [("POST", "/api/pacts/draft", None, {"prompt": "run daily"})]
    assert json.loads(_text(res))["id"] == "pact_1"


def test_create_sends_structured_body_without_none_extras():
    fake = FakeClient(result={"id": "pact_2"})
    server = build_server(fake)
    asyncio.run(server.call_tool("pact_create", {
        "goal_title": "Run", "days_per_week": 3, "weeks": 4,
        "stake_amount_cents": 5000, "charity_id": "charity_water",
        "consent_acknowledged": True, "owner": "a@b.com",
    }))
    method, path, _, body = fake.calls[0]
    assert (method, path) == ("POST", "/api/pacts/create")
    assert body["goal_title"] == "Run"
    assert body["days_per_week"] == 3
    assert body["weeks"] == 4
    assert body["stake_amount_cents"] == 5000
    assert body["charity_id"] == "charity_water"
    assert body["consent_acknowledged"] is True
    assert body["owner"] == "a@b.com"
    # Optional fields the agent did not pass must not be sent as null.
    assert "goal_template" not in body
    assert "signer_name" not in body


def test_confirm_posts_to_pacts_root():
    fake = FakeClient(result={"id": "pact_2", "status": "active"})
    server = build_server(fake)
    asyncio.run(server.call_tool("pact_confirm", {
        "pact_id": "pact_2", "stake_amount_cents": 5000, "charity_id": "charity_water",
        "consent_acknowledged": True,
    }))
    assert fake.calls == [(
        "POST", "/api/pacts", None,
        {"pact_id": "pact_2", "stake_amount_cents": 5000,
         "charity_id": "charity_water", "consent_acknowledged": True},
    )]


def test_set_owner_posts_to_owner_path():
    fake = FakeClient()
    server = build_server(fake)
    asyncio.run(server.call_tool("pact_set_owner", {"pact_id": "p", "owner": "a@b.com"}))
    assert fake.calls == [("POST", "/api/pacts/p/owner", None, {"owner": "a@b.com"})]


def test_start_posts_to_start_path():
    fake = FakeClient()
    server = build_server(fake)
    asyncio.run(server.call_tool("pact_start", {"pact_id": "p"}))
    assert fake.calls == [("POST", "/api/pacts/p/start", None, {})]


# ---------------------------------------------------------------------------
# Review
# ---------------------------------------------------------------------------

def test_get_routes_with_path_id():
    fake = FakeClient(result={"id": "pact_9"})
    server = build_server(fake)
    asyncio.run(server.call_tool("pact_get", {"pact_id": "pact_9"}))
    assert fake.calls == [("GET", "/api/pacts/pact_9", None, None)]


def test_list_pacts_routes_with_owner_param():
    fake = FakeClient(result=[])
    server = build_server(fake)
    asyncio.run(server.call_tool("pact_list_pacts", {"owner": "a@b.com"}))
    assert fake.calls == [("GET", "/api/pacts", {"owner": "a@b.com"}, None)]


def test_list_proofs_reads_proofs():
    fake = FakeClient(result=[])
    server = build_server(fake)
    asyncio.run(server.call_tool("pact_list_proofs", {"pact_id": "p"}))
    assert fake.calls == [("GET", "/api/pacts/p/proofs", None, None)]


def test_packet_reads_packet():
    fake = FakeClient(result={"verdict": {}})
    server = build_server(fake)
    asyncio.run(server.call_tool("pact_packet", {"pact_id": "p"}))
    assert fake.calls == [("GET", "/api/pacts/p/packet", None, None)]


def test_profile_reads_with_owner():
    fake = FakeClient(result={"owner": "a@b.com"})
    server = build_server(fake)
    asyncio.run(server.call_tool("pact_profile", {"owner": "a@b.com"}))
    assert fake.calls == [("GET", "/api/profile", {"owner": "a@b.com"}, None)]


def test_charities_reads_catalogue():
    fake = FakeClient(result=[])
    server = build_server(fake)
    asyncio.run(server.call_tool("pact_charities", {}))
    assert fake.calls == [("GET", "/api/charities", None, None)]


def test_list_return_is_a_single_json_array_block():
    # FastMCP splits a raw list return into one content block per element, which
    # gives the agent no parseable array. Tools must return one JSON text block.
    fake = FakeClient(result=[{"id": "charity_water"}, {"id": "redcross"}])
    server = build_server(fake)
    res = asyncio.run(server.call_tool("pact_charities", {}))
    assert len(res) == 1
    parsed = json.loads(_text(res))
    assert isinstance(parsed, list)
    assert [c["id"] for c in parsed] == ["charity_water", "redcross"]


def test_connector_health_reads_with_owner():
    fake = FakeClient(result={"owner": "a@b.com", "connectors": []})
    server = build_server(fake)
    asyncio.run(server.call_tool("pact_connector_health", {"owner": "a@b.com"}))
    assert fake.calls == [("GET", "/api/connectors/health", {"owner": "a@b.com"}, None)]


# ---------------------------------------------------------------------------
# Recall + coach
# ---------------------------------------------------------------------------

def test_get_coaching_reads_thread():
    fake = FakeClient(result=[])
    server = build_server(fake)
    asyncio.run(server.call_tool("pact_get_coaching", {"pact_id": "pact_2"}))
    assert fake.calls == [("GET", "/api/pacts/pact_2/coach", None, None)]


def test_coach_posts_message():
    fake = FakeClient(result={"inbound": {}, "outbound": {}})
    server = build_server(fake)
    asyncio.run(server.call_tool(
        "pact_coach", {"pact_id": "pact_2", "message": "how's it going"}
    ))
    assert fake.calls == [
        ("POST", "/api/pacts/pact_2/coach", None, {"message": "how's it going"})
    ]


# ---------------------------------------------------------------------------
# Submit evidence
# ---------------------------------------------------------------------------

def test_issue_proof_token_posts():
    fake = FakeClient(result={"token": "t"})
    server = build_server(fake)
    asyncio.run(server.call_tool("pact_issue_proof_token", {"pact_id": "pact_3"}))
    assert fake.calls == [("POST", "/api/pacts/pact_3/proof-token", None, {})]


def test_submit_proof_posts_body_with_defaults():
    fake = FakeClient(result={"status": "passed"})
    server = build_server(fake)
    asyncio.run(server.call_tool("pact_submit_proof", {
        "pact_id": "pact_3", "modality": "text", "token": "tok",
    }))
    assert fake.calls == [(
        "POST", "/api/pacts/pact_3/proofs", None,
        {"modality": "text", "token": "tok", "content_ok": True, "image_path": None},
    )]


def test_submit_proof_image_uses_multipart(tmp_path):
    img = tmp_path / "proof.jpg"
    img.write_bytes(b"\xff\xd8\xff fake-jpeg")
    fake = FakeClient(result={"status": "ambiguous"})
    server = build_server(fake)
    asyncio.run(server.call_tool("pact_submit_proof_image", {
        "pact_id": "pact_4", "token": "tok", "image_path": str(img),
    }))
    method, path, fields, file_keys = fake.calls[0]
    assert method == "MULTIPART"
    assert path == "/api/pacts/pact_4/proofs/image"
    assert fields == {"token": "tok"}
    assert file_keys == ["image"]


# ---------------------------------------------------------------------------
# Submit evidence decisions
# ---------------------------------------------------------------------------

def test_settle_posts():
    fake = FakeClient(result={"status": "succeeded"})
    server = build_server(fake)
    asyncio.run(server.call_tool("pact_settle", {"pact_id": "pact_5"}))
    assert fake.calls == [("POST", "/api/pacts/pact_5/settle", None, {})]


def test_list_reasoning_tasks_filters():
    fake = FakeClient(result=[])
    server = build_server(fake)
    asyncio.run(server.call_tool("pact_list_reasoning_tasks", {
        "capability": "vision", "status": "pending",
    }))
    assert fake.calls == [(
        "GET", "/api/reasoning-tasks",
        {"capability": "vision", "status": "pending"}, None,
    )]


def test_claim_reasoning_task_posts_agent_and_caps():
    fake = FakeClient(result={"id": "task_1", "status": "claimed"})
    server = build_server(fake)
    asyncio.run(server.call_tool("pact_claim_reasoning_task", {
        "task_id": "task_1", "agent_name": "claude", "capabilities": ["vision"],
    }))
    assert fake.calls == [(
        "POST", "/api/reasoning-tasks/task_1/claim", None,
        {"agent_name": "claude", "capabilities": ["vision"]},
    )]


def test_post_reasoning_result_wraps_result():
    fake = FakeClient(result={"id": "task_1", "status": "done"})
    server = build_server(fake)
    decision = {"status": "passed", "reason": "rubric met"}
    asyncio.run(server.call_tool("pact_post_reasoning_result", {
        "task_id": "task_1", "result": decision,
    }))
    assert fake.calls == [(
        "POST", "/api/reasoning-tasks/task_1/result", None, {"result": decision},
    )]


# ---------------------------------------------------------------------------
# Donation completion (agent-side crawl)
# ---------------------------------------------------------------------------

def test_provision_card_posts_to_donation_card():
    fake = FakeClient(result={"provisioned": True, "last4": "4242"})
    server = build_server(fake)
    asyncio.run(server.call_tool("pact_provision_card", {"pact_id": "pact_7"}))
    assert fake.calls == [("POST", "/api/pacts/pact_7/donation/card", None, {})]


def test_card_credential_posts_to_card_credential_endpoint():
    fake = FakeClient(result={"number": "4242424242424242", "cvc": "123"})
    server = build_server(fake)
    res = asyncio.run(server.call_tool("pact_card_credential", {"pact_id": "pact_7"}))
    assert fake.calls == [("POST", "/api/pacts/pact_7/donation/card-credential", None, {})]
    assert json.loads(_text(res))["number"] == "4242424242424242"


def test_record_donation_receipt_posts_evidence_without_none_extras():
    fake = FakeClient(result={"receipt_status": "provider_confirmed"})
    server = build_server(fake)
    asyncio.run(server.call_tool("pact_record_donation_receipt", {
        "pact_id": "pact_7", "receipt_status": "provider_confirmed", "receipt_ref": "CW-123",
    }))
    method, path, _, body = fake.calls[0]
    assert (method, path) == ("POST", "/api/pacts/pact_7/donation/receipt")
    assert body["receipt_status"] == "provider_confirmed"
    assert body["receipt_ref"] == "CW-123"
    # Optional fields the agent did not pass must not be sent as null.
    assert "receipt_url" not in body
    assert "confirmation_notes" not in body


# ---------------------------------------------------------------------------
# PactClient HTTP behaviour
# ---------------------------------------------------------------------------

class _FakeResp:
    def __init__(self, body, status=200):
        self._body = body
        self.status = status

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_client_sends_bearer_token_and_query():
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["req"] = req
        return _FakeResp(b'{"ok": true}')

    with patch("urllib.request.urlopen", fake_urlopen):
        client = PactClient("http://x", token="pat_abc")
        out = client.get_json("/api/pacts", {"owner": "a@b.com"})

    assert out == {"ok": True}
    req = captured["req"]
    assert req.get_header("Authorization") == "Bearer pat_abc"
    assert req.full_url == "http://x/api/pacts?owner=a%40b.com"


def test_client_post_json_sends_body():
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["req"] = req
        return _FakeResp(b'{"id": "pact_1"}')

    with patch("urllib.request.urlopen", fake_urlopen):
        client = PactClient("http://x")
        client.post_json("/api/pacts/draft", {"prompt": "go"})

    req = captured["req"]
    assert req.method == "POST"
    assert json.loads(req.data) == {"prompt": "go"}
    assert req.get_header("Content-type") == "application/json"


def test_client_multipart_frames_file_and_fields():
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["req"] = req
        return _FakeResp(b'{"status": "ambiguous"}')

    with patch("urllib.request.urlopen", fake_urlopen):
        client = PactClient("http://x")
        client.post_multipart(
            "/api/pacts/p/proofs/image",
            fields={"token": "tok"},
            files={"image": ("proof.jpg", b"BYTES", "image/jpeg")},
        )

    req = captured["req"]
    ctype = req.get_header("Content-type")
    assert ctype.startswith("multipart/form-data; boundary=")
    body = req.data
    assert b'name="token"' in body
    assert b"tok" in body
    assert b'name="image"; filename="proof.jpg"' in body
    assert b"BYTES" in body


def test_client_surfaces_422_detail():
    def fake_urlopen(req, timeout=None):
        raise urllib.error.HTTPError(
            url="http://x/api/pacts/draft",
            code=422,
            msg="Unprocessable",
            hdrs=None,
            fp=io.BytesIO(b'{"detail": "I cannot help stake on that."}'),
        )

    with patch("urllib.request.urlopen", fake_urlopen):
        client = PactClient("http://x")
        with pytest.raises(PactApiError) as exc:
            client.post_json("/api/pacts/draft", {"prompt": "bad"})

    assert exc.value.status == 422
    assert "stake on that" in exc.value.detail
