"""Pact's MCP server — the agent-agnostic surface over the Pact HTTP API.

Built on the official MCP Python SDK (FastMCP). The server is a **thin client**:
every tool is a 1:1 pass-through to a Pact API endpoint. The *reasoning* — drafting a
pact + frozen rubric, judging a proof against that rubric, writing coaching grounded in
pace, writing a verdict — lives in the agent (the `/pact` skill is the brain). A tool
cannot use the agent's model, so no reasoning is baked into a tool here.

Two layers, both unit-testable:

  * ``PactClient``  — urllib HTTP (get/post/multipart) with bearer auth. No SDK import.
  * ``build_server(client)`` — registers the FastMCP tools as typed closures over the
    client; the SDK is imported lazily so the other CLI paths don't pay for it.

Every tool returns a single JSON **string** (the whole API response), so the agent
always gets one parseable text block — including for list endpoints, which FastMCP
would otherwise split into one block per element.
"""

from __future__ import annotations

import argparse
import functools
import json
import mimetypes
import os
import secrets
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


# ---------------------------------------------------------------------------
# HTTP client
# ---------------------------------------------------------------------------

class PactApiError(Exception):
    """A non-2xx response from the Pact API.

    ``detail`` carries the server's ``detail`` text when present (e.g. the 422
    supportive refusal a draft of an unsafe goal returns) so the agent can surface
    it verbatim rather than a generic failure.
    """

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(f"Pact API {status}: {detail}")
        self.status = status
        self.detail = detail


