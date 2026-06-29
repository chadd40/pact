from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from typing import Any, Protocol


class JsonClient(Protocol):
    def get_json(self, path: str, params: dict | None = None) -> Any:
        ...


class PactMcpHttpClient:
    def __init__(self, base_url: str, token: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token

    def get_json(self, path: str, params: dict | None = None) -> Any:
        query = urllib.parse.urlencode(params or {})
        url = f"{self.base_url}{path}" + (f"?{query}" if query else "")
        headers = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))


TOOLS = [
    {
        "name": "pact_connector_health",
        "description": "Inspect Pact connector setup health for an owner.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "owner": {
                    "type": "string",
                    "description": "Pact owner email or local owner id.",
                }
            },
            "required": ["owner"],
        },
    },
    {
        "name": "pact_list_pacts",
        "description": "List Pact commitments for an owner.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "owner": {
                    "type": "string",
                    "description": "Pact owner email or local owner id.",
                }
            },
            "required": ["owner"],
        },
    },
]


def _response(msg_id: Any, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _error(msg_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def _tool_result(data: Any) -> dict:
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(data, ensure_ascii=False, indent=2),
            }
        ]
    }


def _call_tool(name: str, args: dict, client: JsonClient) -> Any:
    if name == "pact_connector_health":
        owner = str(args.get("owner", "")).strip()
        if not owner:
            raise ValueError("owner is required")
        return client.get_json("/api/connectors/health", {"owner": owner})
    if name == "pact_list_pacts":
        owner = str(args.get("owner", "")).strip()
        if not owner:
            raise ValueError("owner is required")
        return client.get_json("/api/pacts", {"owner": owner})
    raise KeyError(name)


def handle_jsonrpc_message(message: dict, client: JsonClient) -> dict | None:
    msg_id = message.get("id")
    method = message.get("method")

    if method == "notifications/initialized":
        return None
    if method == "initialize":
        return _response(
            msg_id,
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "pact", "version": "0.1.0"},
            },
        )
    if method == "tools/list":
        return _response(msg_id, {"tools": TOOLS})
    if method == "tools/call":
        params = message.get("params") or {}
        name = str(params.get("name", ""))
        arguments = params.get("arguments") or {}
        try:
            return _response(msg_id, _tool_result(_call_tool(name, arguments, client)))
        except KeyError:
            return _error(msg_id, -32601, f"unknown tool: {name}")
        except ValueError as exc:
            return _error(msg_id, -32602, str(exc))
    return _error(msg_id, -32601, f"unknown method: {method}")


def serve_stdio(client: JsonClient, *, stdin=None, stdout=None) -> int:
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
            response = handle_jsonrpc_message(message, client)
        except Exception as exc:
            response = _error(None, -32700, f"invalid request: {exc}")
        if response is not None:
            stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            stdout.flush()
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="pact mcp")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--agent-token", default=None)
    args = parser.parse_args(argv)
    return serve_stdio(PactMcpHttpClient(args.base_url, args.agent_token))
