from pact.mcp import PactMcpHttpClient, handle_jsonrpc_message


class FakeHttpClient:
    def __init__(self):
        self.calls = []

    def get_json(self, path, params=None):
        self.calls.append(("GET", path, params))
        if path == "/api/connectors/health":
            return {"owner": params["owner"], "connectors": []}
        if path == "/api/pacts":
            return [{"id": "pact_1", "title": "Ship"}]
        raise AssertionError(f"unexpected GET {path}")


def test_mcp_initialize_and_tools_list():
    client = PactMcpHttpClient("http://127.0.0.1:8000")

    init = handle_jsonrpc_message(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        client,
    )
    assert init["id"] == 1
    assert init["result"]["serverInfo"]["name"] == "pact"
    assert init["result"]["capabilities"]["tools"] == {}

    tools = handle_jsonrpc_message(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        client,
    )
    names = {tool["name"] for tool in tools["result"]["tools"]}
    assert {"pact_connector_health", "pact_list_pacts"}.issubset(names)


def test_mcp_tool_call_routes_to_pact_api_and_returns_json_text():
    fake = FakeHttpClient()

    response = handle_jsonrpc_message(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "pact_connector_health",
                "arguments": {"owner": "agent-owner@example.com"},
            },
        },
        fake,
    )

    assert fake.calls == [
        ("GET", "/api/connectors/health", {"owner": "agent-owner@example.com"})
    ]
    assert response["id"] == 3
    assert response["result"]["content"][0]["type"] == "text"
    assert '"agent-owner@example.com"' in response["result"]["content"][0]["text"]


def test_mcp_tool_call_rejects_unknown_tool():
    response = handle_jsonrpc_message(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "not_real", "arguments": {}},
        },
        PactMcpHttpClient("http://127.0.0.1:8000"),
    )

    assert response["id"] == 4
    assert response["error"]["code"] == -32601