class PactClient:
    """Minimal JSON HTTP client for the Pact API (no third-party deps)."""

    def __init__(self, base_url: str, token: str | None = None, *, timeout: int = 30) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def get_json(self, path: str, params: dict | None = None) -> Any:
        return self._request("GET", path, params=params)

    def post_json(self, path: str, body: dict | None = None) -> Any:
        data = json.dumps(body or {}).encode("utf-8")
        return self._request(
            "POST", path, data=data, headers={"Content-Type": "application/json"}
        )

    def post_multipart(self, path: str, fields: dict, files: dict) -> Any:
        """POST multipart/form-data.

        ``files`` maps a field name to ``(filename, content_bytes, content_type)``.
        Used by the photo-proof tool; the body is framed by hand so we keep urllib-only.
        """
        boundary = "----pactmcp" + secrets.token_hex(16)
        body = bytearray()
        for name, value in (fields or {}).items():
            body += f"--{boundary}\r\n".encode()
            body += f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
            body += f"{value}\r\n".encode()
        for name, (filename, content, content_type) in (files or {}).items():
            body += f"--{boundary}\r\n".encode()
            body += (
                f'Content-Disposition: form-data; name="{name}"; '
                f'filename="{filename}"\r\n'
            ).encode()
            body += f"Content-Type: {content_type}\r\n\r\n".encode()
            body += content
            body += b"\r\n"
        body += f"--{boundary}--\r\n".encode()
        headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
        return self._request("POST", path, data=bytes(body), headers=headers)

    # -- internals ----------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        data: bytes | None = None,
        headers: dict | None = None,
    ) -> Any:
        query = urllib.parse.urlencode(params or {})
        url = f"{self.base_url}{path}" + (f"?{query}" if query else "")
        hdrs = dict(headers or {})
        if self.token:
            hdrs["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raise PactApiError(exc.code, _error_detail(exc)) from exc
        return json.loads(raw) if raw else None


def _error_detail(exc: urllib.error.HTTPError) -> str:
    try:
        raw = exc.read().decode("utf-8")
    except Exception:
        raw = ""
    if raw:
        try:
            payload = json.loads(raw)
        except Exception:
            return raw
        if isinstance(payload, dict) and "detail" in payload:
            return str(payload["detail"])
        return raw
    return getattr(exc, "reason", None) or str(exc)


def _dumps(value: Any) -> str:
    """Serialize an API response to one JSON text block for the agent."""
    return json.dumps(value, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------

SERVER_INSTRUCTIONS = (
    "Pact's commitment engine. Tools are thin pass-throughs to the local Pact API; "
    "you are the brain. Make pacts (draft -> confirm), review them, recall what you "
    "told the user (pact_get_coaching) before you coach, submit evidence, and submit "
    "evidence decisions (settle, or claim + post a reasoning-task result). Real money "
    "only moves on explicit human Link approval. Refuse unsafe goals at draft time."
)


def build_server(client: Any):
    """Build the FastMCP server, registering every tool as a closure over ``client``.

    ``client`` only needs ``get_json`` / ``post_json`` / ``post_multipart`` (so tests
    inject a fake). The SDK is imported here to keep it off the other CLI paths.
    """
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("pact", instructions=SERVER_INSTRUCTIONS)
    # Every tool returns one JSON text block (see _dumps); disable structured output
    # so FastMCP doesn't also emit a double-encoded structuredContent payload.
    tool = functools.partial(server.tool, structured_output=False)

    # -- make ---------------------------------------------------------------

    @tool(
        name="pact_draft",
        description=(
            "Draft a pact + frozen rubric from natural language. Returns the draft. "
            "An unsafe/self-harm goal comes back as a supportive refusal (422 detail) "
            "— surface that text, do not retry."
        ),
    )
    def pact_draft(prompt: str) -> str:
        """prompt: the user's goal in natural language."""
        return _dumps(client.post_json("/api/pacts/draft", {"prompt": prompt}))

    @tool(
        name="pact_create",
        description=(
            "Create AND activate a structured pact in one shot from explicit cadence + "
            "stake terms (no separate confirm/start step; use pact_draft for a "
            "non-committed draft). Set consent_acknowledged=true only after the user "
            "acknowledges real money goes to charity on failure — 422s otherwise."
        ),
    )
    def pact_create(
        goal_title: str,
        days_per_week: int,
        weeks: int,
        stake_amount_cents: int,
        charity_id: str,
        consent_acknowledged: bool,
        owner: str | None = None,
        goal_template: str | None = None,
        agent: str | None = None,
        description: str | None = None,
        signer_name: str | None = None,
        card_art: str | None = None,
    ) -> str:
        body: dict[str, Any] = {
            "goal_title": goal_title,
            "days_per_week": days_per_week,
            "weeks": weeks,
            "stake_amount_cents": stake_amount_cents,
            "charity_id": charity_id,
            "consent_acknowledged": consent_acknowledged,
        }
        for key, value in (
            ("owner", owner),
            ("goal_template", goal_template),
            ("agent", agent),
            ("description", description),
            ("signer_name", signer_name),
            ("card_art", card_art),
        ):
            if value is not None:
                body[key] = value
        return _dumps(client.post_json("/api/pacts/create", body))

    @tool(
        name="pact_confirm",
        description=(
            "Confirm a draft with its stake + charity and activate it (no money moves yet). "
            "Set consent_acknowledged=true only after the user explicitly acknowledges that "
            "real money goes to charity on failure — the call returns 422 otherwise."
        ),
    )
    def pact_confirm(
        pact_id: str,
        stake_amount_cents: int,
        charity_id: str,
        consent_acknowledged: bool,
    ) -> str:
        return _dumps(
            client.post_json(
                "/api/pacts",
                {
                    "pact_id": pact_id,
                    "stake_amount_cents": stake_amount_cents,
                    "charity_id": charity_id,
                    "consent_acknowledged": consent_acknowledged,
                },
            )
        )

    @tool(name="pact_set_owner", description="Set the owner (email or local id) of a pact.")
    def pact_set_owner(pact_id: str, owner: str) -> str:
        return _dumps(client.post_json(f"/api/pacts/{pact_id}/owner", {"owner": owner}))

    @tool(name="pact_start", description="Activate a confirmed pact (idempotent).")
    def pact_start(pact_id: str) -> str:
        return _dumps(client.post_json(f"/api/pacts/{pact_id}/start", {}))

    # -- review -------------------------------------------------------------

    @tool(name="pact_list_pacts", description="List an owner's pacts (with progress + cadence).")
    def pact_list_pacts(owner: str) -> str:
        return _dumps(client.get_json("/api/pacts", {"owner": owner}))

    @tool(name="pact_get", description="Get one pact's full state, progress, and cadence.")
    def pact_get(pact_id: str) -> str:
        return _dumps(client.get_json(f"/api/pacts/{pact_id}"))

    @tool(name="pact_list_proofs", description="List a pact's submitted proofs, oldest first.")
    def pact_list_proofs(pact_id: str) -> str:
        return _dumps(client.get_json(f"/api/pacts/{pact_id}/proofs"))

    @tool(
        name="pact_packet",
        description="Get the evidence + verdict packet (with coaching log). 404 until settled.",
    )
    def pact_packet(pact_id: str) -> str:
        return _dumps(client.get_json(f"/api/pacts/{pact_id}/packet"))

    @tool(name="pact_profile", description="An owner's streak + kept/failed history.")
    def pact_profile(owner: str) -> str:
        return _dumps(client.get_json("/api/profile", {"owner": owner}))

    @tool(name="pact_charities", description="The charity catalogue for the confirm picker.")
    def pact_charities() -> str:
        return _dumps(client.get_json("/api/charities"))

    @tool(name="pact_connector_health", description="Inspect an owner's connector setup health.")
    def pact_connector_health(owner: str) -> str:
        return _dumps(client.get_json("/api/connectors/health", {"owner": owner}))

    # -- recall + coach -----------------------------------------------------

    @tool(
        name="pact_get_coaching",
        description=(
            "Read the full coaching thread (inbound user + outbound agent messages). "
            "Read this BEFORE coaching so your next message stays consistent with what "
            "you already told the user."
        ),
    )
    def pact_get_coaching(pact_id: str) -> str:
        return _dumps(client.get_json(f"/api/pacts/{pact_id}/coach"))

    @tool(
        name="pact_coach",
        description="Send a message into a pact's coaching thread; returns inbound + reply.",
    )
    def pact_coach(pact_id: str, message: str) -> str:
        return _dumps(client.post_json(f"/api/pacts/{pact_id}/coach", {"message": message}))

    # -- submit evidence ----------------------------------------------------

    @tool(
        name="pact_issue_proof_token",
        description="Issue a single-use proof token (nonce) required to submit a proof.",
    )
    def pact_issue_proof_token(pact_id: str) -> str:
        return _dumps(client.post_json(f"/api/pacts/{pact_id}/proof-token", {}))

    @tool(
        name="pact_submit_proof",
        description=(
            "Submit a text/log/url proof with a valid token. The backend judges it "
            "against the frozen rubric and returns the judged proof. For photo proofs "
            "use pact_submit_proof_image instead."
        ),
    )
    def pact_submit_proof(
        pact_id: str,
        modality: str,
        token: str,
        content_ok: bool = True,
    ) -> str:
        return _dumps(
            client.post_json(
                f"/api/pacts/{pact_id}/proofs",
                {
                    "modality": modality,
                    "token": token,
                    "content_ok": content_ok,
                    "image_path": None,
                },
            )
        )

    @tool(
        name="pact_submit_proof_image",
        description=(
            "Submit a photo proof: reads a local image file and uploads it with a valid "
            "token. The backend strips EXIF, pHash-dedups, and judges it."
        ),
    )
    def pact_submit_proof_image(pact_id: str, token: str, image_path: str) -> str:
        with open(image_path, "rb") as handle:
            content = handle.read()
        filename = os.path.basename(image_path) or "proof"
        content_type = mimetypes.guess_type(image_path)[0] or "application/octet-stream"
        return _dumps(
            client.post_multipart(
                f"/api/pacts/{pact_id}/proofs/image",
                fields={"token": token},
                files={"image": (filename, content, content_type)},
            )
        )

    # -- submit evidence decisions -----------------------------------------

    @tool(
        name="pact_settle",
        description="Settle a pact now: judge pending proofs, compute the verdict, fire donation if failed.",
    )
    def pact_settle(pact_id: str) -> str:
        return _dumps(client.post_json(f"/api/pacts/{pact_id}/settle", {}))

    @tool(
        name="pact_list_reasoning_tasks",
        description=(
            "List pending broker reasoning tasks (draft/judge_proof/coach/verdict) you "
            "can resolve. Requires an agent token with the claim_tasks scope."
        ),
    )
    def pact_list_reasoning_tasks(
        capability: str | None = None,
        status: str | None = None,
    ) -> str:
        params: dict[str, Any] = {}
        if capability is not None:
            params["capability"] = capability
        if status is not None:
            params["status"] = status
        return _dumps(client.get_json("/api/reasoning-tasks", params or None))

    @tool(
        name="pact_claim_reasoning_task",
        description="Claim a pending reasoning task so you can resolve it. Requires claim_tasks scope.",
    )
    def pact_claim_reasoning_task(
        task_id: str,
        agent_name: str,
        capabilities: list[str],
    ) -> str:
        return _dumps(
            client.post_json(
                f"/api/reasoning-tasks/{task_id}/claim",
                {"agent_name": agent_name, "capabilities": capabilities},
            )
        )

    @tool(
        name="pact_post_reasoning_result",
        description=(
            "Post the resolved result of a claimed reasoning task. The result IS the "
            "evidence decision (e.g. judge: {status, reason, checklist}; coach: {message}; "
            "verdict prose; draft pact). Requires the post_results scope."
        ),
    )
    def pact_post_reasoning_result(task_id: str, result: dict) -> str:
        return _dumps(
            client.post_json(f"/api/reasoning-tasks/{task_id}/result", {"result": result})
        )

    # -- donation completion (agent-side crawl) -----------------------------

    @tool(
        name="pact_provision_card",
        description=(
            "Provision the single-use, merchant-locked virtual card for a donated pact's "
            "charity payment. Returns only non-secret metadata (last4/brand/expiry); the "
            "PAN stays server-side. Call this before pact_card_credential. Live mode "
            "requires the human to have approved the spend in Link first (status donated)."
        ),
    )
    def pact_provision_card(pact_id: str) -> str:
        return _dumps(client.post_json(f"/api/pacts/{pact_id}/donation/card", {}))

    @tool(
        name="pact_card_credential",
        description=(
            "Get the FULL single-use card (number/cvc/expiry) to enter on the chosen "
            "charity's donate page (agent-side crawl). The card is single-use and locked to "
            "that one charity — treat it as a secret, use it only on that charity's page. "
            "Owner-scoped when auth is on. Provision the card first with pact_provision_card."
        ),
    )
    def pact_card_credential(pact_id: str) -> str:
        return _dumps(client.post_json(f"/api/pacts/{pact_id}/donation/card-credential", {}))

    @tool(
        name="pact_record_donation_receipt",
        description=(
            "Record/confirm the charity donation receipt after you paid on the charity's "
            "page. Provide the evidence you have: a confirmation reference (receipt_ref), a "
            "receipt URL (receipt_url), and/or a saved screenshot path (receipt_artifact_path). "
            "Use receipt_status='provider_confirmed' only with real evidence. This flips the "
            "pact from 'approved' to a charity-confirmed donation."
        ),
    )
    def pact_record_donation_receipt(
        pact_id: str,
        receipt_status: str = "manual_receipt",
        receipt_ref: str | None = None,
        receipt_url: str | None = None,
        receipt_source: str | None = None,
        receipt_artifact_path: str | None = None,
        confirmation_notes: str | None = None,
    ) -> str:
        body: dict[str, Any] = {"receipt_status": receipt_status}
        for key, value in (
            ("receipt_ref", receipt_ref),
            ("receipt_url", receipt_url),
            ("receipt_source", receipt_source),
            ("receipt_artifact_path", receipt_artifact_path),
            ("confirmation_notes", confirmation_notes),
        ):
            if value is not None:
                body[key] = value
        return _dumps(client.post_json(f"/api/pacts/{pact_id}/donation/receipt", body))

    return server


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="pact mcp")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--agent-token", default=None)
    args = parser.parse_args(argv)
    server = build_server(PactClient(args.base_url, args.agent_token))
    server.run("stdio")
    return 0
