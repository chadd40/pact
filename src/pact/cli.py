"""The ``pact`` console entrypoint.

Subcommands drive a LIVE Pact server over HTTP:

    pact serve   — run the reasoning worker loop (serve_http) against the queue.
                   The default reasoning provider is the deterministic
                   TestLLMProvider; a real Hermes agent instead reasons inline
                   (/pact skill) and posts results, so it does not run this.
    pact tick    — POST /api/tick once (one scheduler sweep).
    pact outbox  — relay the owner's queued coaching nudges (relay_outbox).
    pact mcp     — run Pact's stdio MCP server for any MCP-compatible agent.

Tests use ``main_async(argv, http=..., on_result=...)`` with an injected async
``httpx.AsyncClient`` bound to the ASGI app (no real network). The sync
``main(argv)`` entrypoint creates a real client and runs the async version via
``asyncio.run``.
"""
from __future__ import annotations

import argparse
import asyncio

import httpx

from .httpworker import HttpWorkerClient
from .reasoning import TestLLMProvider


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pact")
    sub = parser.add_subparsers(dest="command")

    p_serve = sub.add_parser("serve", help="run the reasoning worker loop")
    p_serve.add_argument("--base-url", default="http://localhost:8000")
    p_serve.add_argument("--agent-name", default="pact-worker")
    p_serve.add_argument(
        "--capabilities",
        default="text,vision",
        help="comma-separated capabilities this worker advertises",
    )
    p_serve.add_argument("--rounds", type=int, default=1)
    p_serve.add_argument("--agent-token", default=None)

    p_tick = sub.add_parser("tick", help="run one scheduler sweep (POST /api/tick)")
    p_tick.add_argument("--base-url", default="http://localhost:8000")

    p_preflight = sub.add_parser("preflight", help="check live-money readiness")
    p_preflight.add_argument("--base-url", default="http://localhost:8000")
    p_preflight.add_argument("--owner", required=True)
    p_preflight.add_argument("--charity-id", default=None)
    p_preflight.add_argument("--amount-cents", type=int, default=None)

    p_outbox = sub.add_parser("outbox", help="relay queued coaching nudges")
    p_outbox.add_argument("--base-url", default="http://localhost:8000")
    p_outbox.add_argument("--owner", required=True)
    p_outbox.add_argument("--agent-token", default=None)

    p_mcp = sub.add_parser("mcp", help="run the Pact MCP server over stdio")
    p_mcp.add_argument("--base-url", default="http://127.0.0.1:8000")
    p_mcp.add_argument("--agent-token", default=None)

    return parser


async def main_async(argv=None, *, http=None, on_result=None) -> int:
    """Async entry point. ``http`` injects an async httpx client (tests bind it
    to an ASGI app); ``on_result`` (tests) receives the JSON payload in lieu of
    printing. Returns a process exit code (0 on success)."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 2

    # Unknown command (argparse falls through when dest="command" is set to a
    # parsed subcommand name that isn't in our handled set below — shouldn't
    # happen, but guard for forward-compat).
    if args.command not in ("serve", "tick", "preflight", "outbox", "mcp"):
        parser.print_help()
        return 2

    if args.command == "mcp":
        from .mcp import main as mcp_main

        return mcp_main(
            [
                "--base-url",
                args.base_url,
                *(
                    ["--agent-token", args.agent_token]
                    if args.agent_token
                    else []
                ),
            ]
        )

    own_client = http is None
    client: httpx.AsyncClient
    if own_client:
        client = httpx.AsyncClient(base_url=args.base_url)
    else:
        client = http

    try:
        if args.command == "serve":
            from .httpworker import _can_handle, _task_from_dict

            provider = TestLLMProvider()
            capabilities = provider.capabilities()
            # Parse any explicit --capabilities override.
            cap_list = [c.strip() for c in args.capabilities.split(",") if c.strip()]
            if cap_list:
                capabilities = set(cap_list)

            resolved = 0
            headers = (
                {}
                if not args.agent_token
                else {"Authorization": f"Bearer {args.agent_token}"}
            )
            for _ in range(args.rounds):
                count_this_round = 0
                r = await client.get("/api/reasoning-tasks", headers=headers)
                r.raise_for_status()
                for entry in r.json():
                    if not _can_handle(entry.get("required_capability"), capabilities):
                        continue
                    r2 = await client.post(
                        f"/api/reasoning-tasks/{entry['id']}/claim",
                        json={
                            "agent_name": args.agent_name,
                            "capabilities": list(capabilities),
                        },
                        headers=headers,
                    )
                    r2.raise_for_status()
                    task = _task_from_dict(r2.json())
                    result = provider.resolve(task)
                    r3 = await client.post(
                        f"/api/reasoning-tasks/{task.id}/result",
                        json={"result": result},
                        headers=headers,
                    )
                    r3.raise_for_status()
                    resolved += 1
                    count_this_round += 1
                if count_this_round == 0:
                    break

            if on_result is not None:
                on_result({"resolved": resolved})
            else:
                print(f"resolved {resolved} reasoning task(s)")
            return 0

        if args.command == "tick":
            resp = await client.post("/api/tick")
            resp.raise_for_status()
            summary = resp.json()
            if on_result is not None:
                on_result(summary)
            else:
                print(summary)
            return 0

        if args.command == "preflight":
            params = {"owner": args.owner}
            if args.charity_id:
                params["charity_id"] = args.charity_id
            if args.amount_cents is not None:
                params["amount_cents"] = args.amount_cents
            resp = await client.get("/api/preflight", params=params)
            resp.raise_for_status()
            summary = resp.json()
            if on_result is not None:
                on_result(summary)
            else:
                print(summary)
            return 0 if summary.get("ready") else 1

        if args.command == "outbox":
            headers = (
                {}
                if not args.agent_token
                else {"Authorization": f"Bearer {args.agent_token}"}
            )
            r = await client.get("/api/outbox", params={"owner": args.owner}, headers=headers)
            r.raise_for_status()
            messages = r.json()
            relayed = 0
            for msg in messages:
                marked = await client.post(f"/api/coach/{msg['id']}/delivered", headers=headers)
                marked.raise_for_status()
                relayed += 1
            if on_result is not None:
                on_result({"relayed": relayed})
            else:
                print(f"relayed {relayed} coaching message(s)")
            return 0

    finally:
        if own_client:
            await client.aclose()

    # Should not reach here.
    return 2  # pragma: no cover


def main(argv=None) -> int:
    """Sync console-script entrypoint. Parses argv and dispatches via asyncio.run.

    Unknown subcommands return 2 without raising, so the shell sees a non-zero
    exit code.
    """
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        # argparse exits with status 2 on unknown commands/flags; catch and return
        # the exit code so callers get a non-zero int instead of a raised exception.
        return int(exc.code) if exc.code is not None else 2

    if args.command is None:
        parser.print_help()
        return 2

    if args.command not in ("serve", "tick", "preflight", "outbox", "mcp"):
        parser.print_help()
        return 2

    if args.command == "mcp":
        from .mcp import main as mcp_main

        return mcp_main(
            [
                "--base-url",
                args.base_url,
                *(
                    ["--agent-token", args.agent_token]
                    if args.agent_token
                    else []
                ),
            ]
        )

    return asyncio.run(main_async(argv))
